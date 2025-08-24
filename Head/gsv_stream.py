import threading
import pyaudio as pa
import numpy as np
import toml
from utils.log_manager import LogManager

# Initialize logging
log_manager = LogManager()
logger = log_manager.get_logger('gsv')
import httpx
import asyncio
import queue
import struct
import time
from typing import Union, Iterator, AsyncGenerator
config_json = toml.load("config.toml")

# 全局配置
SENTENCE_SILENCE_DURATION = 0.15  # 句子间静音时长（秒）
EDGE_SILENCE_START_MS = 20  # 音频开头静音时长（毫秒）
EDGE_SILENCE_END_MS = 20  # 音频结尾静音时长（毫秒）

class GSVStream:
    """GSV TTS 流处理器 - 低延迟队列异步并行版本"""
    
    def __init__(self, on_audio_stream_start=None, on_audio_stream_stop=None,
                 on_character=None, on_text_stream_start=None, on_text_stream_stop=None):
        # 回调函数
        self.on_audio_stream_start = on_audio_stream_start
        self.on_audio_stream_stop = on_audio_stream_stop
        self.on_character = on_character
        self.on_text_stream_start = on_text_stream_start
        self.on_text_stream_stop = on_text_stream_stop


        # 状态变量
        self._current_text = ""
        self._is_playing = False
        self._input_data = None
        self._text_stream_started = False  # 文本流是否已开始
        self._audio_started = False  # 音频是否已开始播放


        
        # 配置
        self.tts_url = config_json["tts"]["base_url"]
        self.tts_settings = config_json["tts"]["settings"].copy()
        self.tts_settings["streaming_mode"] = True
        self.tts_settings["media_type"] = "wav"
        self.text_chunk_size = config_json["tts"]["text_chunk_size"]
        self.end_punctuation = config_json["tts"]["end_punctuation"]
        self.sample_rate = 32000
        
        # 队列系统
        self.text_queue = asyncio.Queue()  # 存储文本片段
        self.audio_queue = queue.Queue()   # 存储音频数据
        
        # 音频播放
        self.p = pa.PyAudio()
        self.stream = None
        
        # 口型同步
        self._current_rms = 0.0
        self.last_mouth_value = 0.0
        self.smoothing_factor = 0.3
        

        
    def feed(self, input_data: Union[str, Iterator[str]]):
        """输入文本或文本迭代器"""
        self._input_data = input_data
        self._current_text = ""
    
    def play_async(self):
        """异步播放"""
        if self._input_data:
            threading.Thread(target=self._start_async_processing, daemon=True).start()
    
    def _start_async_processing(self):
        """启动异步处理"""
        # 重新初始化队列以避免事件循环绑定问题
        self.text_queue = asyncio.Queue()
        self.audio_queue = queue.Queue()
        asyncio.run(self._run_low_latency_system())
        
    def apply_edge_silence(self, audio_data, start_silence_ms=None, end_silence_ms=None):
        """对音频数据的开头和结尾应用静音处理（直接置零）"""
        if start_silence_ms is None:
            start_silence_ms = EDGE_SILENCE_START_MS
        if end_silence_ms is None:
            end_silence_ms = EDGE_SILENCE_END_MS
            
        if not audio_data or len(audio_data) < 4:
            return audio_data
        
        # 确保音频数据长度是偶数（16位音频每个样本2字节）
        if len(audio_data) % 2 != 0:
            audio_data = audio_data[:-1]
        
        # 转换为16位整数数组进行处理
        samples = list(struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data))
        
        # 计算开头和结尾需要静音的样本数
        start_silence_samples = min(int(32000 * start_silence_ms / 1000), len(samples) // 4)
        end_silence_samples = min(int(32000 * end_silence_ms / 1000), len(samples) // 4)
        
        # 将开头部分置零
        for i in range(start_silence_samples):
            if i < len(samples):
                samples[i] = 0
        
        # 将结尾部分置零
        for i in range(end_silence_samples):
            idx = len(samples) - 1 - i
            if idx >= 0 and idx >= start_silence_samples:  # 避免与开头重叠
                samples[idx] = 0
        
        # 转换回字节数据
        processed_audio = struct.pack('<' + 'h' * len(samples), *samples)
        return processed_audio
    
    async def _run_low_latency_system(self):
        """运行低延迟TTS系统"""
        try:
            # 触发文本流开始回调
            if self.on_text_stream_start:
                self.on_text_stream_start()
            
            self._is_playing = True
            self._text_stream_started = True  # 标记文本流已开始
            
            # 启动音频播放器线程
            audio_thread = threading.Thread(target=self.audio_player, daemon=True)
            audio_thread.start()
            

            
            # 处理输入数据
            if isinstance(self._input_data, str):
                # 普通文本 - 创建流式生成器
                text_stream = self._simulate_text_streaming(self._input_data)
            else:
                # 文本迭代器
                text_stream = self._process_text_iterator(self._input_data)
            
            # 并行运行文本累积器和TTS处理器
            await asyncio.gather(
                self.text_accumulator(text_stream),
                self.tts_processor()
            )
            
            # 等待音频播放完成
            audio_thread.join(timeout=10)
            
            # 触发文本流停止回调
            if self.on_text_stream_stop and self._text_stream_started:
                self.on_text_stream_stop()
                self._text_stream_started = False
                
        except Exception as e:
            logger.error(f"低延迟系统错误: {e}")
        finally:
            # 不在这里设置_is_playing = False，让audio_player线程自己控制播放状态
            pass
            
    async def _simulate_text_streaming(self, text: str) -> AsyncGenerator[str, None]:
        """模拟文本流式生成"""
        self._current_text = ""
        for char in text:
            self._current_text += char
            # 触发字符回调，模拟TextToAudioStream的行为
            if self.on_character:
                self.on_character(char)
            yield char
            await asyncio.sleep(0.001)  # 小延迟模拟流式
            
    async def _process_text_iterator(self, text_iterator) -> AsyncGenerator[str, None]:
        """处理文本迭代器"""
        for text_chunk in text_iterator:
            if text_chunk:
                # 按字符处理，从一开始就触发回调，不等音频开始
                for char in text_chunk:
                    self._current_text += char
                    if self.on_character:
                        self.on_character(char)
                    yield char
                    await asyncio.sleep(0.001)
            await asyncio.sleep(0.001)
    

      
    async def text_accumulator(self, text_stream: AsyncGenerator[str, None]):
        """文本累积器：收集文本片段并按标点符号分句发送给TTS
        
        分句逻辑：
        1. 按标点符号分句
        2. 如果分出的句子长度 < text_chunk_size，则累积到下一段
        3. 确保发送的句子长度达到阈值，避免过短导致播放间隔
        """
        accumulated_text = ""
        pending_text = ""  # 待发送的文本（长度不足时暂存）
        
        async for char in text_stream:
            accumulated_text += char
            
            # 检查是否遇到标点符号
            if char in self.end_punctuation:
                current_sentence = accumulated_text.strip()
                accumulated_text = ""
                
                if current_sentence:
                    # 将当前句子加入待发送文本
                    pending_text += current_sentence
                    
                    # 检查待发送文本长度是否达到阈值
                    if len(pending_text) >= self.text_chunk_size:
                        # logger.info(f"文本长度达到阈值({len(pending_text)}>={self.text_chunk_size})，发送到TTS队列: '{pending_text}'")
                        await self.text_queue.put(pending_text)
                        pending_text = ""
                    # else:
                    #     logger.info(f"文本长度不足({len(pending_text)}<{self.text_chunk_size})，累积到下一段: '{pending_text}'")
        
        # 处理剩余文本
        if accumulated_text.strip():
            pending_text += accumulated_text.strip()
        
        # 发送最后的待发送文本（无论长度是否达到阈值）
        if pending_text.strip():
            logger.info(f"发送最后文本片段到TTS队列: '{pending_text.strip()}'")
            await self.text_queue.put(pending_text.strip())
        
        # 发送结束信号
        await self.text_queue.put(None)
        logger.info("文本生成完成，发送结束信号")
    
    async def tts_processor(self):
        """TTS处理器：从文本队列获取文本并转换为音频"""
        logger.info("TTS处理器启动")
        
        while True:
            try:
                # 从队列获取文本
                text_chunk = await self.text_queue.get()
                
                if text_chunk is None:  # 结束信号
                    logger.info("TTS处理器收到结束信号")
                    self.audio_queue.put(None)  # 向音频队列发送结束信号
                    break
                
                logger.info(f"TTS开始处理文本: '{text_chunk}'")
                tts_start_time = time.time()
                
                # 发送TTS请求
                request_data = self.tts_settings.copy()
                request_data["text"] = text_chunk
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    async with client.stream('POST', self.tts_url, json=request_data) as response:
                        if response.status_code == 200:
                            chunk_count = 0
                            audio_chunks = []
                            
                            async for audio_chunk in response.aiter_bytes(chunk_size=1024):
                                if audio_chunk:
                                    chunk_count += 1
                                    audio_chunks.append(audio_chunk)
                                    
                                    if chunk_count == 1:
                                        first_chunk_time = time.time()
                                        tts_latency = (first_chunk_time - tts_start_time) * 1000
                                        logger.info(f"TTS首个音频块生成延迟: {tts_latency:.1f}ms")
                            
                            # 对音频数据应用边缘静音处理，然后发送
                            if audio_chunks:
                                # 合并所有音频块
                                complete_audio = b''.join(audio_chunks)
                                
                                # 对完整音频应用边缘静音处理
                                processed_audio = self.apply_edge_silence(complete_audio)
                                
                                # 将处理后的音频重新分块发送
                                chunk_size = 1024
                                for i in range(0, len(processed_audio), chunk_size):
                                    chunk = processed_audio[i:i+chunk_size]
                                    if chunk:
                                        self.audio_queue.put(chunk)
                                
                                # 添加句子间的静音分隔
                                silence_samples = int(32000 * SENTENCE_SILENCE_DURATION)
                                silence_data = b'\x00\x00' * silence_samples
                                self.audio_queue.put(silence_data)
                                logger.info(f"句子音频已处理，添加{SENTENCE_SILENCE_DURATION*1000:.0f}ms静音分隔")
                            
                            tts_end_time = time.time()
                            total_tts_time = (tts_end_time - tts_start_time) * 1000
                            logger.info(f"TTS处理完成，共生成{chunk_count}个音频块，总用时: {total_tts_time:.1f}ms")
                        else:
                            logger.error(f"TTS请求失败，状态码: {response.status_code}")
                            
            except Exception as e:
                logger.error(f"TTS处理出错: {e}")
    
    def audio_player(self):
        """音频播放器：从音频队列获取音频数据并连续播放"""
        logger.info("音频播放器启动")
        
        # 设置播放状态和重置状态变量
        self._is_playing = True
        self._audio_started = False
        
        # 初始化音频流，使用优化的参数以减少爆破音
        self.stream = self.p.open(
            format=pa.paInt16,
            channels=1,
            rate=32000,
            output=True,
            frames_per_buffer=1024,
            stream_callback=None,
            output_device_index=None
        )
        
        # 预热音频流，避免首次播放的延迟
        silence_warmup = b'\x00\x00' * 512
        self.stream.write(silence_warmup)
        
        first_play_time = None
        chunk_count = 0
        audio_buffer = b''  # 音频缓冲区
        min_buffer_size = 2048  # 最小缓冲区大小
        
        try:
            while True:
                try:
                    # 从队列获取音频数据
                    audio_chunk = self.audio_queue.get(timeout=0.1)
                    
                    if audio_chunk is None:  # 结束信号
                        logger.info("音频播放器收到结束信号，播放剩余缓冲区数据")
                        # 播放剩余的缓冲区数据
                        if audio_buffer:
                            self.stream.write(audio_buffer)
                            # 更新RMS值
                            audio_data = np.frombuffer(audio_buffer, dtype=np.int16)
                            self._update_rms(audio_data)
                            logger.info(f"播放最后缓冲区数据，大小: {len(audio_buffer)} bytes")
                        break
                    
                    chunk_count += 1
                    current_time = time.time()
                    
                    # 检测静音数据（连续的零字节）用于日志记录
                    is_silence = audio_chunk == b'\x00\x00' * (len(audio_chunk) // 2)
                    # if is_silence:
                    #     logger.info(f"播放静音分隔 #{chunk_count}，时长: {len(audio_chunk)/2/32000*1000:.0f}ms")
                    # else:
                    #     logger.info(f"播放音频块 #{chunk_count}，大小: {len(audio_chunk)} bytes")
                    
                    if first_play_time is None:
                        first_play_time = current_time
                        logger.info(f"开始播放音频，时间: {first_play_time:.3f}")
                    
                    # 将音频数据添加到缓冲区
                    audio_buffer += audio_chunk
                    
                    # 当缓冲区达到最小大小时开始播放
                    if len(audio_buffer) >= min_buffer_size:
                        # 检查是否是第一次播放真正的音频（非静音）
                        if not self._audio_started and not is_silence:
                            if self.on_audio_stream_start:
                                self.on_audio_stream_start()
                            self._audio_started = True
                            logger.info("触发音频流开始回调 - 开始播放真正的音频")
                        
                        # 播放缓冲区中的数据
                        self.stream.write(audio_buffer[:min_buffer_size])
                        # 更新RMS值
                        audio_data = np.frombuffer(audio_buffer[:min_buffer_size], dtype=np.int16)
                        self._update_rms(audio_data)
                        audio_buffer = audio_buffer[min_buffer_size:]
                    
                    if chunk_count % 20 == 0:
                        elapsed = (current_time - first_play_time) * 1000 if first_play_time else 0
                        # logger.info(f"播放进度: {chunk_count} 块，已播放: {elapsed:.1f}ms，缓冲区大小: {len(audio_buffer)}")
                        
                except queue.Empty:
                    # 队列为空时，如果缓冲区有数据就播放
                    if audio_buffer:
                        play_size = min(len(audio_buffer), 512)  # 播放小块数据
                        
                        # 检查是否是第一次播放真正的音频（非静音）
                        if not self._audio_started:
                            audio_data_check = np.frombuffer(audio_buffer[:play_size], dtype=np.int16)
                            is_silence_check = np.all(audio_data_check == 0)
                            if not is_silence_check:
                                if self.on_audio_stream_start:
                                    self.on_audio_stream_start()
                                self._audio_started = True
                                logger.info("触发音频流开始回调 - 开始播放真正的音频（队列空时）")
                        
                        self.stream.write(audio_buffer[:play_size])
                        # 更新RMS值
                        audio_data = np.frombuffer(audio_buffer[:play_size], dtype=np.int16)
                        self._update_rms(audio_data)
                        audio_buffer = audio_buffer[play_size:]
                    continue
                except Exception as e:
                    logger.error(f"音频播放出错: {e}")
                    break
        
        finally:
            if self.stream:
                # 确保音频流完全播放完毕
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except:
                    pass
            # 重置播放状态和RMS值
            self._is_playing = False
            self._current_rms = 0.0
            self.last_mouth_value = 0.0
            if self.on_audio_stream_stop:
                self.on_audio_stream_stop()
            logger.info(f"音频播放完成，共播放{chunk_count}个音频块，播放状态和RMS已重置")
    

    
    def _update_rms(self, audio_chunk):
        """更新RMS值"""
        if len(audio_chunk) == 0:
            self._current_rms = 0.0
            return
        
        audio_chunk = audio_chunk.astype(np.float32) / 32768.0
        rms = np.sqrt(np.mean(np.square(audio_chunk)))
        self._current_rms = rms
        
        mouth_value = min(rms ** 2.0, 1.0)
        self.last_mouth_value = (self.smoothing_factor * mouth_value + 
                                (1 - self.smoothing_factor) * self.last_mouth_value)
    
    def GetRms(self):
        """获取当前RMS值"""
        return self._current_rms
    
    def text(self):
        """获取当前文本"""
        return self._current_text
    
    def is_playing(self):
        """检查是否在播放"""
        return self._is_playing
    
    def stop(self):
        """停止播放"""
        logger.info("请求停止播放")
        self._is_playing = False
        # 重置状态变量
        self._audio_started = False
        # 重置RMS值
        self._current_rms = 0.0
        self.last_mouth_value = 0.0
        # 清空音频队列
        try:
            while True:
                self.audio_queue.get_nowait()
        except queue.Empty:
            pass
        # 发送结束信号
        self.audio_queue.put(None)
    
    def cleanup(self):
        """清理资源"""
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        self.p.terminate()
        logger.info("资源清理完成")

if __name__ == "__main__":
    # 设置日志级别
    logger.info("开始测试GSVStream...")
    
    def on_audio_start():
        logger.info("开始听到声音了")
    
    def on_audio_stop():
        logger.info("声音停止了")
    
    def on_character(char):
        logger.info(f"字符回调: {char}")
    
    def on_text_start():
        logger.info("文本流开始回调")
    
    def on_text_stop():
        logger.info("文本流停止回调")
    
    # 异步显示RMS值的函数
    async def display_rms_values(tts_instance, interval=0.1):
        """异步显示GetRms的值"""
        while tts_instance.is_playing():
            rms_value = tts_instance.GetRms()
            logger.info(f"当前RMS值: {rms_value:.4f}")
            await asyncio.sleep(interval)
        logger.info("RMS监控结束")
    
    # 启动RMS监控的函数
    def start_rms_monitoring(tts_instance):
        """启动RMS值监控"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(display_rms_values(tts_instance))
        finally:
            loop.close()
    

    
    tts = GSVStream(
        on_audio_stream_start=on_audio_start,
        on_audio_stream_stop=on_audio_stop,
        on_character=on_character,
        on_text_stream_start=on_text_start,
        on_text_stream_stop=on_text_stop
    )
    
    # 测试1: 普通文本
    test_text = "你好，我是李信，我是一个中国人，今天天气不错。"
    logger.info(f"测试普通文本: {test_text}")
    
    tts.feed(test_text)
    tts.play_async()
    # time.sleep(10)  # 等待10秒
    # tts.feed(test_text)
    # tts.play_async()
    # 等待播放完成
    import time
    logger.info("等待播放完成...")
    time.sleep(10)  # 等待10秒
    
    tts.stop()
    logger.info("普通文本测试完成")
    
    # 测试2: 文本迭代器
    def text_generator():
        """模拟流式文本生成"""
        test_text = "人工智能技术正在快速发展，深度学习和机器学习算法不断进步，为各行各业带来了革命性的变化。从自然语言处理到计算机视觉，从语音识别到智能推荐系统，AI技术已经深入到我们生活的方方面面。未来，随着技术的不断完善和应用场景的扩展，人工智能将会发挥更加重要的作用，推动社会进步和经济发展。"
        for text in list(test_text):
            time.sleep(0.03)  # 模拟生成延迟
            yield text
    
    logger.info("开始测试文本迭代器...")
    text_iterator = text_generator()
    
    # 创建新的TTS实例用于迭代器测试
    tts2 = GSVStream(
        on_audio_stream_start=on_audio_start,
        on_audio_stream_stop=on_audio_stop,
        on_character=on_character,
        on_text_stream_start=on_text_start,
        on_text_stream_stop=on_text_stop
    )
    
    tts2.feed(text_iterator)
    tts2.play_async()
    # tts2.feed(text_iterator)
    # tts2.play_async()
    logger.info("等待迭代器播放完成...")
    while tts2.is_playing():
        logger.info(f"当前RMS值: {tts2.GetRms():.4f}")
    time.sleep(50)  # 等待30秒
    
    logger.info("迭代器测试完成")
    tts2.stop()
    tts2.cleanup()
    tts.cleanup()
