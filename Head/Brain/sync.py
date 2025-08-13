
import threading
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal, QObject,QTimer
import time
from loguru import logger
class TextSignals(QObject):
    """用于发送文本更新信号的类"""
    update_text = pyqtSignal(str)

class SubtitleSync(QObject):
    """字幕同步显示类"""
    show_character = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.character_buffer = deque()  # 字符缓冲队列
        self.word_timings = {}  # 存储单词时间信息
        self.current_text = ""  # 当前累积的文本
        self.audio_start_time = None  # 音频开始播放时间
        self.subtitle_timer = QTimer()
        self.subtitle_timer.timeout.connect(self._process_subtitle_buffer)
        self.subtitle_timer.setSingleShot(False)
        self.subtitle_timer.setInterval(10)  # 10ms检查一次，提高精度
        self.lock = threading.Lock()
        self.character_index = 0  # 字符索引
        self.processed_chars = set()  # 已处理的字符索引，避免重复
    
    def start_audio_playback(self):
        """标记音频开始播放"""
        with self.lock:
            self.audio_start_time = time.time() * 1000  # 转换为毫秒
            self.character_buffer.clear()
            self.word_timings.clear()
            self.current_text = ""
            self.character_index = 0
            self.processed_chars.clear()
            if not self.subtitle_timer.isActive():
                self.subtitle_timer.start()
            logger.debug("音频播放开始，字幕同步启动")
    
    def stop_audio_playback(self):
        """停止音频播放"""
        with self.lock:
            self.subtitle_timer.stop()
            self.character_buffer.clear()
            self.word_timings.clear()
            self.current_text = ""
            self.character_index = 0
            self.processed_chars.clear()
            self.audio_start_time = None
            logger.debug("音频播放停止，字幕同步停止")
    
    def add_character(self, character):
        """添加字符（来自on_character回调）"""
        with self.lock:
            self.current_text += character
            # logger.debug(f"添加字符: '{character}', 当前文本长度: {len(self.current_text)}")
    
    def add_word_timing(self, timing_info):
        """添加单词时间信息（来自on_word回调）"""
        if self.audio_start_time is None:
            return
            
        with self.lock:
            if hasattr(timing_info, 'word') and hasattr(timing_info, 'start_time'):
                word = timing_info.word.strip()
                start_time_ms = timing_info.start_time * 1000  # 转换为毫秒
                
                # 清理单词（移除特殊字符，但保留标点符号）
                cleaned_word = word.strip('*').strip()
                if not cleaned_word:
                    return
                
                # 在当前文本中查找这个单词
                word_start_index = self._find_word_in_text(cleaned_word)
                if word_start_index >= 0:
                    # 为单词的每个字符分配时间
                    for i, char in enumerate(cleaned_word):
                        char_index = word_start_index + i
                        if char_index < len(self.current_text) and char_index not in self.processed_chars:
                            target_time = self.audio_start_time + start_time_ms
                            
                            self.character_buffer.append({
                                'character': self.current_text[char_index],
                                'target_time': target_time,
                                'char_index': char_index
                            })
                            self.processed_chars.add(char_index)
                    
                    # 处理单词后的标点符号和空格
                    self._process_post_word_characters(word_start_index + len(cleaned_word), start_time_ms)
                    
                    # logger.debug(f"添加单词时间: '{cleaned_word}' at {start_time_ms:.0f}ms, 索引: {word_start_index}")
    
    def _find_word_in_text(self, word):
        """在当前文本中查找单词位置"""
        # 从当前字符索引开始查找
        search_text = self.current_text[self.character_index:]
        
        if not word:
            return -1
        
        # 查找单词位置
        word_index = search_text.find(word)
        if word_index >= 0:
            absolute_index = self.character_index + word_index
            # 更新字符索引到单词结束位置
            self.character_index = absolute_index + len(word)
            return absolute_index
        
        return -1
    
    def _process_post_word_characters(self, start_index, word_start_time_ms):
        """处理单词后的字符（标点符号、空格等）"""
        # 为单词后的标点符号和空格分配相同的时间
        i = start_index
        while i < len(self.current_text):
            char = self.current_text[i]
            # 如果遇到字母或数字，说明是下一个单词了，停止处理
            if char.isalnum():
                break
            
            # 避免重复处理
            if i not in self.processed_chars:
                target_time = self.audio_start_time + word_start_time_ms
                self.character_buffer.append({
                    'character': char,
                    'target_time': target_time,
                    'char_index': i
                })
                self.processed_chars.add(i)
                # logger.debug(f"处理后续字符: '{char}' at index {i}")
            
            i += 1
    
    def _process_subtitle_buffer(self):
        """处理字幕缓冲区"""
        if self.audio_start_time is None:
            return
            
        current_time = time.time() * 1000
        
        with self.lock:
            # 处理所有应该显示的字符
            while self.character_buffer:
                char_info = self.character_buffer[0]
                if current_time >= char_info['target_time']:
                    char_info = self.character_buffer.popleft()
                    self.show_character.emit(char_info['character'])
                    # logger.debug(f"显示字符: '{char_info['character']}' (索引: {char_info['char_index']})")
                else:
                    break

class Interrupt(QThread):
    """处理打断逻辑的独立线程"""
    interrupt_completed = pyqtSignal()
    
    def __init__(self, mouth, mode):
        super().__init__()
        self.mouth = mouth
        self.mode = mode
        self.should_stop = False
    
    def run(self):
        """在独立线程中执行打断操作"""
        try:
            if self.mode == 1:
                # 模式1：听到声音就立即打断
                if self.mouth and hasattr(self.mouth, 'stream'):
                    self.mouth.stream.stop()
                    logger.info("打断TTS stream完成")
            elif self.mode == 2:
                # 模式2：打断当前响应
                if self.mouth and hasattr(self.mouth, 'stream'):
                    self.mouth.stream.stop()
                    logger.info("打断TTS stream完成")
            
            self.interrupt_completed.emit()
            
        except Exception as e:
            logger.error(f"打断处理出错: {e}")
    
    def stop_thread(self):
        """停止线程"""
        self.should_stop = True
        self.quit()
        self.wait()