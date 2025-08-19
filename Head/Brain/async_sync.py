import asyncio
import threading
import time
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QMetaObject, Qt
from loguru import logger
import sys


class AsyncTextSignals(QObject):
    """用于发送文本更新信号的类"""
    update_text = pyqtSignal(str)


class AsyncSubtitleSync(QObject):
    """异步字幕同步显示类"""
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
        self.lock = asyncio.Lock()
        self.character_index = 0  # 字符索引
        self.processed_chars = set()  # 已处理的字符索引，避免重复
        self._running = False
    
    async def restart_audio_playback(self):
        """重启音频播放（先停止再启动，确保状态清理）"""
        logger.debug("重启字幕同步器")
        await self.stop_audio_playback()
        # 稍微等待确保停止操作完成
        await asyncio.sleep(0.01)
        await self.start_audio_playback()
        logger.debug("字幕同步器重启完成")
    
    async def start_audio_playback(self):
        """标记音频开始播放"""
        async with self.lock:
            self.audio_start_time = time.time() * 1000  # 转换为毫秒
            self.character_buffer.clear()
            self.word_timings.clear()
            self.current_text = ""
            self.character_index = 0
            self.processed_chars.clear()
            self._running = True
            
            if not self.subtitle_timer.isActive():
                # 使用 QMetaObject.invokeMethod 确保在正确的线程中启动定时器
                QMetaObject.invokeMethod(self.subtitle_timer, "start", Qt.ConnectionType.QueuedConnection)
            logger.debug("音频播放开始，字幕同步启动")
    
    async def stop_audio_playback(self):
        """停止音频播放"""
        async with self.lock:
            self._running = False
            # 使用 QMetaObject.invokeMethod 确保在正确的线程中停止定时器
            QMetaObject.invokeMethod(self.subtitle_timer, "stop", Qt.ConnectionType.QueuedConnection)
            self.character_buffer.clear()
            self.word_timings.clear()
            self.current_text = ""
            self.character_index = 0
            self.processed_chars.clear()
            self.audio_start_time = None
            logger.debug("音频播放停止，字幕同步停止")
    
    async def add_character(self, character):
        """添加字符（来自on_character回调）"""
        if not self._running:
            return
            
        async with self.lock:
            self.current_text += character
    
    async def add_word_timing(self, timing_info):
        """添加单词时间信息（来自on_word回调）"""
        if self.audio_start_time is None or not self._running:
            return
            
        async with self.lock:
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
            
            i += 1
    
    def _process_subtitle_buffer(self):
        """处理字幕缓冲区"""
        if self.audio_start_time is None or not self._running:
            return
            
        current_time = time.time() * 1000
        
        # 处理所有应该显示的字符
        while self.character_buffer:
            char_info = self.character_buffer[0]
            if current_time >= char_info['target_time']:
                char_info = self.character_buffer.popleft()
                self.show_character.emit(char_info['character'])
            else:
                break


class AsyncInterruptManager(QObject):
    """异步打断管理器"""
    interrupt_completed = pyqtSignal()
    
    def __init__(self, mouth, mode_manager):
        super().__init__()
        self.mouth = mouth
        self.mode_manager = mode_manager
        self._interrupt_task = None
        self._running = False
    
    async def start_interrupt(self, mode):
        """启动打断操作"""
        if self._interrupt_task and not self._interrupt_task.done():
            # 如果已有打断任务在运行，先取消它
            self._interrupt_task.cancel()
            try:
                await self._interrupt_task
            except asyncio.CancelledError:
                pass
        
        self._running = True
        self._interrupt_task = asyncio.create_task(self._perform_interrupt(mode))
        await self._interrupt_task
    
    async def _perform_interrupt(self, mode):
        """执行打断操作"""
        try:
            logger.info(f"开始执行模式{mode}打断")
            
            # 无论哪种模式，都是停止TTS流
            if self.mouth and hasattr(self.mouth, 'stream') and self.mouth.stream.is_playing():
                # 在线程池中执行阻塞操作
                await asyncio.get_event_loop().run_in_executor(None, self.mouth.stream.stop)
                logger.info(f"模式{mode}打断: TTS流已停止")
            
            # 等待一小段时间确保停止完成
            await asyncio.sleep(0.1)
            
            # 发送完成信号（使用QMetaObject确保线程安全）
            QMetaObject.invokeMethod(self, "interrupt_completed", Qt.ConnectionType.QueuedConnection)
            
        except asyncio.CancelledError:
            logger.info("打断操作被取消")
            raise
        except Exception as e:
            logger.error(f"打断处理出错: {e}")
            # 即使出错也要发送完成信号，避免挂起
            QMetaObject.invokeMethod(self, "interrupt_completed", Qt.ConnectionType.QueuedConnection)
        finally:
            self._running = False
    
    def stop_interrupt(self):
        """停止打断操作"""
        if self._interrupt_task and not self._interrupt_task.done():
            self._interrupt_task.cancel()
        self._running = False


