import os
import threading
import wave
import time
from pathlib import Path
from typing import Dict, Optional, List, Callable
from enum import Enum
from logger import get_logger

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("警告: pyaudio未安装，音频功能将受限")


class AudioState(Enum):
    """音频状态枚举"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    LOADING = "loading"


class AudioTrack:
    """音频轨道类"""
    
    def __init__(self, file_path: str, volume: float = 1.0):
        """初始化音频轨道
        
        Args:
            file_path: 音频文件路径
            volume: 音量 (0.0-1.0)
        """
        self.file_path = Path(file_path)
        self.volume = max(0.0, min(1.0, volume))
        self.state = AudioState.STOPPED
        self.stream = None
        self.wave_file = None
        self.audio_data = None
        self.sample_rate = None
        self.channels = None
        self.sample_width = None
        self.frames = None
        self.loop_count = 0
        self.callbacks: Dict[str, List[Callable]] = {
            'on_start': [],
            'on_stop': [],
            'on_pause': [],
            'on_resume': []
        }
    
    def _load_audio_data(self) -> bool:
        """加载音频数据
        
        Returns:
            bool: 是否加载成功
        """
        try:
            self.wave_file = wave.open(str(self.file_path), 'rb')
            self.sample_rate = self.wave_file.getframerate()
            self.channels = self.wave_file.getnchannels()
            self.sample_width = self.wave_file.getsampwidth()
            self.frames = self.wave_file.getnframes()
            self.audio_data = self.wave_file.readframes(self.frames)
            self.wave_file.close()
            return True
        except Exception as e:
            print(f"加载音频数据失败: {e}")
            return False
    
    def _play_audio(self, loops: int = 0) -> None:
        """播放音频的内部方法
        
        Args:
            loops: 循环次数
        """
        if not PYAUDIO_AVAILABLE or not hasattr(audio_manager, 'pyaudio_instance'):
            return
        
        try:
            self.stream = audio_manager.pyaudio_instance.open(
                format=audio_manager.pyaudio_instance.get_format_from_width(self.sample_width),
                channels=self.channels,
                rate=self.sample_rate,
                output=True
            )
            
            # 简单播放音频数据
            self.stream.write(self.audio_data)
            
        except Exception as e:
            print(f"播放音频失败: {e}")
    
    def add_callback(self, event: str, callback: Callable) -> None:
        """添加回调函数
        
        Args:
            event: 事件类型
            callback: 回调函数
        """
        if event in self.callbacks:
            self.callbacks[event].append(callback)
    
    def _trigger_callbacks(self, event: str) -> None:
        """触发回调函数
        
        Args:
            event: 事件类型
        """
        for callback in self.callbacks.get(event, []):
            try:
                callback(self)
            except Exception as e:
                print(f"回调函数执行失败: {e}")


class Audio:
    """管理音效的类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化音频管理器"""
        if self._initialized:
            return
        
        self._initialized = True
        self.logger = get_logger('audio')
        self.master_volume = 1.0
        self.muted = False
        self.tracks: Dict[str, AudioTrack] = {}
        self.audio_cache: Dict[str, any] = {}
        self.supported_formats = ['.wav']
        
        # 初始化pyaudio
        self._init_pyaudio()
        
        # 音频文件搜索路径
        self.audio_paths = [
            Path("./assets/audio"),
            Path("./audio"),
            Path("./sounds")
        ]
        
        # 创建音频目录
        self._create_audio_directories()
    
    def _init_pyaudio(self) -> bool:
        """初始化pyaudio
        
        Returns:
            bool: 是否初始化成功
        """
        if not PYAUDIO_AVAILABLE:
            self.logger.warning("pyaudio不可用，音频功能将受限")
            return False
        
        try:
            self.pyaudio_instance = pyaudio.PyAudio()
            self.logger.info("pyaudio初始化成功")
            return True
        except Exception as e:
            self.logger.error(f"pyaudio初始化失败: {e}")
            return False
    
    def _create_audio_directories(self) -> None:
        """创建音频目录"""
        for path in self.audio_paths:
            path.mkdir(parents=True, exist_ok=True)
        self.logger.info("音频目录创建完成")
    
    def load_audio(self, track_name: str, file_path: str, volume: float = 1.0) -> bool:
        """加载音频文件
        
        Args:
            track_name: 轨道名称
            file_path: 音频文件路径
            volume: 音量
            
        Returns:
            bool: 是否加载成功
        """
        try:
            # 查找音频文件
            audio_file = self._find_audio_file(file_path)
            if not audio_file:
                self.logger.error(f"音频文件未找到: {file_path}")
                return False
            
            # 检查格式支持
            if audio_file.suffix.lower() not in self.supported_formats:
                self.logger.warning(f"不支持的音频格式: {audio_file.suffix}")
            
            # 创建音频轨道
            track = AudioTrack(str(audio_file), volume)
            
            if PYAUDIO_AVAILABLE:
                # 加载音频数据
                if track._load_audio_data():
                    pass
                else:
                    self.logger.error(f"加载音频数据失败: {audio_file}")
                    return False
            
            self.tracks[track_name] = track
            self.logger.info(f"音频加载成功: {track_name} -> {audio_file}")
            return True
        except Exception as e:
            self.logger.error(f"加载音频失败: {e}")
            return False
    
    def _find_audio_file(self, file_path: str) -> Optional[Path]:
        """查找音频文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[Path]: 找到的文件路径
        """
        # 如果是绝对路径且存在
        path = Path(file_path)
        if path.is_absolute() and path.exists():
            return path
        
        # 在音频搜索路径中查找
        for search_path in self.audio_paths:
            full_path = search_path / file_path
            if full_path.exists():
                return full_path
            
            # 尝试添加支持的扩展名
            if not full_path.suffix:
                for ext in self.supported_formats:
                    test_path = full_path.with_suffix(ext)
                    if test_path.exists():
                        return test_path
        
        return None
    
    def play(self, track_name: str, loop: int = 0, fade_in: int = 0) -> bool:
        """播放音频
        
        Args:
            track_name: 轨道名称
            loop: 循环次数 (-1为无限循环)
            fade_in: 淡入时间(毫秒，暂不支持)
            
        Returns:
            bool: 是否播放成功
        """
        if not PYAUDIO_AVAILABLE:
            self.logger.warning("pyaudio不可用，无法播放音频")
            return False
        
        if track_name not in self.tracks:
            self.logger.error(f"音频轨道不存在: {track_name}")
            return False
        
        if self.muted:
            self.logger.info(f"音频已静音，跳过播放: {track_name}")
            return False
        
        try:
            track = self.tracks[track_name]
            track.loop_count = loop
            
            # 停止当前播放
            if track.stream and track.stream.is_active():
                track.stream.stop_stream()
                track.stream.close()
            
            # 开始新的播放
            track._play_audio(loop)
            track.state = AudioState.PLAYING
            track._trigger_callbacks('on_start')
            
            self.logger.debug(f"音频播放开始: {track_name}")
            return True
        except Exception as e:
            self.logger.error(f"播放音频失败: {e}")
            return False
    
    def stop(self, track_name: str, fade_out: int = 0) -> bool:
        """停止音频
        
        Args:
            track_name: 轨道名称
            fade_out: 淡出时间(毫秒)
            
        Returns:
            bool: 是否停止成功
        """
        if track_name not in self.tracks:
            return False
        
        try:
            track = self.tracks[track_name]
            
            if track.stream and track.stream.is_active():
                track.stream.stop_stream()
                track.stream.close()
                track.stream = None
            
            track.state = AudioState.STOPPED
            track._trigger_callbacks('on_stop')
            
            self.logger.debug(f"音频停止: {track_name}")
            return True
        except Exception as e:
            self.logger.error(f"停止音频失败: {e}")
            return False
    
    def pause(self, track_name: str) -> bool:
        """暂停音频
        
        Args:
            track_name: 轨道名称
            
        Returns:
            bool: 是否暂停成功
        """
        if not PYAUDIO_AVAILABLE or track_name not in self.tracks:
            return False
        
        try:
            track = self.tracks[track_name]
            if track.stream and track.stream.is_active():
                track.stream.stop_stream()
                track.state = AudioState.PAUSED
                track._trigger_callbacks('on_pause')
                self.logger.debug(f"音频暂停: {track_name}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"暂停音频失败: {e}")
            return False
    
    def resume(self, track_name: str) -> bool:
        """恢复音频
        
        Args:
            track_name: 轨道名称
            
        Returns:
            bool: 是否恢复成功
        """
        if not PYAUDIO_AVAILABLE or track_name not in self.tracks:
            return False
        
        try:
            track = self.tracks[track_name]
            if track.state == AudioState.PAUSED and track.stream:
                track.stream.start_stream()
                track.state = AudioState.PLAYING
                track._trigger_callbacks('on_resume')
                self.logger.debug(f"音频恢复: {track_name}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"恢复音频失败: {e}")
            return False
    
    def set_volume(self, track_name: str, volume: float) -> bool:
        """设置音频音量
        
        Args:
            track_name: 轨道名称
            volume: 音量 (0.0-1.0)
            
        Returns:
            bool: 是否设置成功
        """
        if track_name not in self.tracks:
            return False
        
        try:
            volume = max(0.0, min(1.0, volume))
            track = self.tracks[track_name]
            track.volume = volume
            
            # PyAudio不直接支持音量控制，需要在播放时处理音频数据
            self.logger.debug(f"音量设置: {track_name} -> {volume}")
            return True
        except Exception as e:
            self.logger.error(f"设置音量失败: {e}")
            return False
    
    def set_master_volume(self, volume: float) -> None:
        """设置主音量
        
        Args:
            volume: 主音量 (0.0-1.0)
        """
        self.master_volume = max(0.0, min(1.0, volume))
        
        # PyAudio需要在播放时应用音量
        self.logger.info(f"主音量设置为: {self.master_volume}")
    
    def mute(self) -> None:
        """静音"""
        self.muted = True
        self.stop_all()
        self.logger.info("音频已静音")
    
    def unmute(self) -> None:
        """取消静音"""
        self.muted = False
        self.logger.info("音频取消静音")
    
    def stop_all(self) -> None:
        """停止所有音频"""
        for track_name in list(self.tracks.keys()):
            self.stop(track_name)
        self.logger.info("所有音频已停止")
    
    def is_playing(self, track_name: str) -> bool:
        """检查音频是否正在播放
        
        Args:
            track_name: 轨道名称
            
        Returns:
            bool: 是否正在播放
        """
        if track_name not in self.tracks:
            return False
        
        track = self.tracks[track_name]
        return (track.state == AudioState.PLAYING and 
                track.stream and track.stream.is_active())
    
    def get_track_info(self, track_name: str) -> Optional[Dict]:
        """获取轨道信息
        
        Args:
            track_name: 轨道名称
            
        Returns:
            Optional[Dict]: 轨道信息
        """
        if track_name not in self.tracks:
            return None
        
        track = self.tracks[track_name]
        return {
            'name': track_name,
            'file_path': str(track.file_path),
            'volume': track.volume,
            'state': track.state.value,
            'is_playing': self.is_playing(track_name)
        }
    
    def list_tracks(self) -> List[str]:
        """列出所有轨道
        
        Returns:
            List[str]: 轨道名称列表
        """
        return list(self.tracks.keys())
    
    def unload_track(self, track_name: str) -> bool:
        """卸载音频轨道
        
        Args:
            track_name: 轨道名称
            
        Returns:
            bool: 是否卸载成功
        """
        if track_name not in self.tracks:
            return False
        
        self.stop(track_name)
        del self.tracks[track_name]
        self.logger.info(f"音频轨道已卸载: {track_name}")
        return True
    
    def cleanup(self) -> None:
        """清理资源"""
        self.stop_all()
        self.tracks.clear()
        self.audio_cache.clear()
        
        if PYAUDIO_AVAILABLE and hasattr(self, 'pyaudio_instance'):
            self.pyaudio_instance.terminate()
        
        self.logger.info("音频管理器已清理")


# 创建全局音频管理器实例
audio_manager = Audio()

# 便捷函数
def load_audio(track_name: str, file_path: str, volume: float = 1.0) -> bool:
    """加载音频的便捷函数"""
    return audio_manager.load_audio(track_name, file_path, volume)

def play_audio(track_name: str, loop: int = 0) -> bool:
    """播放音频的便捷函数"""
    return audio_manager.play(track_name, loop)

def stop_audio(track_name: str) -> bool:
    """停止音频的便捷函数"""
    return audio_manager.stop(track_name)

def set_audio_volume(track_name: str, volume: float) -> bool:
    """设置音频音量的便捷函数"""
    return audio_manager.set_volume(track_name, volume)