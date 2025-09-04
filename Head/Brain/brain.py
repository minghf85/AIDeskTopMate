import sys
import signal
from typing import Dict, Any, Optional
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt, QTimer
from Body.tlw import TransparentLive2dWindow, Live2DSignals
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from Head.Brain.agent import AIFE
from Head.ear import ASR
from Head.Brain.feel import FeelState, InterruptMode, InteractionMode, AgentMode
from Head.mouth import TTS_GSV,TTS_realtime
from Head.Brain.async_sync import (
    AsyncTextSignals, AsyncSubtitleSync, AsyncInterruptManager, 
    AsyncTerminalInput, AsyncEventLoop
)
from dotmap import DotMap
import toml
from utils.log_manager import LogManager
from utils.monitor import BrainMonitor
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

    def add_handler(self, handler):
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
        
        # 初始化状态管理器
        self.feel_state = FeelState()
        self.feel_state.update_environment_state(
            config_loaded=True,
            log_level="INFO"
        )
        
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
        
        # 初始化监控器
        self.monitor = None
        
        # 更新feel_state的初始配置
        self.feel_state.update_component_status("brain", 
            interrupt_mode=InterruptMode(self.interrupt_mode),
            interaction_mode=InteractionMode.VOICE if self.input_mode == "voice" else InteractionMode.TEXT,
            sync_subtitle=self.sync_subtitle
        )
        
        # 异步组件
        self.async_loop = AsyncEventLoop()
        self.subtitle_sync = None
        self.interrupt_manager = None
        self.terminal_input = None
        
        # 状态驱动定时器
        self.state_check_timer = QTimer()
        self.state_check_timer.timeout.connect(self._process_state_driven_interaction)
        self.state_check_interval = config.general.get("state_check_interval", 1000)  # 默认1秒检查一次
        
        self.wakeup()
        
        # 注册程序退出时的清理函数
        import atexit
        atexit.register(self.cleanup)
        
        self.received_first_chunk = False
        # 添加延迟计算相关的时间戳
        self.speech_detect_time = None  # 检测到说话的时间
        self.transcription_complete_time = None  # 转录完成的时间
        self.aife_response_time = None  # AIFE响应的时间
        self.audio_start_time = None  # 音频开始播放的时间

    def cleanup(self):
        """程序退出时的清理工作"""
        try:
            # 清理监控器
            if self.monitor:
                self.logger.info("正在清理监控器...")
                self.monitor.cleanup()
                self.monitor = None
                self.logger.info("监控器清理完成")
            
            if self.agent and hasattr(self.agent, 'memory_manager'):
                self.logger.info("正在保存记忆...")
                self.agent.memory_manager.save_all_memories()
                self.logger.info("记忆保存完成")
        except Exception as e:
            self.logger.error(f"清理过程中发生错误: {e}")

    def wakeup(self):
        """唤醒大脑，从头往下激活"""
        # 更新大脑状态
        self.feel_state.update_component_status("brain", brain_awake=True)
        
        # 初始化ASR（ear）
        try:
            self.ear = ASR(url=config.asr.settings.url, lang=config.asr.settings.lang, sv=config.asr.settings.sv)
            
            # 连接ASR信号到处理方法
            self.ear.hearStart.connect(self.handle_interrupt)
            self.ear.transcriptionReady.connect(self.handle_transcription)
            self.ear.errorOccurred.connect(self.handle_asr_error)
            
            # 启动ASR线程
            self.ear.start()
            self.logger.info("ASR线程已启动")
            
            # 更新ear状态
            self.feel_state.update_component_status("ear", 
                ear_running=True, 
                ear_connected=True,
                ear_enabled=self.ear_enabled
            )
            self.feel_state.update_environment_state(asr_server_connected=True)
        except Exception as e:
            self.logger.error(f"初始化ASR失败: {e}")
            self.feel_state.update_component_status("ear", ear_running=False, ear_connected=False)
            self.feel_state.update_environment_state(asr_server_connected=False)
            self.feel_state.environment_state.add_error(f"ASR初始化失败: {e}")
            self.handle_component_error("ear", str(e))
            
        # 初始化TTS（mouth）
        try:
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
            self.logger.info(f"TTS引擎已初始化: {config.tts.mode}")
            
            # 更新mouth状态
            self.feel_state.update_component_status("mouth", mouth_enabled=self.mouth_enabled)
            self.feel_state.update_environment_state(tts_server_connected=True)
        except Exception as e:
            self.logger.error(f"初始化TTS失败: {e}")
            self.feel_state.update_component_status("mouth", mouth_enabled=False)
            self.feel_state.update_environment_state(tts_server_connected=False)
            self.feel_state.environment_state.add_error(f"TTS初始化失败: {e}")
            self.handle_component_error("mouth", str(e))
            
        # 初始化Body（Live2D）
        try:
            self.body = self.activate_body()
            self.logger.info("Live2D界面已初始化")
            
            # 更新body状态
            self.feel_state.update_component_status("body", body_initialized=True)
            self.feel_state.update_environment_state(model_loaded=True)
        except Exception as e:
            self.logger.error(f"初始化Live2D失败: {e}")
            self.feel_state.update_component_status("body", body_initialized=False)
            self.feel_state.update_environment_state(model_loaded=False)
            self.feel_state.environment_state.add_error(f"Live2D初始化失败: {e}")
            self.handle_component_error("body", str(e))
            return  # 如果body初始化失败，无法继续
            
        # 安装事件过滤器以捕获键盘事件
        self.window.installEventFilter(self)
        # 连接文本更新信号
        self.text_signals.update_text.connect(self.window.msgbox.update_text)
        
        # 初始化Agent（智能体）
        try:
            self.agent = AIFE(
                agent_config=config.agent, 
                stream_chat_callback=self.on_stream_chat_callback,
                live2d_signals=self.signals,
                message_signals=self.window.msgbox_signals  # 传递MessageSignals对象
            )
            self.logger.info("Agent智能体已初始化")
            
            # 更新agent状态
            self.feel_state.update_component_status("agent", 
                agent_initialized=True,
                agent_mode=self.feel_state.component_status.agent_mode
            )
            self.feel_state.update_environment_state(llm_connected=True)
        except Exception as e:
            self.logger.error(f"初始化Agent失败: {e}")
            self.feel_state.update_component_status("agent", agent_initialized=False)
            self.feel_state.update_environment_state(llm_connected=False)
            self.feel_state.environment_state.add_error(f"Agent初始化失败: {e}")
            self.handle_component_error("agent", str(e))

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
        
        # 初始化监控器
        self.monitor = BrainMonitor(self.feel_state)
        self.logger.info("Brain监控器已初始化")
        
        # 启动状态检查定时器
        self.state_check_timer.start(self.state_check_interval)
        self.logger.info(f"状态检查定时器已启动，检查间隔: {self.state_check_interval}ms")
        
        # 设置初始响应时间，让系统能够正常进入空闲状态
        self.feel_state.interaction_state.update_response_time()
        self.logger.info("已设置初始响应时间")
        
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
                    # 使用新的记忆管理器添加到短期记忆
                    self.agent.memory_manager.short_term_memory.add_message(AIMessage(content=interrupted_response))
                    self.agent.memory_manager.save_ChatHistory()
                    self.logger.info(f"添加被打断的响应到记忆: {interrupted_response}")
                elif self.agent:
                    # 向后兼容
                    self.agent.short_term_memory.add_ai_message(AIMessage(content=interrupted_response))
                    self.logger.info(f"添加被打断的响应到记忆: {interrupted_response}")
                
                # 更新last_response到feel_state（被打断的响应）
                self.feel_state.last_response = interrupted_response
                self.logger.debug(f"更新last_response（被打断）: {interrupted_response}")

    def handle_transcription(self, text: str):
        """基于状态智能处理ASR识别结果"""
        self.last_text = text
        
        # 重置听音状态 - 转录完成意味着不再听到声音
        self.feel_state.update_component_status("ear", is_hearing=False)
        
        # 更新状态
        self.feel_state.update_interaction_state(last_text=text)
        self.feel_state.update_performance_metrics(transcription_complete_time=time.time())
        
        if len(text) > self.text_ok_len:  # 只处理>self.text_ok_len
            try:
                # 记录转录完成的时间
                self.transcription_complete_time = time.time()
                
                # 计算并记录转录延迟
                if self.speech_detect_time:
                    transcription_delay = self.transcription_complete_time - self.speech_detect_time
                    self.logger.info(f"语音转录延迟: {transcription_delay:.3f}秒")

                # 基于状态和模式智能处理转录结果
                if not self._should_process_transcription(text):
                    return
                    
                # 根据打断模式和当前状态处理
                if self.interrupt_mode == 2 and self.feel_state.is_in_conversation():
                    # 模式2：等待当前响应结束后开始新对话
                    self.logger.info(f"模式2: 等待当前响应结束，暂存转录文本: {text}")
                    self.pending_transcription = text
                    self.feel_state.update_interaction_state(pending_transcription=text)
                    # 如果当前正在播放，添加被打断的响应到记忆并启动打断
                    if (self.mouth and hasattr(self.mouth, 'stream') and 
                        self.mouth.stream.is_playing()):
                        self._add_interrupted_response_to_memory()
                        self._start_interrupt_thread(mode=2)
                    return

                elif self.interrupt_mode == 0 and self.feel_state.is_in_conversation():
                    # 模式0：等待当前响应完成后再处理新对话
                    self.logger.info("模式0: 当前正在对话中，忽略新的转录文本")
                    return
                
                # 设置用户输入到状态中，由定时器触发状态驱动处理
                self.feel_state.current_user_input = text
                # 更新交互时间，标记用户有新输入
                self.feel_state.update_interaction_time()
                            
            except Exception as e:
                self.logger.error(f"处理AIFE响应时出错: {e}")
                self.feel_state.environment_state.add_error(f"处理AIFE响应时出错: {e}")
                if self.window.msgbox:
                    self.window.msgbox.show_text(f"AI处理错误: {str(e)}")

    def _on_text_stream_start(self):
        """处理文本流开始事件"""
        self.received_first_chunk_time = time.time()
        self.feel_state.update_performance_metrics(received_first_chunk_time=self.received_first_chunk_time)

    def _on_text_stream_stop(self):
        """处理文本流停止事件
        
        统一处理正常完成的响应，确保所有完整的响应都被正确保存到AI记忆中
        """
        # 正常完成的响应添加到记忆中
        if self.current_response and self.agent:
            if hasattr(self.agent, 'memory_manager'):
                # 使用新的记忆管理器添加到短期记忆
                self.agent.memory_manager.short_term_memory.add_message(AIMessage(content=self.current_response))
                self.agent.memory_manager.save_ChatHistory()
                self.logger.info(f"添加完整响应到记忆: {self.current_response}")
            else:
                # 向后兼容
                self.agent.short_term_memory.add_ai_message(AIMessage(content=self.current_response))
                self.logger.info(f"添加完整响应到记忆: {self.current_response}")
            
            # 更新last_response到feel_state
            self.feel_state.last_response = self.current_response
            self.logger.debug(f"更新last_response: {self.current_response}")
        
        self.current_response = ""
        self.received_all_chunks_time = time.time()
        
        # 更新状态
        self.feel_state.update_interaction_state(current_response="")
        self.feel_state.update_performance_metrics(received_all_chunks_time=self.received_all_chunks_time)
        self.feel_state.update_component_status("mouth", is_speaking=False)
        
        # AI响应完成，更新响应时间用于空闲状态判断
        self.feel_state.interaction_state.update_response_time()
        
        # 如果是自主行为完成，重置自主行为状态
        if self.feel_state.interaction_state.is_autonomous:
            self.feel_state.mark_autonomous_completed()
            self.logger.debug("自主行为完成，重置is_autonomous状态")
        
        # 检查是否有待处理的转录文本需要处理
        self._check_pending_transcription()

    def on_stream_chat_callback(self, text: str):
        """处理流式聊天返回的文本"""
        # self.logger.info(f"流式聊天返回: {text}")
        if not self.received_first_chunk:
            self.aife_response_time = time.time()
            self.feel_state.update_performance_metrics(aife_response_time=self.aife_response_time)
        self.received_first_chunk = True
        
        # 累积响应文本
        self.current_response += text
        self.feel_state.update_interaction_state(
            current_response=self.current_response,
            received_first_chunk=True
        )

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
            if not self.agent:
                self.handle_component_error("agent", "Agent未初始化")
                return
                
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
            
            try:
                # 添加用户消息到记忆中
                if self.agent and hasattr(self.agent, 'memory_manager'):
                    self.agent.memory_manager.short_term_memory.add_message(HumanMessage(content=text))
                elif self.agent:
                    self.agent.short_term_memory.add_message(HumanMessage(content=text))
                
                # 根据use_agent配置选择使用 Agent 或简单聊天
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

                if self.mouth and hasattr(self.mouth, 'stream') and self.mouth.stream is not None:
                    try:
                        self.mouth.stream.feed(ai_response_iterator)
                        self.mouth.stream.play_async()
                        self.logger.info("AI响应已传递给TTS流")
                    except Exception as e:
                        self.logger.error(f"TTS播放失败: {e}")
                        self.handle_component_error("mouth", f"TTS播放错误: {str(e)}")
                        # 回退到文本显示
                        self._fallback_text_display(ai_response_iterator)
                else:
                    # 如果没有流式TTS，回退到传统方式
                    self._fallback_text_display(ai_response_iterator)
                    
            except Exception as e:
                self.logger.error(f"Agent处理失败: {e}")
                self.handle_component_error("agent", f"AI处理错误: {str(e)}")
                        
        except Exception as e:
            self.logger.error(f"启动AI响应时出错: {e}")
            self.handle_component_error("brain", f"AI响应启动错误: {str(e)}")

    def _fallback_text_display(self, response_iterator):
        """回退到文本显示模式"""
        try:
            full_response = ""
            for content in response_iterator:
                if content:
                    full_response += content
                    if self.window and hasattr(self.window, 'msgbox') and self.window.msgbox:
                        self.window.msgbox.update_text(content)
            
            # 非流式情况下直接添加到记忆
            if self.agent and full_response:
                if hasattr(self.agent, 'memory_manager'):
                    # 使用新的记忆管理器添加到短期记忆
                    self.agent.memory_manager.short_term_memory.add_message(AIMessage(content=full_response))
                    self.logger.info(f"添加非流式响应到记忆: {full_response}")
                else:
                    # 向后兼容
                    self.agent.short_term_memory.add_ai_message(AIMessage(content=full_response))
                    self.logger.info(f"添加非流式响应到记忆: {full_response}")
                
                # 更新last_response到feel_state（非流式响应）
                self.feel_state.last_response = full_response
                self.logger.debug(f"更新last_response（非流式）: {full_response}")
                
                # 非流式响应完成，更新响应时间
                self.feel_state.interaction_state.update_response_time()
                    
        except Exception as e:
            self.logger.error(f"回退文本显示失败: {e}")
            if self.window and hasattr(self.window, 'msgbox') and self.window.msgbox:
                self.window.msgbox.show_text(f"显示错误: {str(e)}")

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
        """基于状态智能处理打断
        mode 0: 不打断
        mode 1: 听到声音立即打断
        mode 2: 等待说话人说完后打断并开始新对话
        """
        self.speech_detect_time = time.time()
        
        # 更新状态
        self.feel_state.update_component_status("ear", is_hearing=True)
        self.feel_state.update_performance_metrics(speech_detect_time=self.speech_detect_time)
        
        # 基于FeelState状态判断是否需要打断
        if not self._should_interrupt():
            self.logger.debug("当前状态不适合打断")
            return
            
        # 根据打断模式执行相应操作
        if self.interrupt_mode == 1:
            # 模式1：听到声音立即打断
            self.logger.info("模式1: 检测到说话，立即打断")
            self.feel_state.update_interaction_state(interrupted=True)
            self._add_interrupted_response_to_memory()
            self._start_interrupt_thread(mode=1)
        elif self.interrupt_mode == 2:
            # 模式2：记录打断意图，等待当前响应结束
            self.logger.info("模式2: 检测到说话，等待当前响应结束后打断")
            # 这里不立即打断，而是在handle_transcription中处理
        # 模式0：不打断，只记录状态
        
    def _should_interrupt(self) -> bool:
        """基于FeelState判断是否应该打断"""
        # 如果系统未就绪，不打断
        if not self.feel_state.is_system_ready():
            self.logger.debug("系统未就绪，不执行打断")
            return False
            
        # 如果不在对话中，不需要打断
        if not self.feel_state.is_in_conversation():
            self.logger.debug("当前不在对话中，无需打断")
            return False
            
        # 如果无法接受输入，不打断
        if not self.feel_state.can_accept_input():
            self.logger.debug("当前无法接受输入，不执行打断")
            return False
            
        # 检查TTS是否真的在播放
        if not (self.mouth and hasattr(self.mouth, 'stream') and self.mouth.stream.is_playing()):
            self.logger.debug("TTS未在播放，无需打断")
            return False
            
        # 检查打断模式
        if self.interrupt_mode == 0:
            self.logger.debug("打断模式为0，不执行打断")
            return False
            
        return True
        
    def _should_process_transcription(self, text: str) -> bool:
        """基于FeelState判断是否应该处理转录文本"""
        # 检查系统是否就绪
        if not self.feel_state.is_system_ready():
            self.logger.debug("系统未就绪，忽略转录文本")
            return False
            
        # 检查是否可以接受输入
        if not self.feel_state.can_accept_input():
            self.logger.debug("当前无法接受输入，忽略转录文本")
            return False
            
        # 检查文本长度
        if len(text.strip()) == 0:
            self.logger.debug("转录文本为空，忽略")
            return False
            
        return True
        
    def _process_state_driven_interaction(self):
        """基于feel_state状态驱动的交互处理核心方法"""
        try:
            # 检查系统是否就绪
            if not self.feel_state.is_system_ready():
                self.logger.debug("系统未就绪，跳过状态驱动处理")
                return
            
            # 首先更新空闲状态 - 这是关键的状态更新机制
            self.feel_state.check_free_status()
            
            # 检查是否有用户输入需要处理
            if self.feel_state.current_user_input:
                self.logger.info(f"检测到用户输入，开始状态驱动处理: {self.feel_state.current_user_input}")
                self._handle_user_input_state()
                return
            
            # 检查is_free状态，执行自主行为（统一的自主行为触发机制）
            if self.feel_state.is_free:
                self.logger.debug("检测到is_free状态为true，处理自主行为")
                self._handle_free_time_behavior()
                return
                
        except Exception as e:
            self.logger.error(f"状态驱动处理出错: {e}")
            self.feel_state.environment_state.add_error(f"状态驱动处理出错: {e}")
    
    def _handle_user_input_state(self):
        """处理用户输入状态"""
        try:
            user_input = self.feel_state.current_user_input
            
            # 检查是否可以接受输入
            if not self.feel_state.can_accept_input():
                self.logger.warning("当前无法接受输入，清除用户输入状态")
                self.feel_state.current_user_input = None
                return
            
            # 检查是否还在对话中
            if self.feel_state.is_in_conversation():
                self.logger.warning("仍在对话中，清除用户输入状态避免重复处理")
                # 清除用户输入状态，避免定时器重复处理
                self.feel_state.current_user_input = None
                return
            
            # 开始新对话
            self._start_new_conversation(user_input)
            
            # 立即清空current_user_input，避免定时器重复处理
            self.feel_state.current_user_input = None
            self.logger.debug(f"已开始处理用户输入，清空current_user_input避免重复处理")
            
        except Exception as e:
            self.logger.error(f"处理用户输入状态出错: {e}")
            self.feel_state.environment_state.add_error(f"处理用户输入状态出错: {e}")
    

    
    def _handle_free_time_behavior(self):
        """处理is_free为true时的自主行为"""
        try:
            if self.feel_state.is_free and self.use_agent and self.agent:
                # 清空字幕
                self.window.msgbox.clear_content()
                
                # 获取空闲时间用于日志
                idle_time = self.feel_state.get_idle_time()
                self.logger.info(f"系统空闲{idle_time:.1f}秒，启动自主行为")
                
                # 设置自主行为状态标记
                self.feel_state.update_interaction_state(is_autonomous=True)
                
                # 标记free状态已被触发，立即设为false避免重复触发
                self.feel_state.mark_free_triggered()
                
                # 立即重置响应时间，将idle_time置0
                self.feel_state.interaction_state.update_response_time()
                
                # 重置响应相关状态
                self.current_response = ""
                self.received_first_chunk = False
                
                # 调用agent的handle_free_time方法
                ai_response_async_gen = self.agent.handle_free_time()
                
                # 启动TTS处理
                if self.mouth and hasattr(self.mouth, 'stream') and self.mouth.stream is not None:
                    try:
                        ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                        self.mouth.stream.feed(ai_response_iterator)
                        self.mouth.stream.play_async()
                        self.logger.info("自主行为响应已传递给TTS流")
                    except Exception as e:
                        self.logger.error(f"自主行为TTS播放失败: {e}")
                        # 回退到文本显示
                        ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                        self._fallback_text_display(ai_response_iterator)
                        # 非流式响应完成，更新响应时间
                        self.feel_state.interaction_state.update_response_time()
                        # 重置自主行为状态
                        self.feel_state.mark_autonomous_completed()
                else:
                    # 如果没有流式TTS，回退到传统方式
                    ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                    self._fallback_text_display(ai_response_iterator)
                    # 非流式响应完成，更新响应时间
                    self.feel_state.interaction_state.update_response_time()
                    # 重置自主行为状态
                    self.feel_state.mark_autonomous_completed()
                    
        except Exception as e:
            self.logger.error(f"处理自主行为出错: {e}")
            self.feel_state.environment_state.add_error(f"处理自主行为出错: {e}")
            # 即使出错也要更新响应时间，避免持续触发
            self.feel_state.interaction_state.update_response_time()
            # 重置自主行为状态
            self.feel_state.mark_autonomous_completed()
    
    def _start_autonomous_behavior(self):
        """启动自主行为"""
        try:
            self.logger.info("启动自主行为")
            
            # 标记free状态已被触发，立即设为false
            self.feel_state.mark_free_triggered()
            self.logger.debug("已标记free状态为已触发")
            
            # 清空当前用户输入，设置为自主模式
            self.feel_state.current_user_input = None
            
            # 重置响应相关状态
            self.current_response = ""
            self.received_first_chunk = False
            
            # 调用agent的自主行为
            if self.agent:
                ai_response_async_gen = self.agent.agent_chat(self.feel_state)
                
                # 启动TTS处理，使用与_handle_free_time_behavior相同的逻辑
                if self.mouth and hasattr(self.mouth, 'stream') and self.mouth.stream is not None:
                    try:
                        ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                        self.mouth.stream.feed(ai_response_iterator)
                        self.mouth.stream.play_async()
                        self.logger.info("自主行为响应已传递给TTS流")
                    except Exception as e:
                        self.logger.error(f"自主行为TTS播放失败: {e}")
                        # 回退到文本显示
                        ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                        self._fallback_text_display(ai_response_iterator)
                        # 非流式响应完成，更新响应时间
                        self.feel_state.interaction_state.update_response_time()
                else:
                    # 如果没有流式TTS，回退到传统方式
                    ai_response_iterator = self._async_to_sync_generator(ai_response_async_gen)
                    self._fallback_text_display(ai_response_iterator)
                    # 非流式响应完成，更新响应时间
                    self.feel_state.interaction_state.update_response_time()
                    
        except Exception as e:
            self.logger.error(f"启动自主行为出错: {e}")
            self.feel_state.environment_state.add_error(f"启动自主行为出错: {e}")
            # 即使出错也要更新响应时间，避免持续触发
            self.feel_state.interaction_state.update_response_time()
    
    def _start_new_conversation(self, text: str):
        """开始新对话"""
        self.logger.info(f"开始新对话: {text}")
        
        # 清空字幕，防止堆叠
        if self.sync_subtitle and self.subtitle_sync:
            self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback(force_clear=True))
            self.logger.debug("新对话开始前已清空字幕")
        
        self.window.msgbox.clear_content()
        self.current_response = ""
        self.feel_state.update_interaction_state(current_response="")
        # 更新交互时间，标记开始新对话
        self.feel_state.update_interaction_time()
        self._start_ai_response(text)

    def _on_interrupt_completed(self):
        """基于状态智能处理打断完成后的回调"""
        self.logger.info("打断操作完成")
        
        # 重置当前响应（因为已经被打断并保存到记忆中）
        self.current_response = ""
        
        # 基于状态和模式处理后续逻辑
        if self.interrupt_mode == 2 and self.pending_transcription:
            # 模式2：检查是否可以立即开始新对话
            if self._can_start_new_conversation():
                self.logger.info(f"模式2打断后开始新对话: {self.pending_transcription}")
                self._start_new_conversation(self.pending_transcription)
                self.pending_transcription = None
            else:
                self.logger.warning("系统状态不允许立即开始新对话，保留待处理文本")
                # 保留pending_transcription，等待系统就绪
        else:
            # 非模式2或没有待处理转录文本
            self._finalize_interrupt_cleanup()
            
    def _can_start_new_conversation(self) -> bool:
        """检查是否可以开始新对话"""
        # 检查系统是否就绪
        if not self.feel_state.is_system_ready():
            self.logger.debug("系统未就绪，无法开始新对话")
            return False
            
        # 检查是否可以接受输入
        if not self.feel_state.can_accept_input():
            self.logger.debug("当前无法接受输入，无法开始新对话")
            return False
            
        # 检查是否还在对话中（可能有其他组件仍在工作）
        if self.feel_state.is_in_conversation():
            self.logger.debug("仍在对话中，无法开始新对话")
            return False
            
        return True
        
    def _finalize_interrupt_cleanup(self):
        """完成打断后的清理工作"""
        # 停止字幕同步
        if self.sync_subtitle and self.subtitle_sync:
            self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback())
        
        # 打断完成后更新交互时间，开始计算空闲时间
        self.feel_state.interaction_state.update_interaction_time()
        
        # 更新组件状态
        self.feel_state.update_component_status("mouth", is_speaking=False, is_playing=False)
        self.logger.info("打断清理完成，系统进入空闲状态")
        
        # 检查是否有待处理的转录文本需要处理
        self._check_pending_transcription()
        
    def _check_pending_transcription(self):
        """检查并处理待处理的转录文本"""
        if self.pending_transcription and self._can_start_new_conversation():
            self.logger.info(f"系统空闲，处理待处理的转录文本: {self.pending_transcription}")
            text = self.pending_transcription
            self.pending_transcription = None
            self._start_new_conversation(text)

    def handle_asr_error(self, error: str):
        """处理ASR错误"""
        self.logger.error(f"ASR错误: {error}")
        self.handle_component_error("ear", error)

    def handle_component_error(self, part: str, error_msg: str = ""):
        """处理组件错误的通用方法
        
        Args:
            part: 出错的组件名称 ("ear", "mouth", "agent", "body" 等)
            error_msg: 详细错误信息
        """
        try:
            # 生成错误提示文本
            error_text = config.error.text.format(part=part)
            
            # 记录错误日志
            self.logger.error(f"组件 {part} 发生错误: {error_msg}")
            
            # 在消息框显示错误信息
            if self.window and hasattr(self.window, 'msgbox') and self.window.msgbox:
                display_error = f"{part}组件错误: {error_msg}" if error_msg else f"{part}组件发生错误"
                self.window.msgbox.show_text(display_error)
            
            # 播放错误提示音频（仅当mouth组件正常且不是mouth组件本身出错时）
            if (part != "mouth" and 
                self.mouth and 
                hasattr(self.mouth, 'stream') and 
                self.mouth.stream is not None):
                try:
                    # 先停止当前播放的内容（如果有的话）
                    if hasattr(self.mouth.stream, 'is_playing') and self.mouth.stream.is_playing():
                        self.mouth.stream.stop()
                    
                    # 播放错误提示
                    def error_text_generator():
                        yield error_text
                    
                    self.mouth.stream.feed(error_text_generator())
                    self.mouth.stream.play_async()
                    self.logger.info(f"播放错误提示: {error_text}")
                    
                except Exception as e:
                    self.logger.error(f"播放错误提示失败: {e}")
                    # 如果TTS播放失败，至少在消息框显示错误文本
                    if self.window and hasattr(self.window, 'msgbox') and self.window.msgbox:
                        self.window.msgbox.show_text(error_text)
            else:
                # 如果没有TTS或mouth组件本身出错，直接在消息框显示错误文本
                if self.window and hasattr(self.window, 'msgbox') and self.window.msgbox:
                    self.window.msgbox.show_text(error_text)
                    
        except Exception as e:
            self.logger.error(f"处理组件错误时发生异常: {e}")

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
        
        # 停止状态检查定时器
        if hasattr(self, 'state_check_timer') and self.state_check_timer:
            self.state_check_timer.stop()
            self.logger.info("状态检查定时器已停止")
        
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
            
        # 更新状态为休眠
        self.feel_state.update_component_status("brain", brain_awake=False)
        self.feel_state.update_component_status("ear", ear_running=False, ear_enabled=False, is_hearing=False)
        self.feel_state.update_component_status("mouth", mouth_enabled=False, is_speaking=False, is_playing=False)
        self.feel_state.update_component_status("agent", agent_initialized=False)
        self.feel_state.update_component_status("body", body_initialized=False)
        self.feel_state.update_environment_state(
            asr_server_connected=False,
            tts_server_connected=False,
            llm_connected=False,
            model_loaded=False
        )
            
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
                
                # M键切换监控面板
                elif key == Qt.Key.Key_M:  # Qt.Key_M
                    self.toggle_monitor_panel()
                    return True
        return False

    def toggle_agent_mode(self):
        """切换Agent智能体模式"""
        self.use_agent = not self.use_agent
        mode_text = "智能体模式" if self.use_agent else "简单聊天模式"
        
        # 更新状态
        from Head.Brain.feel import AgentMode
        agent_mode = AgentMode.AGENT if self.use_agent else AgentMode.SIMPLE_CHAT
        self.feel_state.update_component_status("agent", agent_mode=agent_mode)
        
        if self.window.msgbox:
            self.window.msgbox.show_text(f"已切换为{mode_text}")
        self.logger.info(f"切换为{mode_text}")
    
    def toggle_monitor_panel(self):
        """切换监控面板显示状态"""
        try:
            if self.monitor:
                self.monitor.toggle_panel()
                status = "显示" if self.monitor.visible else "隐藏"
                if self.window.msgbox:
                    self.window.msgbox.show_text(f"监控面板已{status}")
                self.logger.info(f"监控面板已{status}")
            else:
                if self.window.msgbox:
                    self.window.msgbox.show_text("监控器未初始化")
                self.logger.warning("监控器未初始化")
        except Exception as e:
            self.logger.error(f"切换监控面板时出错: {e}")
            if self.window.msgbox:
                self.window.msgbox.show_text(f"监控面板切换失败: {str(e)}")

    def toggle_input(self, force_voice=False):
        """切换输入方式，闭麦切换为终端文本输入，开麦切换为语音输入"""
        from Head.Brain.feel import InteractionMode
        
        if force_voice or self.input_mode == "text":
            # 切换为语音输入
            self.input_mode = "voice"
            self.feel_state.update_component_status("brain", interaction_mode=InteractionMode.VOICE)
            
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
            self.feel_state.update_component_status("brain", interaction_mode=InteractionMode.TEXT)
            
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
            self.feel_state.update_component_status("ear", ear_enabled=False, is_hearing=False)
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
            self.feel_state.update_component_status("ear", ear_enabled=True)

    def toggle_mouth(self):
        """切换mouth开启/关闭"""
        if self.mouth_enabled:
            if self.mouth and hasattr(self.mouth, 'stream'):
                self.mouth.stream.stop()
                self.logger.info("TTS已关闭")
                if self.window.msgbox:
                    self.window.msgbox.show_text("语音合成已关闭")
            self.mouth_enabled = False
            self.feel_state.update_component_status("mouth", mouth_enabled=False, is_speaking=False, is_playing=False)
        else:
            # mouth开启时无需重新初始化mouth，只需提示
            self.logger.info("TTS已开启")
            if self.window.msgbox:
                self.window.msgbox.show_text("语音合成已开启")
            self.mouth_enabled = True
            self.feel_state.update_component_status("mouth", mouth_enabled=True)

    def _on_audio_stream_start(self):
        """处理音频流开始播放的回调"""
        self.audio_start_time = time.time()
        
        # 更新状态
        self.feel_state.update_component_status("mouth", is_speaking=True, is_playing=True)
        self.feel_state.update_performance_metrics(audio_start_time=self.audio_start_time)
        
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
        # 更新状态
        self.feel_state.update_component_status("mouth", is_speaking=False, is_playing=False)
        
        # 停止字幕同步（如果启用）
        if self.sync_subtitle and self.subtitle_sync:
            self.async_loop.run_coroutine(self.subtitle_sync.stop_audio_playback())
            self.logger.debug("字幕同步已停止")
    
    # ============= 状态查询方法 =============
    
    def get_feel_state(self) -> FeelState:
        """获取当前完整的状态信息"""
        return self.feel_state
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return self.feel_state.get_status_summary()
    
    def get_component_summary(self) -> Dict[str, str]:
        """获取组件状态摘要"""
        return self.feel_state.get_component_summary()
    
    def get_performance_summary(self) -> Dict[str, Optional[float]]:
        """获取性能摘要"""
        return self.feel_state.get_performance_summary()
    
    def is_system_ready(self) -> bool:
        """检查系统是否就绪"""
        return self.feel_state.is_system_ready()
    
    def is_in_conversation(self) -> bool:
        """检查是否正在对话中"""
        return self.feel_state.is_in_conversation()
    
    def can_accept_input(self) -> bool:
        """检查是否可以接受输入"""
        return self.feel_state.can_accept_input()
    
    def print_status(self):
        """打印当前状态"""
        print("=" * 60)
        print("🧠 数字人状态报告")
        print("=" * 60)
        print(f"状态概览: {self.feel_state}")
        print()
        
        components = self.get_component_summary()
        print("📋 组件状态:")
        for component, status in components.items():
            print(f"  {component.ljust(12)}: {status}")
        print()
        
        performance = self.get_performance_summary()
        print("⚡ 性能指标:")
        for metric, value in performance.items():
            if value is not None:
                print(f"  {metric.ljust(25)}: {value:.1f}ms")
        print()
        
        print(f"🔧 系统就绪: {'✅' if self.is_system_ready() else '❌'}")
        print(f"💬 对话中: {'✅' if self.is_in_conversation() else '❌'}")
        print(f"📝 可接受输入: {'✅' if self.can_accept_input() else '❌'}")
        print(f"😴 空闲状态: {'✅' if self.feel_state.is_free else '❌'}")
        print(f"⏱️ 运行时长: {self.feel_state.get_uptime():.1f}秒")
        print(f"💭 总交互次数: {self.feel_state.total_interactions}")
        print("=" * 60)


if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())