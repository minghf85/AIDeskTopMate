import threading
from queue import Queue
from collections import deque
import pyaudio as pa
import os
import numpy as np
from datetime import datetime
from requests.auth import CONTENT_TYPE_FORM_URLENCODED
from dotmap import DotMap
import toml
from dotenv import load_dotenv
import loguru
import httpx
import asyncio
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

logger = loguru.logger

# 读取toml的live2d配置
config = DotMap(toml.load("config.toml"))
config_json = toml.load("config.toml")

class GSVStream:
    """GSV TTS 流处理器，模拟 TextToAudioStream 的接口"""
    
    def __init__(self, on_audio_stream_start=None, on_audio_stream_stop=None, 
                 on_word=None, on_character=None, on_text_stream_start=None, on_text_stream_stop=None):
        self.audio_player = pa.PyAudio()
        self.on_audio_stream_start = on_audio_stream_start
        self.on_audio_stream_stop = on_audio_stream_stop
        self.on_word = on_word
        self.on_character = on_character
        self.on_text_stream_start = on_text_stream_start
        self.on_text_stream_stop = on_text_stream_stop

        self._current_text = ""
        self._is_playing = False
        self._stop_requested = False
        self._text_iterator = None
        self._audio_stream = None
        
        # 队列系统
        self.text_queue = Queue()  # 文本队列
        self.audio_queue = Queue()  # 音频队列
        
        # 多线程处理
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.text_processor_thread = None
        self.audio_generator_thread = None
        self.audio_player_thread = None
        
        # 控制标志
        self._processing_active = False
        # TTS配置
        self.tts_url = config_json["tts"]["base_url"]
        self.tts_settings = config_json["tts"]["settings"]
        self.text_chunk_size = config_json["tts"]["text_chunk_size"]
        self.end_punctuation = config_json["tts"]["end_punctuation"]

        # RMS 和口型同步相关参数
        self.sample_rate = 32000
        self.smoothing_factor = 0.3
        self.last_mouth_value = 0.0
        self.silence_threshold = 0  # 静音阈值
        self.max_rms_scale = 0.1  # 最大RMS缩放，可以从配置读取
        self.mouth_scale = 1.0  # 整体嘴巴开合缩放
        self._current_rms = 0.0
        self._current_smoothed_value = 0.0
        
    def feed(self, text_iterator):
        """输入文本迭代器"""
        self._text_iterator = text_iterator
        self._current_text = ""
        
    def play_async(self):
        """异步播放"""
        if self._text_iterator:
            threading.Thread(target=self._play_thread, daemon=True).start()
    
    def _play_thread(self):
        """主播放线程，启动多线程处理管道"""
        try:
            if self.on_text_stream_start:
                self.on_text_stream_start()
            
            self._processing_active = True
            self._is_playing = True
            
            # 启动三个处理线程
            self.text_processor_thread = threading.Thread(target=self._text_processor, daemon=True)
            self.audio_generator_thread = threading.Thread(target=self._audio_generator, daemon=True)
            self.audio_player_thread = threading.Thread(target=self._audio_player, daemon=True)
            
            self.text_processor_thread.start()
            self.audio_generator_thread.start()
            self.audio_player_thread.start()
            
            # 等待文本处理完成
            if self.text_processor_thread:
                self.text_processor_thread.join()
            
            # 等待所有音频生成和播放完成
            if self.audio_generator_thread:
                self.audio_generator_thread.join()
            if self.audio_player_thread:
                self.audio_player_thread.join()
            
            if self.on_text_stream_stop:
                self.on_text_stream_stop()
                
        except Exception as e:
            logger.error(f"GSV播放线程错误: {e}")
        finally:
            self._processing_active = False
            self._is_playing = False
            self._stop_requested = False
    
    def _text_processor(self):
        """文本处理线程：收集文本并分段放入文本队列"""
        try:
            full_text = ""
            current_segment = ""
            
            if self._text_iterator:
                for text_chunk in self._text_iterator:
                    if self._stop_requested:
                        break
                    if text_chunk:
                        current_segment += text_chunk
                        full_text += text_chunk
                        self._current_text = full_text
                        
                        # 检查是否到了句子结束
                        if any(current_segment.endswith(p) for p in self.end_punctuation):
                            if len(current_segment) > self.text_chunk_size:
                                # 将文本段放入队列
                                self.text_queue.put(current_segment.strip())
                                current_segment = ""
                            else:
                                continue
                        
                        if self.on_character:
                            self.on_character(text_chunk)
            
            # 处理剩余的文本段
            if current_segment.strip():
                self.text_queue.put(current_segment.strip())
            
            # 发送结束信号
            self.text_queue.put(None)
            
        except Exception as e:
            logger.error(f"文本处理线程错误: {e}")
    
    def _audio_generator(self):
        """音频生成线程：从文本队列获取文本，生成音频数据放入音频队列"""
        try:
            while self._processing_active and not self._stop_requested:
                try:
                    # 从文本队列获取文本
                    text = self.text_queue.get(timeout=1.0)
                    if text is None:  # 结束信号
                        break
                    
                    # 生成音频数据
                    audio_data = asyncio.run(self._generate_audio_data(text))
                    if audio_data:
                        self.audio_queue.put(audio_data)
                    
                    self.text_queue.task_done()
                    
                except Exception as e:
                    if "timeout" not in str(e).lower():
                        logger.error(f"音频生成错误: {e}")
                        logger.error(f"音频生成错误详情: {traceback.format_exc()}")
                    continue
            
            # 发送结束信号
            self.audio_queue.put(None)
            
        except Exception as e:
            logger.error(f"音频生成线程错误: {e}")
    
    def _audio_player(self):
        """音频播放线程：从音频队列获取音频数据并播放"""
        audio_stream = None
        try:
            audio_started = False
            
            while self._processing_active and not self._stop_requested:
                try:
                    # 从音频队列获取音频数据
                    audio_data = self.audio_queue.get(timeout=1.0)
                    if audio_data is None:  # 结束信号
                        break
                    
                    if not audio_started:
                        # 创建音频流（只创建一次）
                        audio_stream = self.audio_player.open(
                            format=pa.paInt16,
                            channels=1,
                            rate=self.sample_rate,
                            output=True
                        )
                        if self.on_audio_stream_start:
                            self.on_audio_stream_start()
                        audio_started = True
                    
                    # 播放音频数据（使用持久的音频流）
                    self._play_audio_chunks_to_stream(audio_data, audio_stream)
                    self.audio_queue.task_done()
                    
                except Exception as e:
                    if "timeout" not in str(e).lower():
                        logger.error(f"音频播放错误: {e}")
                        logger.error(f"音频播放错误详情: {traceback.format_exc()}")
                    continue
            
            if audio_started and self.on_audio_stream_stop:
                self.on_audio_stream_stop()
                
        except Exception as e:
            logger.error(f"音频播放线程错误: {e}")
        finally:
            # 确保音频流被正确关闭
            if audio_stream:
                try:
                    audio_stream.stop_stream()
                    audio_stream.close()
                except:
                    pass
    
    def update_mouth_sync(self, audio_chunk):
        """更新口型同步，计算 RMS 值"""
        if audio_chunk is None or len(audio_chunk) == 0:
            self._current_rms = 0.0
            self._current_smoothed_value = 0.0
            return

        # 计算RMS值
        audio_chunk = audio_chunk.astype(np.float32) / 32768.0  # 标准化
        rms = np.sqrt(np.mean(np.square(audio_chunk)))
        self._current_rms = rms

        # 计算嘴巴开合值
        if rms < self.silence_threshold:
            mouth_value = 0.0
        else:
            normalized_rms = (rms - self.silence_threshold) / self.max_rms_scale
            mouth_value = min(normalized_rms ** 2.0, 1.0) * self.mouth_scale

        # 应用平滑处理
        smoothed_value = (self.smoothing_factor * mouth_value +
                          (1 - self.smoothing_factor) * self.last_mouth_value)

        self._current_smoothed_value = smoothed_value
        self.last_mouth_value = smoothed_value

        return smoothed_value

    def GetRms(self):
        """获取当前音频的 RMS 值"""
        return self._current_rms
    
    def text(self):
        """获取当前文本"""
        return self._current_text
    
    async def _generate_audio_data(self, text):
        """生成音频数据（不直接播放）"""
        try:
            # 准备TTS请求
            request_json = self.tts_settings.copy()
            request_json["text"] = text
            
            audio_chunks = []
            
            # 发送HTTP流式请求并收集音频数据
            async with httpx.AsyncClient(follow_redirects=True) as client:
                async with client.stream(
                    "POST",
                    self.tts_url,
                    json=request_json
                ) as response:
                    async for chunk in response.aiter_bytes(chunk_size=1024):
                        if self._stop_requested:
                            break
                        if chunk:
                            audio_chunks.append(chunk)
            
            return audio_chunks
            
        except Exception as e:
            logger.error(f"音频数据生成错误: {e}")
            logger.error(f"音频数据生成错误详情: {traceback.format_exc()}")
            return None
    
    def _play_audio_chunks_to_stream(self, audio_chunks, audio_stream):
        """将音频数据播放到指定的音频流"""
        try:
            for chunk in audio_chunks:
                if self._stop_requested:
                    break
                if chunk:
                    # 播放音频块
                    audio_stream.write(chunk)
                    
                    # 更新口型同步
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    self.update_mouth_sync(audio_data)
                    
        except Exception as e:
            logger.error(f"音频播放错误: {e}")
            logger.error(f"音频播放错误详情: {traceback.format_exc()}")
    
    def _play_audio_data(self, audio_chunks):
        """播放音频数据（保留原方法以兼容性）"""
        try:
            # 创建音频流
            audio_stream = self.audio_player.open(
                format=pa.paInt16,
                channels=1,
                rate=self.sample_rate,
                output=True
            )
            
            try:
                self._play_audio_chunks_to_stream(audio_chunks, audio_stream)
            finally:
                audio_stream.stop_stream()
                audio_stream.close()
                
        except Exception as e:
            logger.error(f"音频播放错误: {e}")
    
    def is_playing(self):
        """检查是否在播放"""
        return self._is_playing
    
    async def _generate_and_play_audio(self, text):
        """生成并播放音频"""
        try:
            # 准备TTS请求
            request_json = self.tts_settings.copy()
            request_json["text"] = text
            
            # 创建音频流
            self._audio_stream = self.audio_player.open(
                format=pa.paInt16,
                channels=1,
                rate=self.sample_rate,
                output=True
            )
            
            # 发送HTTP流式请求并播放音频
            async with httpx.AsyncClient(follow_redirects=True) as client:
                async with client.stream(
                    "POST",
                    self.tts_url,
                    json=request_json
                ) as response:
                    await self._stream_audio(response)
                    
        except Exception as e:
            logger.error(f"音频生成播放错误: {e}")
        finally:
            if self._audio_stream:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
                self._audio_stream = None
    
    async def _stream_audio(self, response):
        """流式播放音频"""
        try:
            async for chunk in response.aiter_bytes(chunk_size=1024):
                if self._stop_requested:
                    break
                if chunk:
                    # 播放音频块
                    if self._audio_stream:
                        self._audio_stream.write(chunk)
                    
                    # 更新口型同步
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    self.update_mouth_sync(audio_data)
                    
        except Exception as e:
            logger.error(f"流式音频播放错误: {e}")
    
    def stop(self):
        """停止播放"""
        self._stop_requested = True
        self._processing_active = False
        self._is_playing = False
        
        # 清空队列
        try:
            while not self.text_queue.empty():
                self.text_queue.get_nowait()
        except:
            pass
        
        try:
            while not self.audio_queue.empty():
                self.audio_queue.get_nowait()
        except:
            pass
        
        # 停止旧的音频流（如果存在）
        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except:
                pass
            self._audio_stream = None
        
        # 等待线程结束
        if self.text_processor_thread and self.text_processor_thread.is_alive():
            self.text_processor_thread.join(timeout=1.0)
        if self.audio_generator_thread and self.audio_generator_thread.is_alive():
            self.audio_generator_thread.join(timeout=1.0)
        if self.audio_player_thread and self.audio_player_thread.is_alive():
            self.audio_player_thread.join(timeout=1.0)

