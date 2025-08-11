import numpy as np
import soundfile as sf
import time
import os
import re
from loguru import logger
import json
from typing import Optional, Dict, List, Tuple, Union
import asyncio
import websockets
import pyaudio
from PyQt6.QtCore import QThread, pyqtSignal

class ASR(QThread):
    """
    WebSocket-based 语音识别线程类
    实现实时语音识别和处理
    """
    # 定义信号
    transcriptionReady = pyqtSignal(str)  # 转录文本信号
    errorOccurred = pyqtSignal(str)       # 错误信号
    
    def __init__(self, url: str = "ws://127.0.0.1:8001/ws/transcribe",
                 lang: str = "auto",
                 sv: int = 0,
                 sample_rate: int = 16000,
                 channels: int = 1,
                 chunk_size: int = 512):
        super().__init__()
        self.url = f"{url}?lang={lang}&sv={sv}"
        self.running = False
        self.audio_queue = asyncio.Queue()
        self.event_loop = None
        
        # 音频设置
        self.format = pyaudio.paInt16
        self.channels = channels
        self.rate = sample_rate
        self.chunk = chunk_size
        self.audio_stream = None
        self.pyaudio = None
        
    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频数据回调函数"""
        try:
            if self.event_loop and self.running:
                asyncio.run_coroutine_threadsafe(
                    self.audio_queue.put(in_data), 
                    self.event_loop
                )
        except Exception as e:
            logger.error(f"音频回调错误: {e}")
        return (None, pyaudio.paContinue)
    
    async def record_and_send(self, ws):
        """录制并发送音频数据"""
        try:
            while self.running:
                audio_data = await self.audio_queue.get()
                try:
                    await ws.send(audio_data)
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket连接已关闭")
                    break
                except Exception as e:
                    logger.error(f"发送数据错误: {e}")
                    break
        except asyncio.CancelledError:
            logger.info("音频录制已停止")
        except Exception as e:
            logger.error(f"录制过程错误: {e}")

    async def receive_messages(self, ws):
        """接收并处理WebSocket消息"""
        try:
            async for message in ws:
                try:
                    res_json = json.loads(message)
                    if res_json.get("code") == 0:
                        transcription = res_json.get("data", "")
                        # 发送信号而不是调用回调
                        self.transcriptionReady.emit(transcription)
                except json.JSONDecodeError:
                    logger.error(f"解析响应失败: {message}")
        except Exception as e:
            self.errorOccurred.emit(str(e))
            logger.error(f"接收消息错误: {e}")

    async def process(self):
        """主处理循环"""
        try:
            async with websockets.connect(self.url) as ws:
                logger.info("WebSocket连接已建立")
                record_task = asyncio.create_task(self.record_and_send(ws))
                receive_task = asyncio.create_task(self.receive_messages(ws))
                await asyncio.gather(record_task, receive_task)
        except Exception as e:
            self.errorOccurred.emit(str(e))
            logger.error(f"WebSocket错误: {e}")

    def setup_audio(self, device_index: Optional[int] = None):
        """设置音频设备"""
        self.pyaudio = pyaudio.PyAudio()
        try:
            self.audio_stream = self.pyaudio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
                input_device_index=device_index,
                stream_callback=self.audio_callback
            )
        except Exception as e:
            logger.error(f"音频设备设置失败: {e}")
            raise e

    def run(self):
        """线程运行入口"""
        self.running = True
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        
        try:
            self.event_loop.run_until_complete(self.process())
        except Exception as e:
            self.errorOccurred.emit(str(e))
        finally:
            self.stop()
            self.event_loop.close()

    def stop(self):
        """停止识别"""
        self.running = False
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pyaudio:
            self.pyaudio.terminate()
        self.wait()  # 等待线程完成
