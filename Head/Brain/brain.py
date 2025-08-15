import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt, QTimer
from Body.tlw import TransparentLive2dWindow, Live2DSignals
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from Head.Brain.agent import AIFE
from Head.ear_improved import ASRImproved as ASR
from Head.mouth import TTS_GSV,TTS_realtime
from Head.Brain.sync import SubtitleSync,TextSignals,Interrupt
from dotmap import DotMap
import toml
from loguru import logger
from PyQt6.QtGui import QKeyEvent
import time
import threading

config = DotMap(toml.load("config.toml"))

class TerminalInputThread(QThread):
    """后台线程监听终端输入"""
    def __init__(self, brain):
        super().__init__()
        self.brain = brain
        self.running = True

    def run(self):
        while self.running:
            try:
                text = input("请输入文本（按I键切换回语音输入）：")
                if text.strip() and self.running:  # 检查是否仍在运行
                    self.brain.send_text_to_ai(text)
            except EOFError:
                break

    def stop(self):
        self.running = False
        # 发送一个换行以解除input阻塞
        print("\n")

class Brain(QObject):
    """统筹管理所有的功能模块，在各个线程模块之间传递信息"""
    def __init__(self):
        super().__init__()  # 调用 QObject 的初始化方法
        self.text_signals = TextSignals()
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
        self.interrupt_thread = None  # 打断线程
        self.pending_transcription = None  # 等待处理的转录文本
        self.ear_enabled = True
        self.mouth_enabled = True
        self.input_mode = "voice"  # "voice" 或 "text"
        self.terminal_input_thread = None
        
        # 字幕同步相关（将在activate_body中初始化，确保在主线程中）
        self.subtitle_sync = None
        
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
            logger.info("ASR线程已启动")
        except Exception as e:
            logger.error(f"启动ASR失败: {e}")
            
        if config.tts.mode == "GSV":
            self.mouth = TTS_GSV()
            # 后面再实现
        elif config.tts.mode == "realtime":
            # 根据同步设置决定回调函数
            if self.sync_subtitle:
                self.mouth = TTS_realtime(
                    on_word=self.show_word, 
                    on_character=self.show_character,
                    on_audio_stream_start=self._on_audio_stream_start,
                    on_audio_stream_stop=self._on_audio_stream_stop,
                    on_text_stream_stop=self._on_text_stream_stop,
                    on_text_stream_start=self._on_text_stream_start
                )
            else:
                self.mouth = TTS_realtime(
                    on_word=None, 
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
        self.agent = AIFE(agent_config=config.agent, stream_chat_callback=self.on_stream_chat_callback)

    def activate_body(self):
        self.signals = Live2DSignals()
        self.app = QApplication(sys.argv)
        self.window = TransparentLive2dWindow(self.signals, self.mouth)
        self.window.show()
        self.window.msgbox.show()
        self.window._load_model(config.live2d.model_path)
        self.window.msgbox.show_text("大脑已唤醒，系统运行中...")
        
        # 在主线程中初始化字幕同步
        if self.sync_subtitle:
            self.subtitle_sync = SubtitleSync()
            self.subtitle_sync.show_character.connect(self._show_character_delayed)
        
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
                if self.agent:
                    self.agent.short_term_memory.add_ai_message(AIMessage(content=interrupted_response))
                    logger.info(f"添加被打断的响应到记忆: {interrupted_response}")

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
                    logger.info(f"语音转录延迟: {transcription_delay:.3f}秒")

                if self.interrupt_mode == 2 and self.mouth.stream.stream_running:
                    # 模式2：说话结束后打断当前响应并开始新对话
                    self.pending_transcription = text
                    self._add_interrupted_response_to_memory()
                    self._start_interrupt_thread(mode=2)
                    return

                elif self.interrupt_mode == 0:
                    # 模式0：等待当前响应完成后再处理新对话
                    if hasattr(self.mouth, 'stream') and self.mouth.stream.stream_running:
                        return  # 如果当前有响应在处理，直接返回
                
                # 处理新对话（适用于模式0的空闲状态和模式1）
                self.window.msgbox.clear_content()
                self.current_response = ""
                self._start_ai_response(text)
                            
            except Exception as e:
                logger.error(f"处理AIFE响应时出错: {e}")
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
            self.agent.short_term_memory.add_ai_message(AIMessage(content=self.current_response))
            logger.info(f"添加完整响应到记忆: {self.current_response}")
        
        self.current_response = ""
        self.received_all_chunks_time = time.time()

    def on_stream_chat_callback(self, text: str):
        """处理流式聊天返回的文本"""
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
        if self.sync_subtitle and self.subtitle_sync:
            # 将字符添加到字幕同步器
            self.subtitle_sync.add_character(character)

    def show_word(self, timing_info):
        """处理TTS返回的单词时间信息 - 仅在同步模式下使用"""
        if self.sync_subtitle and self.subtitle_sync:
            # 将时间信息添加到字幕同步器
            self.subtitle_sync.add_word_timing(timing_info)
    
    def _show_character_delayed(self, character: str):
        """实际显示字符的方法 - 仅在同步模式下使用"""
        if self.window.msgbox:
            logger.debug(f"显示字符: '{character}'")
            self.text_signals.update_text.emit(character)

    def _start_interrupt_thread(self, mode):
        """启动打断线程"""
        # 如果已有打断线程在运行，先停止它
        if self.interrupt_thread and self.interrupt_thread.isRunning():
            self.interrupt_thread.stop_thread()
        
        # 创建新的打断线程
        self.interrupt_thread = Interrupt(self.mouth, mode)
        self.interrupt_thread.interrupt_completed.connect(self._on_interrupt_completed)
        self.interrupt_thread.start()

    def _start_ai_response(self, text: str):
        """启动AI响应处理"""
        try:
            if self.agent:
                # 重置当前响应文本和相关标志
                self.current_response = ""
                self.received_first_chunk = False
                
                # 记录发送给AIFE的时间
                send_to_aife_time = time.time()
                
                if self.sync_subtitle and self.subtitle_sync:
                    self.subtitle_sync.start_audio_playback()
                
                logger.info(f"开始处理: {text}")
                ai_response_iterator = self.agent.common_chat(text)
                
                # 计算并记录AIFE响应延迟
                if self.aife_response_time:
                    aife_delay = send_to_aife_time - self.aife_response_time
                    logger.info(f"发送给AIFE->接收响应延迟: {aife_delay:.3f}秒")

                if self.mouth and hasattr(self.mouth, 'stream'):
                    self.mouth.stream.feed(ai_response_iterator)
                    self.mouth.stream.play_async()
                    logger.info("AI响应已传递给TTS流")
                else:
                    # 如果没有流式TTS，回退到传统方式
                    full_response = ""
                    for content in ai_response_iterator:
                        if content:
                            full_response += content
                            self.window.msgbox.update_text(content)
                    
                    # 非流式情况下直接添加到记忆
                    if self.agent and full_response:
                        self.agent.short_term_memory.add_ai_message(AIMessage(content=full_response))
                        logger.info(f"添加非流式响应到记忆: {full_response}")
                    
                    if hasattr(self.mouth, 'stream'):
                        self.mouth.stream.feed(full_response)
                        
        except Exception as e:
            logger.error(f"启动AI响应时出错: {e}")
            if self.window.msgbox:
                self.window.msgbox.show_text(f"AI处理错误: {str(e)}")

    def handle_interrupt(self):
        """打断正在说话
        mode 0: 不打断
        mode 1: 听到声音立即打断
        mode 2: 等待说话人说完后打断并开始新对话
        """
        self.speech_detect_time = time.time()
        if self.interrupt_mode == 1 and self.mouth.stream.stream_running:
            # 模式1：听到声音就立即打断
            logger.info("检测到说话")
            self._add_interrupted_response_to_memory()
            self._start_interrupt_thread(mode=1)
        # 模式0和2在这里不做任何处理

    def _on_interrupt_completed(self):
        """打断完成后的回调"""
        logger.info("打断操作完成")
        
        # 重置当前响应（因为已经被打断并保存到记忆中）
        self.current_response = ""
        
        # 仅在同步模式下停止字幕同步
        if self.sync_subtitle and self.subtitle_sync:
            self.subtitle_sync.stop_audio_playback()
        
        # 如果是模式2且有待处理的转录文本，立即开始新对话
        if self.interrupt_mode == 2 and self.pending_transcription:
            self.window.msgbox.clear_content()
            self.current_response = ""
            self._start_ai_response(self.pending_transcription)
            self.pending_transcription = None

    def handle_asr_error(self, error: str):
        """处理ASR错误"""
        logger.error(f"ASR错误: {error}")
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
        logger.info("大脑进入休眠状态...")
        
        # 如果当前有TTS在运行，先处理被打断的响应
        if hasattr(self.mouth, 'stream') and self.mouth.stream and self.mouth.stream.stream_running:
            self._add_interrupted_response_to_memory()
        
        # 仅在同步模式下停止字幕同步
        if self.sync_subtitle and self.subtitle_sync:
            self.subtitle_sync.stop_audio_playback()
        
        # 停止打断线程
        if self.interrupt_thread and self.interrupt_thread.isRunning():
            self.interrupt_thread.stop_thread()
        
        # 停止TTS流
        if self.mouth and hasattr(self.mouth, 'stream'):
            self.mouth.stream.stop()
        
        # 停止ASR
        if self.ear:
            self.ear.stop()
            logger.info("ASR已停止")
        
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
        if self.terminal_input_thread:
            self.terminal_input_thread.stop()
            self.terminal_input_thread = None
        
        logger.info("大脑已休眠")

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
        return False

    def toggle_input(self, force_voice=False):
        """切换输入方式，闭麦切换为终端文本输入，开麦切换为语音输入"""
        if force_voice or self.input_mode == "text":
            # 切换为语音输入
            self.input_mode = "voice"
            if self.terminal_input_thread:
                self.terminal_input_thread.stop()
                self.terminal_input_thread = None
            if not self.ear_enabled:
                self.toggle_ear()  # 开麦
            if self.window.msgbox:
                self.window.msgbox.show_text("已切换为语音输入（开麦）")
            logger.info("切换为语音输入")
        else:
            # 切换为文本输入
            self.input_mode = "text"
            if self.ear_enabled:
                self.toggle_ear()  # 闭麦
            if self.window.msgbox:
                self.window.msgbox.show_text("已切换为终端文本输入（闭麦）")
            logger.info("切换为终端文本输入")
            # 启动终端输入线程
            if self.terminal_input_thread:
                self.terminal_input_thread.stop()
                self.terminal_input_thread = None
            self.terminal_input_thread = TerminalInputThread(self)
            self.terminal_input_thread.start()

    def toggle_ear(self):
        """切换ear开启/关闭"""
        if self.ear_enabled:
            if self.ear:
                try:
                    self.ear.stop_stream()
                    logger.info("闭麦")
                    if self.window.msgbox:
                        self.window.msgbox.show_text("已闭麦")
                except Exception as e:
                    logger.error(f"闭麦失败: {e}")
            self.ear_enabled = False
        else:
            if self.ear:
                try:
                    self.ear.resume_stream()
                    logger.info("开麦")
                    if self.window.msgbox:
                        self.window.msgbox.show_text("已开麦")
                except Exception as e:
                    logger.error(f"开麦失败: {e}")
            self.ear_enabled = True

    def toggle_mouth(self):
        """切换mouth开启/关闭"""
        if self.mouth_enabled:
            if self.mouth and hasattr(self.mouth, 'stream'):
                self.mouth.stream.stop()
                logger.info("TTS已关闭")
                if self.window.msgbox:
                    self.window.msgbox.show_text("语音合成已关闭")
            self.mouth_enabled = False
        else:
            # mouth开启时无需重新初始化mouth，只需提示
            logger.info("TTS已开启")
            if self.window.msgbox:
                self.window.msgbox.show_text("语音合成已开启")
            self.mouth_enabled = True

    def _on_audio_stream_start(self):
        """处理音频流开始播放的回调"""
        self.audio_start_time = time.time()
        
        # 计算从AIFE响应到开始播放的延迟
        if self.aife_response_time:
            tts_delay = self.audio_start_time - self.aife_response_time
            logger.info(f"TTS开始播放延迟: {tts_delay:.3f}秒")
        
        # 计算从转录完成到开始播放的总延迟
        if self.transcription_complete_time:
            total_delay = self.audio_start_time - self.transcription_complete_time
            logger.info(f"总响应延迟(从转录完成到开始播放): {total_delay:.3f}秒")

        # 重置时间戳，为下一轮做准备
        self.speech_detect_time = None
        self.transcription_complete_time = None
        self.aife_response_time = None
        self.audio_start_time = None

    def _on_audio_stream_stop(self):
        pass

if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())