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
        self.character_buffer = deque()  # 字符缓冲队列（保留兼容性）
        self.current_text = ""  # 当前累积的文本
        self.audio_start_time = None  # 音频开始播放时间
        self.subtitle_timer = QTimer()
        self.subtitle_timer.timeout.connect(self._process_subtitle_buffer)
        self.subtitle_timer.setSingleShot(False)
        self.subtitle_timer.setInterval(50)  # 英文50ms显示一个字符，匀速显示，中文100ms一个字符
        self.lock = asyncio.Lock()
        self.display_index = 0  # 当前应该显示的字符索引
        self._running = False
    
    async def restart_audio_playback(self):
        """重启音频播放（先停止再启动，确保状态清理）"""
        logger.debug("重启字幕同步器")
        # 保存当前文本，避免在重启时丢失
        saved_text = self.current_text
        await self.stop_audio_playback()
        # 恢复文本内容
        self.current_text = saved_text
        # 稍微等待确保停止操作完成
        await asyncio.sleep(0.01)
        await self.start_audio_playback()
        logger.debug(f"字幕同步器重启完成，恢复文本长度: {len(self.current_text)}")
    
    async def start_audio_playback(self):
        """标记音频开始播放"""
        async with self.lock:
            self.audio_start_time = time.time() * 1000  # 转换为毫秒
            self.character_buffer.clear()
            # 不清空current_text，因为字符已经通过add_character添加了
            self.display_index = 0
            self._running = True
            
            logger.debug(f"准备启动定时器: isActive={self.subtitle_timer.isActive()}, interval={self.subtitle_timer.interval()}, text_length={len(self.current_text)}")
            if not self.subtitle_timer.isActive():
                # 使用QMetaObject.invokeMethod确保在主线程中启动定时器
                QMetaObject.invokeMethod(self.subtitle_timer, "start", Qt.ConnectionType.QueuedConnection)
                logger.debug("已请求在主线程中启动定时器")
                # 立即触发一次显示，避免等待第一个定时器间隔
                QMetaObject.invokeMethod(self, "_process_subtitle_buffer", Qt.ConnectionType.QueuedConnection)
            logger.debug("音频播放开始，字幕同步启动")
    
    async def stop_audio_playback(self):
        """停止音频播放"""
        async with self.lock:
            # 先显示所有剩余字符
            remaining_chars = len(self.current_text) - self.display_index
            if remaining_chars > 0:
                logger.debug(f"音频停止前显示剩余 {remaining_chars} 个字符")
                for i in range(self.display_index, len(self.current_text)):
                    char = self.current_text[i]
                    self.show_character.emit(char)
                    logger.debug(f"显示剩余字符: '{char}' (索引: {i})")
            
            self._running = False
            # 使用QMetaObject.invokeMethod确保在主线程中停止定时器
            if self.subtitle_timer.isActive():
                QMetaObject.invokeMethod(self.subtitle_timer, "stop", Qt.ConnectionType.QueuedConnection)
                logger.debug("已请求在主线程中停止定时器")
            self.character_buffer.clear()
            self.current_text = ""
            self.display_index = 0
            self.audio_start_time = None
            logger.debug("音频播放停止，字幕同步停止，已清理所有状态")
    
    async def add_character(self, character):
        """添加字符（来自on_character回调）"""
        async with self.lock:
            self.current_text += character
            logger.debug(f"添加字符: '{character}', 当前文本长度: {len(self.current_text)}, _running={self._running}")
    
    async def add_word_timing(self, timing_info):
        """添加单词时间信息（来自on_word回调）- 已弃用，保留接口兼容性"""
        # 不再使用on_word回调，保留此方法仅为兼容性
        pass
    

    
    def _process_subtitle_buffer(self):
        """处理字幕缓冲区 - 匀速显示字符"""
        # logger.debug(f"定时器触发: audio_start_time={self.audio_start_time}, _running={self._running}, display_index={self.display_index}, text_length={len(self.current_text)}")
        
        if self.audio_start_time is None or not self._running:
            logger.debug("定时器触发但条件不满足，返回")
            return
            
        # 检查是否有字符需要显示
        if self.display_index < len(self.current_text):
            char = self.current_text[self.display_index]
            logger.debug(f"准备显示字符: '{char}' (索引: {self.display_index})")
            self.show_character.emit(char)
            self.display_index += 1
            logger.debug(f"已发送字符显示信号: '{char}' (索引: {self.display_index-1})")
        # else:
            # 没有更多字符需要显示，但保持定时器运行以处理新添加的字符
            # logger.debug(f"当前没有新字符需要显示，等待更多字符 (display_index={self.display_index}, text_length={len(self.current_text)})")
            # 不停止定时器，因为可能还会有新字符添加


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
