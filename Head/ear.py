import numpy as np
import time
import json
from loguru import logger
from typing import Optional
import asyncio
import websockets
import pyaudio
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication
import threading
import io
import sys
from dotmap import DotMap
import toml
config = DotMap(toml.load("config.toml"))
class ASR(QThread):
    """
    参考 client_wss.html 重新设计的 ASR 类
    使用定时发送音频数据的方式，简化连接逻辑
    """
    # 定义信号
    hearStart = pyqtSignal()
    transcriptionStart = pyqtSignal()
    transcriptionReady = pyqtSignal(str)  # 转录文本信号
    errorOccurred = pyqtSignal(str)       # 错误信号
    
    def __init__(self, url: str = "ws://127.0.0.1:8001/ws/transcribe",
                 lang: str = "auto",
                 sv: int = 0,
                 sample_rate: int = 16000,
                 channels: int = 1,
                 chunk_size: int = 4096):
        super().__init__()
        
        # WebSocket 配置
        base_url = url.split('?')[0]  # 移除可能存在的查询参数
        query_params = []
        if lang:
            query_params.append(f"lang={lang}")
        if sv:
            query_params.append(f"sv={sv}")
        query_string = '?' + '&'.join(query_params) if query_params else ''
        self.url = base_url + query_string

        # 运行状态
        self.running = False
        self.ws = None
        self.is_hearing = False  # 是否正在听到声音
        # 音频配置
        self.format = pyaudio.paInt16
        self.channels = channels
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # 音频组件
        self.pyaudio_instance = None
        self.audio_stream = None
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        
        # 事件循环
        self.event_loop = None

        logger.info(f"ASR 初始化完成: URL={self.url}, 采样率={self.sample_rate}")

    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数 - 收集音频数据到缓冲区"""
        try:
            with self.buffer_lock:
                # 将新的音频数据添加到缓冲区
                self.audio_buffer.append(in_data)
        except Exception as e:
            logger.error(f"音频回调错误: {e}")
        return (None, pyaudio.paContinue)

    def get_and_clear_audio_buffer(self):
        """获取并清空音频缓冲区"""
        with self.buffer_lock:
            if not self.audio_buffer:
                return None
            
            # 合并所有音频数据
            audio_data = b''.join(self.audio_buffer)
            self.audio_buffer.clear()
            return audio_data

    async def send_audio_data(self):
        """发送音频数据"""
        try:
            while self.running and self.ws:
                # 获取音频数据
                audio_data = self.get_and_clear_audio_buffer()
                
                if audio_data and len(audio_data) > 0:
                    try:
                        await self.ws.send(audio_data)
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("WebSocket 连接已关闭")
                        break
                    except Exception as e:
                        logger.error(f"发送音频数据错误: {e}")
                        break
                
                # 使用很小的延迟以避免CPU过度使用
                await asyncio.sleep(0.5)
                
        except asyncio.CancelledError:
            logger.info("音频发送已停止")
        except Exception as e:
            logger.error(f"发送音频数据过程错误: {e}")

    async def receive_messages(self):
        """接收 WebSocket 消息"""
        if not self.ws:
            logger.error("WebSocket 连接未建立")
            return
            
        try:
            async for message in self.ws:
                try:
                    res_json = json.loads(message)
                    logger.debug(f"收到消息: {res_json}")
                    
                    # 处理检测到语音/说话人的信号
                    if res_json.get("code") == 1:
                        info = res_json.get("info", "")
                        logger.info(f"检测到语音活动: {info}")
                        self.is_hearing = True
                        self.hearStart.emit()
                            

                    
                    # 处理转录结果
                    elif res_json.get("code") == 0:
                        transcription = res_json.get("data", "")
                        if transcription.strip():
                            logger.info(f"转录结果: {transcription}")
                            
                            # 发射转录完成信号
                            self.transcriptionReady.emit(transcription)
                            # 重置状态
                            self.is_hearing = False
                            
                except json.JSONDecodeError:
                    logger.error(f"解析响应失败: {message}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket 接收连接已关闭")
        except Exception as e:
            logger.error(f"接收消息错误: {e}")
            self.errorOccurred.emit(f"接收消息错误: {e}")

    async def start_websocket_session(self):
        """启动 WebSocket 会话"""
        try:
            logger.info(f"正在连接到 {self.url}...")
            
            async with websockets.connect(self.url) as ws:
                self.ws = ws
                logger.info("WebSocket 连接已建立")
                
                # 启动音频流
                self.setup_audio_stream()
                
                # 创建并行任务
                send_task = asyncio.create_task(self.send_audio_data())
                receive_task = asyncio.create_task(self.receive_messages())
                
                # 等待任务完成
                await asyncio.gather(send_task, receive_task, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"WebSocket 连接错误: {e}")
            self.errorOccurred.emit(f"连接错误: {e}")
        finally:
            self.ws = None

    def setup_audio_stream(self):
        """设置音频流"""
        try:
            self.pyaudio_instance = pyaudio.PyAudio()
            
            self.audio_stream = self.pyaudio_instance.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=self.audio_callback
            )
            
            logger.info(f"音频流已启动 - 采样率: {self.sample_rate}, 通道: {self.channels}, 块大小: {self.chunk_size}")
            
        except Exception as e:
            logger.error(f"设置音频流失败: {e}")
            raise e

    def run(self):
        """线程运行入口"""
        try:
            self.running = True
            
            # 创建事件循环
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            # 运行 WebSocket 会话
            self.event_loop.run_until_complete(self.start_websocket_session())
            
        except Exception as e:
            logger.error(f"ASR 运行错误: {e}")
            self.errorOccurred.emit(f"运行错误: {e}")
        finally:
            self.cleanup()

    def stop(self):
        """停止识别"""
        logger.info("正在停止 ASR...")
        self.running = False
        
        # 停止事件循环
        if self.event_loop and self.event_loop.is_running():
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)

    def cleanup(self):
        """清理资源"""
        logger.info("正在清理 ASR 资源...")
        
        # 重置状态
        self.is_hearing = False
        
        # 清理音频资源
        if self.audio_stream:
            try:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            except Exception as e:
                logger.error(f"关闭音频流错误: {e}")
                
        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
                self.pyaudio_instance = None
            except Exception as e:
                logger.error(f"终止 PyAudio 错误: {e}")
        
        # 清理缓冲区
        with self.buffer_lock:
            self.audio_buffer.clear()
        
        # 清理事件循环
        if self.event_loop and not self.event_loop.is_closed():
            try:
                # 取消所有剩余任务
                pending = asyncio.all_tasks(self.event_loop)
                for task in pending:
                    task.cancel()
                
                self.event_loop.close()
                self.event_loop = None
            except Exception as e:
                logger.error(f"关闭事件循环错误: {e}")
        
        logger.info("ASR 资源清理完成")

    def reset_state(self):
        """重置听音和转录状态"""
        self.is_hearing = False
        logger.info("ASR 状态已重置")

    def get_status(self):
        """获取当前状态"""
        return {
            'running': self.running,
            'url': self.url,
            'sample_rate': self.sample_rate,
            'channels': self.channels,
            'connected': self.ws is not None,
            'is_hearing': self.is_hearing
        }

def detect_voice():
    logger.info("检测到语音活动，开始识别...")

def start_recognition():
    logger.info("开始语音识别...")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    asr = ASR(url=config.asr.settings.url)
    asr.hearStart.connect(detect_voice)
    asr.transcriptionStart.connect(start_recognition)
    asr.run()