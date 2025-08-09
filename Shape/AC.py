import numpy as np
import wave
import threading
import pyaudio
import tempfile
import os
from collections import deque
from live2d.utils.lipsync import WavHandler

class AudioController:
    """修复的音频控制器，支持低延迟队列播放"""
    
    def __init__(self):
        self.wav_handler = WavHandler()
        self.pyaudio = pyaudio.PyAudio()
        
        # 任务队列
        self.task_queue = deque()
        self.lock = threading.Lock()
        self.playing = False
        self.should_stop = False
        
        self.stream = None
        self.setup_stream()
        # 工作线程
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def setup_stream(self):
        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
            
            self.stream = self.pyaudio.open(
                format=self.pyaudio.get_format_from_width(2),
                channels=2,
                rate=44100,
                output=True,
                frames_per_buffer=1024
            )
        except Exception as e:
            print(f"设置音频流时出错: {e}")

    def _worker(self):
        """队列处理工作线程"""
        while not self.should_stop:
            file_path = None
            
            with self.lock:
                if self.task_queue and not self.playing:
                    file_path = self.task_queue.popleft()
                    self.playing = True
            
            if file_path:
                self._play_file(file_path)
                with self.lock:
                    self.playing = False
                # 清理临时文件
                if file_path.startswith(tempfile.gettempdir()):
                    try:
                        os.unlink(file_path)
                    except:
                        pass
            else:
                threading.Event().wait(0.01)  # 10ms检查间隔
    
    def _play_file(self, file_path):
        """播放WAV文件"""
        try:
            # 启动口型同步
            self.wav_handler.Start(file_path)
            print(f"开始播放: {file_path}")
            
            with wave.open(file_path, 'rb') as wf:
                # 检查是否需要重新配置流
                if (wf.getsampwidth() != self.stream._format // 8 or 
                    wf.getnchannels() != self.stream._channels or
                    wf.getframerate() != self.stream._rate):
                    self.setup_stream()
                
                # 播放音频数据
                while self.playing and not self.should_stop:
                    data = wf.readframes(1024)
                    if not data:
                        break
                    self.stream.write(data)
                
                print("播放完成")
                
        except Exception as e:
            print(f"播放失败: {e}")
    
    def add_file_task(self, file_path: str):
        """添加文件任务"""
        if not os.path.exists(file_path):
            print(f"文件不存在: {file_path}")
            return
            
        with self.lock:
            self.task_queue.append(file_path)
        print(f"已添加任务: {file_path}")
    
    def add_stream_task(self, audio_data: bytes):
        """添加流式音频任务（转换为临时WAV文件）"""
        if not audio_data:
            print("音频数据为空")
            return
            
        try:
            self.stream.write(audio_data)
            self.wav_handler.StartFromMemory(audio_data)
        except Exception as e:
            print(f"wav_handler: {e}")

    def update_lipsync(self):
        """获取口型同步RMS值"""
        if self.wav_handler.Update():
            return self.wav_handler.GetRms()
        return 0.0
    
    def stop(self):
        """停止播放并清空队列"""
        print("停止播放...")
        with self.lock:
            self.playing = False
            self.task_queue.clear()
        self.wav_handler.ReleasePcmData()
        if self.stream is not None:
            self.stream.stop_stream()
    
    def is_busy(self):
        """检查是否忙碌"""
        with self.lock:
            return self.playing or len(self.task_queue) > 0
    
    def get_queue_size(self):
        """获取队列大小"""
        with self.lock:
            return len(self.task_queue)
    
    def __del__(self):
        """析构函数"""
        self.should_stop = True
        self.stop()
        if hasattr(self, 'pyaudio'):
            self.pyaudio.terminate()