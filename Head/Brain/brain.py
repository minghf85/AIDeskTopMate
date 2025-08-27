import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt, QTimer
from Body.tlw import TransparentLive2dWindow, Live2DSignals
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from Head.Brain.agent import AIFE
from Head.ear import ASR
from Head.mouth import TTS_GSV,TTS_realtime
from Head.Brain.async_sync import (
    AsyncTextSignals, AsyncSubtitleSync, AsyncInterruptManager, 
    AsyncTerminalInput, AsyncEventLoop
)
from dotmap import DotMap
import toml
from utils.log_manager import LogManager
from PyQt6.QtGui import QKeyEvent
import time
import threading
import asyncio
from aiostream import stream

config = DotMap(toml.load("config.toml"))

class AsyncGenBroadcaster:
    def __init__(self, async_gen):
        self.async_gen = async_gen
        self.handlers = []

    def add_handler(self, handler: callable):
        """注册处理函数，需为异步函数"""
        self.handlers.append(handler)

    async def broadcast(self):
        """启动广播"""
        async for chunk in self.async_gen:
            await asyncio.gather(*[handler(chunk) for handler in self.handlers])

# 使用示例
async def save_to_db(chunk):
    print(f"DB保存: {chunk}")

async def log_to_console(chunk):
    print(f"日志输出: {chunk}")

# broadcaster = AsyncGenBroadcaster(self.agent.common_chat("你好"))
# broadcaster.add_handler(save_to_db)
# broadcaster.add_handler(log_to_console)
# await broadcaster.broadcast()  # 启动分发