class AsyncTerminalInput(QObject):
    """异步终端输入管理器"""
    text_received = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._input_task = None
        self._running = False
        self._executor = None
    
    async def start_input_monitoring(self):
        """开始监听终端输入"""
        if self._running:
            return
            
        self._running = True
        logger.info("开始终端输入监听")
        
        # 使用线程池执行器来处理阻塞的input操作
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        self._input_task = asyncio.create_task(self._monitor_input())
    
    async def _monitor_input(self):
        """监听输入的主循环"""
        try:
            while self._running:
                try:
                    # 在线程池中执行阻塞的input操作
                    text = await asyncio.get_event_loop().run_in_executor(
                        self._executor, 
                        self._get_input_with_prompt
                    )
                    
                    if text and self._running:
                        # 使用QMetaObject确保信号在正确的线程中发送
                        # 直接emit信号，PyQt6会自动处理线程安全
                        self.text_received.emit(text)
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"终端输入监听出错: {e}")
                    await asyncio.sleep(0.1)  # 避免快速重试
                    
        except asyncio.CancelledError:
            logger.info("终端输入监听被取消")
        finally:
            logger.info("终端输入监听结束")
    
    def _get_input_with_prompt(self):
        """获取用户输入（在线程池中执行）"""
        try:
            return input("请输入文本（按I键切换回语音输入）：").strip()
        except EOFError:
            return None
        except KeyboardInterrupt:
            return None
    
    async def stop_input_monitoring(self):
        """停止监听终端输入"""
        if not self._running:
            return
            
        self._running = False
        logger.info("停止终端输入监听")
        
        if self._input_task and not self._input_task.done():
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass
        
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None


class AsyncEventLoop(QObject):
    """异步事件循环管理器"""
    
    def __init__(self):
        super().__init__()
        self.loop = None
        self.loop_thread = None
        self._running = False
    
    def start_loop(self):
        """在单独线程中启动事件循环"""
        if self._running:
            return
            
        self._running = True
        self.loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.loop_thread.start()
        
        # 等待循环启动
        while self.loop is None:
            time.sleep(0.01)
    
    def _run_loop(self):
        """运行事件循环的线程函数"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.info("异步事件循环已启动")
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"异步事件循环出错: {e}")
        finally:
            logger.info("异步事件循环已结束")
    
    def stop_loop(self):
        """停止事件循环"""
        if not self._running:
            return
            
        self._running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        
        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=2.0)
    
    def run_coroutine(self, coro):
        """在事件循环中运行协程"""
        if not self.loop or not self._running:
            logger.warning("事件循环未运行，无法执行协程")
            return None
            
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future
    
    def run_coroutine_sync(self, coro, timeout=None):
        """同步方式运行协程（等待结果）"""
        future = self.run_coroutine(coro)
        if future:
            try:
                return future.result(timeout=timeout)
            except Exception as e:
                logger.error(f"协程执行失败: {e}")
                return None
        return None
