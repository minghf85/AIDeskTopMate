import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from Body.tlw import TransparentLive2dWindow, Live2DSignals
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from Head.Brain.agent import AIFE
from Head.ear import ASR
from Head.mouth import TTS_GSV,TTS_realtime
from dotmap import DotMap
import toml
from loguru import logger

config = DotMap(toml.load("config.toml"))

class TextSignals(QObject):
    """用于发送文本更新信号的类"""
    update_text = pyqtSignal(str)

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

class Brain:
    """统筹管理所有的功能模块，在各个线程模块之间传递信息"""
    def __init__(self):
        self.text_signals = TextSignals()
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        self.current_response = ""
        self.interrupt_mode = config.asr.interrupt_mode
        self.end_punctuation = config.tts.end_punctuation  # 获取结束标点符号列表
        self.interrupted = False  # 新增打断标志
        self.interrupt_thread = None  # 打断线程
        self.pending_transcription = None  # 等待处理的转录文本
        self.wakeup()
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, lambda s, f: self.signal_handler(s, f))

    def signal_handler(self, signum, frame):
        """处理Ctrl+C信号"""
        print("\nReceived Ctrl+C, shutting down...")
        self.app.quit()
        sys.exit(0)

    def wakeup(self):
        """唤醒大脑，从头往下激活"""
        self.ear = ASR(url=config.asr.settings.url, lang=config.asr.settings.lang, sv=config.asr.settings.sv)
        
        # 连接ASR信号到处理方法
        self.ear.hearStart.connect(self.handle_interrupt)
        self.ear.transcriptionReady.connect(self.handle_transcription)
        self.ear.errorOccurred.connect(self.handle_asr_error)
        
        # 设置音频设备并启动ASR
        try:
            self.ear.setup_audio_stream()
            self.ear.start()
            logger.info("ASR已启动")
        except Exception as e:
            logger.error(f"启动ASR失败: {e}")
            
        if config.tts.mode == "GSV":
            self.mouth = TTS_GSV()
        elif config.tts.mode == "realtime":
            self.mouth = TTS_realtime()
        self.body = self.activate_body()
        # 连接文本更新信号
        self.text_signals.update_text.connect(self.window.msgbox.update_text)
        self.agent = AIFE(platform=config.llm.platform, llm_config=config.llm.llm_config, stream_chat_callback=self.show_character)

    def activate_body(self):
        self.signals = Live2DSignals()
        self.app = QApplication(sys.argv)
        self.window = TransparentLive2dWindow(self.signals, self.mouth)
        self.window.show()
        self.window.msgbox.show()
        self.window._load_model(config.live2d.model_path)
        self.window.msgbox.show_text("大脑已唤醒，系统运行中...")
        return self.window.model

    def handle_transcription(self, text: str):
        """处理ASR识别结果"""
        if text.strip() and text not in self.end_punctuation:  # 只处理非空文本和非单个或多个标点符号
            try:
                if self.interrupt_mode == 2:
                    # 模式2：说话结束后打断当前响应并开始新对话
                    self.pending_transcription = text
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

    def show_character(self, character: str):
        """显示角色说话的文本"""
        if self.window.msgbox:
            self.text_signals.update_text.emit(character)

    def _start_ai_response(self, text: str):
        """启动AI响应处理"""
        try:
            if self.agent:
                # 使用流式方式处理AI响应
                ai_response_iterator = self.agent.common_chat(text)
                
                # 将AI响应迭代器传递给TTS流
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
                    
                    if self.mouth and hasattr(self.mouth, 'speak'):
                        self.mouth.speak(full_response)
                    
                    # 添加到记忆
                    if self.agent:
                        self.agent.short_term_memory.add_ai_message(AIMessage(content=full_response))
                        
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
        if self.interrupt_mode == 1:
            # 模式1：听到声音就立即打断
            self._start_interrupt_thread(mode=1)
        # 模式0和2在这里不做任何处理

    def _start_interrupt_thread(self, mode):
        """启动打断线程"""
        # 如果已有打断线程在运行，先停止它
        if self.interrupt_thread and self.interrupt_thread.isRunning():
            self.interrupt_thread.stop_thread()
        
        # 创建新的打断线程
        self.interrupt_thread = Interrupt(self.mouth, mode)
        self.interrupt_thread.interrupt_completed.connect(self._on_interrupt_completed)
        self.interrupt_thread.start()

    def _on_interrupt_completed(self):
        """打断完成后的回调"""
        logger.info("打断操作完成")
        
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
        if text.strip():
            self.handle_transcription(text)

    def sleep(self):
        """让大脑进入休眠状态"""
        logger.info("大脑进入休眠状态...")
        
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
        
        logger.info("大脑已休眠")

if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())