class Brain(QObject):
    """统筹管理所有的功能模块，在各个线程模块之间传递信息"""
    def __init__(self):
        super().__init__()  # 调用 QObject 的初始化方法
        
        # Initialize logging
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('brain')
        
        self.text_signals = AsyncTextSignals()
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        self.text_ok_len = config.general.text_ok_len
        self.last_text = ""
        self.current_response = ""  # 当前累积的响应文本
        self.sync_subtitle = config.tts.sync_subtitle
        self.interrupt_mode = config.asr.interrupt_mode
        self.end_punctuation = config.tts.end_punctuation  # 获取结束标点符号列表
        self.interrupted = False  # 新增打断标志
        self.pending_transcription = None  # 等待处理的转录文本
        self.ear_enabled = True
        self.mouth_enabled = True
        self.input_mode = "voice"  # "voice" 或 "text"
        self.use_agent = config.agent.get("enable_agent", True)  # 控制是否使用Agent功能
        
        # 异步组件
        self.async_loop = AsyncEventLoop()
        self.subtitle_sync = None
        self.interrupt_manager = None
        self.terminal_input = None
        
        self.wakeup()
        
        self.received_first_chunk = False
        # 添加延迟计算相关的时间戳
        self.speech_detect_time = None  # 检测到说话的时间
        self.transcription_complete_time = None  # 转录完成的时间
        self.aife_response_time = None  # AIFE响应的时间
        self.audio_start_time = None  # 音频开始播放的时间

    def wakeup(self):
        """唤醒大脑，从头往下激活"""
        self.ear = ASR(url=config.asr.settings.url, lang=config.asr.settings.lang, sv=config.asr.settings.sv)
        
        # 连接ASR信号到处理方法
        self.ear.hearStart.connect(self.handle_interrupt)
        self.ear.transcriptionReady.connect(self.handle_transcription)
        self.ear.errorOccurred.connect(self.handle_asr_error)
        
        # 启动ASR线程
        try:
            self.ear.start()
            self.logger.info("ASR线程已启动")
        except Exception as e:
            self.logger.error(f"启动ASR失败: {e}")
            
        if config.tts.mode == "GSV":
            if self.sync_subtitle:
                self.mouth = TTS_GSV(
                    on_character=self.show_character,
                    on_audio_stream_start=self._on_audio_stream_start,
                    on_audio_stream_stop=self._on_audio_stream_stop,
                    on_text_stream_stop=self._on_text_stream_stop,
                    on_text_stream_start=self._on_text_stream_start)
            else:
                self.mouth = TTS_GSV(
                    on_character=self.direct_show_character,
                    on_audio_stream_start=self._on_audio_stream_start,
                    on_audio_stream_stop=self._on_audio_stream_stop,
                    on_text_stream_stop=self._on_text_stream_stop,
                    on_text_stream_start=self._on_text_stream_start
                )
            # 后面再实现
        elif config.tts.mode == "realtime":
            # 根据同步设置决定回调函数
            if self.sync_subtitle:
                self.mouth = TTS_realtime(
                    on_character=self.show_character,
                    on_audio_stream_start=self._on_audio_stream_start,
                    on_audio_stream_stop=self._on_audio_stream_stop,
                    on_text_stream_stop=self._on_text_stream_stop,
                    on_text_stream_start=self._on_text_stream_start
                )
            else:
                self.mouth = TTS_realtime(
                    on_character=self.direct_show_character,
                    on_audio_stream_start=self._on_audio_stream_start,
                    on_audio_stream_stop=self._on_audio_stream_stop,
                    on_text_stream_stop=self._on_text_stream_stop,
                    on_text_stream_start=self._on_text_stream_start
                )
        self.body = self.activate_body()
        # 安装事件过滤器以捕获键盘事件
        self.window.installEventFilter(self)
        # 连接文本更新信号
        self.text_signals.update_text.connect(self.window.msgbox.update_text)
        
        # 初始化Agent，传递信号对象
        self.agent = AIFE(
            agent_config=config.agent, 
            stream_chat_callback=self.on_stream_chat_callback,
            live2d_signals=self.signals,
            message_signals=self.window.msgbox_signals  # 传递MessageSignals对象
        )

    def activate_body(self):
        self.signals = Live2DSignals()
        self.app = QApplication(sys.argv)
        self.window = TransparentLive2dWindow(self.signals, self.mouth)
        self.window.show()
        self.window.msgbox.show()
        self.window._load_model(config.live2d.model_path)
        self.window.msgbox.show_text("大脑已唤醒，系统运行中...")
        
        # 启动异步事件循环
        self.async_loop.start_loop()
        
        # 在主线程中初始化字幕同步
        if self.sync_subtitle:
            self.subtitle_sync = AsyncSubtitleSync()
            self.subtitle_sync.show_character.connect(self._show_character_delayed)
        
        # 初始化异步打断管理器
        self.interrupt_manager = AsyncInterruptManager(self.mouth, self)
        self.interrupt_manager.interrupt_completed.connect(self._on_interrupt_completed)
        
        # 初始化异步终端输入
        self.terminal_input = AsyncTerminalInput()
        self.terminal_input.text_received.connect(self.send_text_to_ai)
        
        return self.window.model

    def _add_interrupted_response_to_memory(self):
        """统一处理被打断的响应内容，添加到AI记忆
        
        此方法统一处理所有被打断的情况，避免重复代码：
        - 模式1：听到声音立即打断
        - 模式2：说话结束后打断
        - 程序退出时的清理
        """
        if self.mouth and hasattr(self.mouth, 'stream'):
            interrupted_text = self.mouth.stream.text()
            if interrupted_text.strip():  # 只有当有实际内容时才添加
                interrupted_response = f"{interrupted_text}|Be Interrupted|"
                if self.agent and hasattr(self.agent, 'memory_manager'):
                    # 使用新的记忆管理器，标记为低重要性
                    self.agent.memory_manager.add_message(AIMessage(content=interrupted_response), importance=0.3)
                    self.logger.info(f"添加被打断的响应到记忆: {interrupted_response}")
                elif self.agent:
                    # 向后兼容
                    self.agent.short_term_memory.add_ai_message(AIMessage(content=interrupted_response))
                    self.logger.info(f"添加被打断的响应到记忆: {interrupted_response}")

    def handle_transcription(self, text: str):
        """处理ASR识别结果"""
        self.last_text = text
        if len(text) > self.text_ok_len:  # 只处理>self.text_ok_len
            try:
                # 记录转录完成的时间
                self.transcription_complete_time = time.time()
                
                # 计算并记录转录延迟
                if self.speech_detect_time:
                    transcription_delay = self.transcription_complete_time - self.speech_detect_time
                    self.logger.info(f"语音转录延迟: {transcription_delay:.3f}秒")

                if self.interrupt_mode == 2 and self.mouth.stream.is_playing():
                    # 模式2：说话结束后打断当前响应并开始新对话
                    self.pending_transcription = text
                    self._add_interrupted_response_to_memory()
                    self._start_interrupt_thread(mode=2)
                    return

                elif self.interrupt_mode == 0:
                    # 模式0：等待当前响应完成后再处理新对话
                    if hasattr(self.mouth, 'stream') and self.mouth.stream.is_playing():
                        return  # 如果当前有响应在处理，直接返回
                
                # 处理新对话（适用于模式0的空闲状态和模式1）
                self.window.msgbox.clear_content()
                self.current_response = ""
                self._start_ai_response(text)
                            
            except Exception as e:
                self.logger.error(f"处理AIFE响应时出错: {e}")
                if self.window.msgbox:
                    self.window.msgbox.show_text(f"AI处理错误: {str(e)}")

    def _on_text_stream_start(self):
        """处理文本流开始事件"""
        self.received_first_chunk_time = time.time()

    def _on_text_stream_stop(self):
        """处理文本流停止事件
        
        统一处理正常完成的响应，确保所有完整的响应都被正确保存到AI记忆中
        """
        # 正常完成的响应添加到记忆中
        if self.current_response and self.agent:
            if hasattr(self.agent, 'memory_manager'):
                # 使用新的记忆管理器，计算重要性
                importance = self._calculate_stream_response_importance(self.current_response)
                self.agent.memory_manager.add_message(AIMessage(content=self.current_response), importance)
                self.logger.info(f"添加完整响应到记忆: {self.current_response}")
            else:
                # 向后兼容
                self.agent.short_term_memory.add_ai_message(AIMessage(content=self.current_response))
                self.logger.info(f"添加完整响应到记忆: {self.current_response}")
        
        self.current_response = ""
        self.received_all_chunks_time = time.time()

    def on_stream_chat_callback(self, text: str):
        """处理流式聊天返回的文本"""
        # self.logger.info(f"流式聊天返回: {text}")
        if not self.received_first_chunk:
            self.aife_response_time = time.time()
        self.received_first_chunk = True
        # 累积响应文本
        self.current_response += text

    def direct_show_character(self, character: str):
        """直接显示角色的字符信息（包含标点符号）"""
        if self.window.msgbox:
            self.text_signals.update_text.emit(character)

    def show_character(self, character: str):
        """处理TTS返回的字符信息（包含标点符号）- 仅在同步模式下使用"""
        self.logger.debug(f"show_character被调用: '{character}', sync_subtitle={self.sync_subtitle}, subtitle_sync存在={self.subtitle_sync is not None}")
        if self.sync_subtitle and self.subtitle_sync:
            # 将字符添加到字幕同步器（异步调用）
            # 注意：这里只是添加字符到缓冲区，实际显示要等到音频开始播放
            self.async_loop.run_coroutine(self.subtitle_sync.add_character(character))
    
    def _show_character_delayed(self, character: str):
        """实际显示字符的方法 - 仅在同步模式下使用"""
        self.logger.debug(f"_show_character_delayed被调用: '{character}', msgbox存在={self.window.msgbox is not None}")
        if self.window.msgbox:
            self.text_signals.update_text.emit(character)
            self.logger.debug(f"已发送字符到UI: '{character}'")

    def _start_interrupt_thread(self, mode):
        """启动打断操作（异步）"""
        if self.interrupt_manager:
            # 使用异步打断管理器
            self.async_loop.run_coroutine(self.interrupt_manager.start_interrupt(mode))

    def _start_ai_response(self, text: str):
        """启动AI响应处理"""
        try:
            if self.agent:
                # 重置当前响应文本和相关标志
                self.current_response = ""
                self.received_first_chunk = False
                
                # 记录发送给AIFE的时间
                send_to_aife_time = time.time()
                
                # 清理字幕同步器状态，但不启动播放（等待音频开始播放时再启动）
                if self.sync_subtitle and self.subtitle_sync:
                    # 强制清理状态，不显示剩余字符，避免在音频播放前显示字符
                    self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback(force_clear=True))
                    self.logger.debug("字幕同步器状态已强制清理，等待音频开始播放")
                
                self.logger.info(f"开始处理: {text}")
                
                # 根据配置选择使用 Agent 或简单聊天
                if self.use_agent:
                    ai_response_async_gen = self.agent.agent_chat(text)
                else:
                    ai_response_async_gen = self.agent.common_chat(text)
                
                # 使用aiostream将AsyncGenerator转换为Generator
                ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                
                # 计算并记录AIFE响应延迟
                if self.aife_response_time:
                    aife_delay = send_to_aife_time - self.aife_response_time
                    self.logger.info(f"发送给AIFE->接收响应延迟: {aife_delay:.3f}秒")

                if self.mouth and hasattr(self.mouth, 'stream'):
                    self.mouth.stream.feed(ai_response_iterator)
                    self.mouth.stream.play_async()
                    self.logger.info("AI响应已传递给TTS流")
                else:
                    # 如果没有流式TTS，回退到传统方式
                    full_response = ""
                    for content in ai_response_iterator:
                        if content:
                            full_response += content
                            self.window.msgbox.update_text(content)
                    
                    # 非流式情况下直接添加到记忆
                    if self.agent and full_response:
                        if hasattr(self.agent, 'memory_manager'):
                            importance = self._calculate_stream_response_importance(full_response)
                            self.agent.memory_manager.add_message(AIMessage(content=full_response), importance)
                            self.logger.info(f"添加非流式响应到记忆: {full_response}")
                        else:
                            # 向后兼容
                            self.agent.short_term_memory.add_ai_message(AIMessage(content=full_response))
                            self.logger.info(f"添加非流式响应到记忆: {full_response}")
                    
                    if hasattr(self.mouth, 'stream'):
                        self.mouth.stream.feed(full_response)
                        
        except Exception as e:
            self.logger.error(f"启动AI响应时出错: {e}")
            if self.window.msgbox:
                self.window.msgbox.show_text(f"AI处理错误: {str(e)}")

    def _async_to_sync_generator(self, async_gen):
        """将AsyncGenerator转换为Generator"""
        try:
            # 获取或创建事件循环
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 如果循环正在运行，创建新线程来运行异步生成器
            if loop.is_running():
                import threading
                import queue
                
                result_queue = queue.Queue()
                exception_queue = queue.Queue()
                
                def run_async_gen():
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        
                        async def collect_results():
                            try:
                                async for item in async_gen:
                                    result_queue.put(('item', item))
                                result_queue.put(('done', None))
                            except Exception as e:
                                exception_queue.put(e)
                                result_queue.put(('error', e))
                        
                        new_loop.run_until_complete(collect_results())
                        new_loop.close()
                    except Exception as e:
                        exception_queue.put(e)
                        result_queue.put(('error', e))
                
                thread = threading.Thread(target=run_async_gen)
                thread.start()
                
                while True:
                    try:
                        msg_type, value = result_queue.get(timeout=1.0)
                        if msg_type == 'item':
                            yield value
                        elif msg_type == 'done':
                            break
                        elif msg_type == 'error':
                            if not exception_queue.empty():
                                raise exception_queue.get()
                            break
                    except queue.Empty:
                        continue
                
                thread.join()
            else:
                # 如果循环没有运行，直接运行
                async def collect_all():
                    results = []
                    async for item in async_gen:
                        results.append(item)
                    return results
                
                results = loop.run_until_complete(collect_all())
                for item in results:
                    yield item
                    
        except Exception as e:
            self.logger.error(f"转换AsyncGenerator时出错: {e}")
            yield f"生成器转换错误: {str(e)}"

    def handle_interrupt(self):
        """打断正在说话
        mode 0: 不打断
        mode 1: 听到声音立即打断
        mode 2: 等待说话人说完后打断并开始新对话
        """
        self.speech_detect_time = time.time()
        if self.interrupt_mode == 1 and self.mouth.stream.is_playing():
            # 模式1：听到声音就立即打断
            self.logger.info("检测到说话")
            self._add_interrupted_response_to_memory()
            self._start_interrupt_thread(mode=1)
        # 模式0和2在这里不做任何处理

    def _on_interrupt_completed(self):
        """打断完成后的回调"""
        self.logger.info("打断操作完成")
        
        # 重置当前响应（因为已经被打断并保存到记忆中）
        self.current_response = ""
        
        # 如果是模式2且有待处理的转录文本，立即开始新对话
        if self.interrupt_mode == 2 and self.pending_transcription:
            self.window.msgbox.clear_content()
            self.current_response = ""
            self.logger.info(f"模式2打断后开始新对话: {self.pending_transcription}")
            self._start_ai_response(self.pending_transcription)
            self.pending_transcription = None
        else:
            # 只有在非模式2或没有待处理转录文本时才停止字幕同步
            if self.sync_subtitle and self.subtitle_sync:
                self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback())

    def handle_asr_error(self, error: str):
        """处理ASR错误"""
        self.logger.error(f"ASR错误: {error}")
        if self.window.msgbox:
            self.window.msgbox.show_text(f"语音识别错误: {error}")

    def clear_accumulated_text(self):
        """清空累计文本"""
        self.accumulated_text = ""
        if self.window.msgbox:
            self.window.msgbox.show_text("文本已清空")
    
    def get_accumulated_text(self):
        """获取累计识别文本"""
        return self.accumulated_text.strip()
    
    def send_text_to_ai(self, text: str):
        """手动发送文本给AI（用于调试或手动输入）"""
        # 模拟语音输入的时间戳设置，确保字幕同步正常工作
        self.speech_detect_time = time.time()
        self.handle_transcription(text)

    def sleep(self):
        """让大脑进入休眠状态"""
        self.logger.info("大脑进入休眠状态...")
        
        # 如果当前有TTS在运行，先处理被打断的响应
        if hasattr(self.mouth, 'stream') and self.mouth.stream and self.mouth.stream.is_playing():
            self._add_interrupted_response_to_memory()
        
        # 仅在同步模式下停止字幕同步
        if self.sync_subtitle and self.subtitle_sync:
            self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback())
        
        # 停止异步组件
        if self.interrupt_manager:
            self.interrupt_manager.stop_interrupt()
        
        if self.terminal_input:
            self.async_loop.run_coroutine(self.terminal_input.stop_input_monitoring())
        # 停止TTS流
        if self.mouth and hasattr(self.mouth, 'stream'):
            self.mouth.stream.stop()
        
        # 停止ASR
        if self.ear:
            self.ear.stop()
            self.logger.info("ASR已停止")
        
        # 关闭消息窗口
        if self.window.msgbox:
            self.window.msgbox.close()
            
        # 关闭Live2D窗口
        if hasattr(self, 'window') and self.window:
            self.window.close()
            
        # 清理资源
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        self.interrupt_thread = None
        # 停止终端输入线程
        
        self.logger.info("大脑已休眠")

    def eventFilter(self, obj, event):
        # 处理键盘事件
        if event.type() == event.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                key = event.key()
                # K键切换ear
                if key == Qt.Key.Key_K:  # Qt.Key_K
                    self.toggle_ear()
                    return True
                # L键切换mouth
                elif key == Qt.Key.Key_L:  # Qt.Key_L
                    self.toggle_mouth()
                    return True
                
                # I键切换输入方式，闭麦切换为终端文本输入，开麦切换为语音输入
                elif key == Qt.Key.Key_I:  # Qt.Key_I
                    self.toggle_input()
                    return True
                
                # A键切换Agent模式
                elif key == Qt.Key.Key_A:  # Qt.Key_A
                    self.toggle_agent_mode()
                    return True
        return False

    def toggle_agent_mode(self):
        """切换Agent智能体模式"""
        self.use_agent = not self.use_agent
        mode_text = "智能体模式" if self.use_agent else "简单聊天模式"
        if self.window.msgbox:
            self.window.msgbox.show_text(f"已切换为{mode_text}")
        self.logger.info(f"切换为{mode_text}")

    def toggle_input(self, force_voice=False):
        """切换输入方式，闭麦切换为终端文本输入，开麦切换为语音输入"""
        if force_voice or self.input_mode == "text":
            # 切换为语音输入
            self.input_mode = "voice"
            if self.terminal_input:
                self.async_loop.run_coroutine(self.terminal_input.stop_input_monitoring())

            if not self.ear_enabled:
                self.toggle_ear()  # 开麦
            if self.window.msgbox:
                self.window.msgbox.show_text("已切换为语音输入（开麦）")
            self.logger.info("切换为语音输入")
        else:
            # 切换为文本输入
            self.input_mode = "text"
            if self.ear_enabled:
                self.toggle_ear()  # 闭麦
            if self.window.msgbox:
                self.window.msgbox.show_text("已切换为终端文本输入（闭麦）")
            self.logger.info("切换为终端文本输入")
            # 启动异步终端输入监听
            if self.terminal_input:
                self.async_loop.run_coroutine(self.terminal_input.start_input_monitoring())

    def toggle_ear(self):
        """切换ear开启/关闭"""
        if self.ear_enabled:
            if self.ear:
                try:
                    self.ear.stop_stream()
                    self.logger.info("闭麦")
                    if self.window.msgbox:
                        self.window.msgbox.show_text("已闭麦")
                except Exception as e:
                    self.logger.error(f"闭麦失败: {e}")
            self.ear_enabled = False
        else:
            if self.ear:
                try:
                    self.ear.resume_stream()
                    self.logger.info("开麦")
                    if self.window.msgbox:
                        self.window.msgbox.show_text("已开麦")
                except Exception as e:
                    self.logger.error(f"开麦失败: {e}")
            self.ear_enabled = True

    def toggle_mouth(self):
        """切换mouth开启/关闭"""
        if self.mouth_enabled:
            if self.mouth and hasattr(self.mouth, 'stream'):
                self.mouth.stream.stop()
                self.logger.info("TTS已关闭")
                if self.window.msgbox:
                    self.window.msgbox.show_text("语音合成已关闭")
            self.mouth_enabled = False
        else:
            # mouth开启时无需重新初始化mouth，只需提示
            self.logger.info("TTS已开启")
            if self.window.msgbox:
                self.window.msgbox.show_text("语音合成已开启")
            self.mouth_enabled = True

    def _on_audio_stream_start(self):
        """处理音频流开始播放的回调"""
        self.audio_start_time = time.time()
        
        # 计算从AIFE响应到开始播放的延迟
        if self.aife_response_time:
            tts_delay = self.audio_start_time - self.aife_response_time
            self.logger.info(f"TTS开始播放延迟: {tts_delay:.3f}秒")
        
        # 计算从转录完成到开始播放的总延迟
        if self.transcription_complete_time:
            total_delay = self.audio_start_time - self.transcription_complete_time
            self.logger.info(f"总响应延迟(从转录完成到开始播放): {total_delay:.3f}秒")
        
        # 启动字幕同步（如果启用）
        if self.sync_subtitle and self.subtitle_sync:
            self.async_loop.run_coroutine(self.subtitle_sync.start_audio_playback())
            self.logger.debug("字幕同步已启动")

        # 重置时间戳，为下一轮做准备
        self.speech_detect_time = None
        self.transcription_complete_time = None
        self.aife_response_time = None
        self.audio_start_time = None

    def _on_audio_stream_stop(self):
        """处理音频流停止播放的回调"""
        # 停止字幕同步（如果启用）
        if self.sync_subtitle and self.subtitle_sync:
            self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback())
            self.logger.debug("字幕同步已停止")
    
    def _calculate_stream_response_importance(self, response: str) -> float:
        """计算流式响应的重要性分数
        
        Args:
            response: AI响应内容
            
        Returns:
            重要性分数 (0.0-1.0)
        """
        if not response or not response.strip():
            return 0.1
        
        importance = 0.5  # 基础重要性
        
        # 被打断的响应重要性较低
        if "|Be Interrupted|" in response:
            importance = 0.3
        else:
            # 根据响应长度调整重要性
            if len(response) > 100:
                importance += 0.2
            elif len(response) < 20:
                importance -= 0.1
            
            # 包含问号的响应可能更重要（互动性强）
            if "?" in response or "？" in response:
                importance += 0.1
            
            # 包含特定关键词的响应更重要
            important_keywords = ["重要", "注意", "警告", "错误", "成功", "完成"]
            if any(keyword in response for keyword in important_keywords):
                importance += 0.2
        
        return min(max(importance, 0.1), 1.0)  # 限制在0.1-1.0范围内

if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())