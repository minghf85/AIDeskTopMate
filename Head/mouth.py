import threading
from queue import Queue
from collections import deque
import pyaudio as pa
import time
import wave
import requests
import io
import os
import numpy as np  # 添加这行
from datetime import datetime
from live2d.utils.lipsync import WavHandler
from requests.auth import CONTENT_TYPE_FORM_URLENCODED
from dotmap import DotMap
import toml
import streamlit as st

from RealtimeTTS import TextToAudioStream, AzureEngine, EdgeEngine, KokoroEngine

# 读取toml的live2d配置
config = DotMap(toml.load("config.toml"))

class Mouth:
    def __init__(self, audio_save = False):
        self.wav_handler = WavHandler()


class TTS_GSV(Mouth):
    def __init__(self, stream=None):
        super().__init__()
        self.baseurl = config.tts.baseurl
        self.tts_settings = config.tts.settings
        self.p = pa.PyAudio()
        self.text_queue = Queue()
        self.running = False
        self.audio_thread = None
        self.tts_thread = None
        self.stream_thread = None
        self.initial_text = self.tts_settings.get("text")
        self.full_text = self.initial_text
        self.text_ready = threading.Event()

    def _synthesize_text(self, text):
        try:
            print(f"正在合成文本: {text}")
            self.tts_settings["text"] = text
            
            url = f"{self.baseurl}/tts"
            response = requests.post(
                url,
                json=dict(self.tts_settings),
                stream=True,
                headers={'Accept': 'audio/x-wav'}
            )
            
            if response.status_code == 200:
                audio_buffer = bytearray()
                first_chunk = True
                for chunk in response.iter_content(chunk_size=1024 * 4):
                    if not self.running:
                        break
                    
                    if chunk:
                        # 处理第一个数据块
                        if first_chunk:
                            if chunk.startswith(b'RIFF'):
                                # 从WAV头中获取音频参数
                                with io.BytesIO(chunk) as wav_io:
                                    with wave.open(wav_io, 'rb') as wav:
                                        sample_rate = wav.getframerate()
                                        channels = wav.getnchannels()
                                        width = wav.getsampwidth()
                                        print(f"音频参数: {sample_rate}Hz, {channels}通道, {width*8}位")
                                # 移除WAV头
                                chunk = chunk[44:]
                            first_chunk = False
                        
                        if len(chunk) > 0:
                            audio_buffer.extend(chunk)
                            # 当缓冲区足够大时再发送给播放器
                            if len(audio_buffer) >= 4096:
                                self.wav_handler.ProcessData(bytes(audio_buffer))
                                audio_buffer.clear()

                # 处理剩余的音频数据
                if audio_buffer:
                    self.wav_handler.ProcessData(bytes(audio_buffer))
                
                print(f"文本合成完成: {text}")
            else:
                print(f"语音合成失败: {response.text}")
                
        except Exception as e:
            print(f"处理文本时出错: {e}")
            
    def _create_wav_header(self, sample_rate=32000, channels=1, sample_width=2):
        """创建WAV文件头"""
        header = io.BytesIO()
        with wave.open(header, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.setnframes(0)
        header.seek(0)
        return header.read()

    def process_text(self):
        """处理文本并生成音频"""
        # 如果有初始文本，先处理它
        if self.initial_text and self.running:
            print(f"处理初始文本: {self.initial_text}")
            self._synthesize_text(self.initial_text)
            self.initial_text = None  # 清除初始文本，避免重复处理
        
        while self.running:
            try:
                if not self.text_queue.empty():
                    text = self.text_queue.get()
                    if text:
                        self._synthesize_text(text)
            except Exception as e:
                print(f"TTS处理错误: {e}")
                time.sleep(1)
            time.sleep(0.001)
            
    def start(self):
        """启动TTS系统"""
        if self.running:
            return
            
        self.running = True
        
        # 启动TTS线程
        self.tts_thread = threading.Thread(target=self.process_text)
        self.tts_thread.daemon = True
        self.tts_thread.start()
        
    def stop(self):
        """停止TTS系统"""
        print("正在停止TTS系统...")
        
        # 首先设置运行状态为False
        self.running = False
        requests.get(f"{self.baseurl}/interrupt")
        # 立即清空文本队列
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except:
                pass
        
        # 完全清理和重置音频播放器
        if self.audio_player:
            self.audio_player.clear()
        
        # 完全停止音频播放器
        if self.audio_player:
            self.audio_player.stop()
            
        # 等待线程结束
        if self.audio_thread:
            self.audio_thread.join(timeout=1.0)
        if self.tts_thread:
            self.tts_thread.join(timeout=1.0)
        if self.stream_thread:
            self.stream_thread.join(timeout=1.0)
            
    def add_text(self, text):
        """添加文本到队列"""
        if self.running:
            self.text_queue.put(text)

class TTS_realtime(Mouth):
    def __init__(self, stream=None):
        super().__init__()
        self.stream = stream
        if config.tts.settings.engine == "azure":
            self.engine = AzureEngine()
        elif config.tts.settings.engine == "edge":
            self.engine = EdgeEngine()
        elif config.tts.settings.engine == "kokoro":
            self.engine = KokoroEngine()
        else:
            raise ValueError("未知的 TTS 引擎")
        
        self.audio_stream = TextToAudioStream(self.engine)
    
    def speak(self, text):
        """将文本添加到音频流中"""
        self.audio_stream.feed(text)
        self.audio_stream.play_async()


if __name__ == "__main__":
    tts = TTS_realtime()

