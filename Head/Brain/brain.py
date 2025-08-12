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

class AIResponseWorker(QThread):
    """AI响应处理工作线程"""
    content_ready = pyqtSignal(str)  # 内容就绪信号
    response_complete = pyqtSignal(str)  # 响应完成信号
    error_occurred = pyqtSignal(str)  # 错误信号
    
    def __init__(self, agent, text):
        super().__init__()
        self.agent = agent
        self.text = text
        self.should_stop = False
        
    def run(self):
        try:
            full_response = ""
            for content in self.agent.common_chat(self.text):
                if self.should_stop:
                    break
                if content:
                    full_response += content
                    self.content_ready.emit(content)
            
            if not self.should_stop:
                self.response_complete.emit(full_response)
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def stop(self):
        self.should_stop = True

config = DotMap(toml.load("config.toml"))

class Brain:
    """统筹管理所有的功能模块，在各个线程模块之间传递信息"""
    def __init__(self):
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        self.current_response = ""
        self.pending_text = ""  # 待语音合成的累积文本
        self.interrupt_mode = config.asr.interrupt_mode
        self.tts_text_chunk_size = config.tts.text_chunk_size if hasattr(config.tts, 'text_chunk_size') else 1024
        self.end_punctuation = config.tts.end_punctuation if hasattr(config.tts, 'end_punctuation') else ['。', '！', '？', '.', '!', '?', '；', ';', ':', '：']
        self.interrupted = False  # 新增打断标志
        self.ai_worker = None
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
        self.agent = AIFE(platform=config.llm.platform, llm_config=config.llm.llm_config)
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
        if text.strip() and len(text) > 10:  # 只处理非空文本
            try:
                if self.interrupt_mode == 2:
                    # 模式2：说话结束后打断当前响应并开始新对话
                    if self.ai_worker and self.ai_worker.isRunning():
                        self.ai_worker.stop()
                        logger.info("打断AI生成")
                    if self.mouth:
                        self.mouth.stream.stop()
                        logger.info("打断TTS stream")
                    
                    # 立即开始处理新的对话
                    self.window.msgbox.clear_content()
                    self.current_response = ""
                    self.pending_text = ""  # 清空待合成文本
                    self.ai_worker = AIResponseWorker(self.agent, text)
                    self.ai_worker.content_ready.connect(self.on_ai_content_ready)
                    self.ai_worker.response_complete.connect(self.on_ai_response_complete)
                    self.ai_worker.error_occurred.connect(self.on_ai_error)
                    self.ai_worker.start()
                    return

                elif self.interrupt_mode == 0:
                    # 模式0：等待当前响应完成后再处理新对话
                    if self.ai_worker and self.ai_worker.isRunning():
                        return  # 如果当前有响应在处理，直接返回
                
                # 处理新对话（适用于模式0的空闲状态和模式1）
                if self.agent:
                    self.window.msgbox.clear_content()
                    self.current_response = ""
                    self.pending_text = ""  # 清空待合成文本
                    self.ai_worker = AIResponseWorker(self.agent, text)
                    self.ai_worker.content_ready.connect(self.on_ai_content_ready)
                    self.ai_worker.response_complete.connect(self.on_ai_response_complete)
                    self.ai_worker.error_occurred.connect(self.on_ai_error)
                    self.ai_worker.start()
                            
            except Exception as e:
                logger.error(f"处理AIFE响应时出错: {e}")
                if self.window.msgbox:
                    self.window.msgbox.show_text(f"AI处理错误: {str(e)}")
    
    def should_speak_now(self, text: str) -> bool:
        """判断是否应该立即进行语音合成
        必须满足两个条件：
        1. 字数至少达到 text_chunk_size
        2. 包含完整的句子（以 end_punctuation 结尾）
        """
        # 首要条件：字数必须至少达到 text_chunk_size
        if len(text) < self.tts_text_chunk_size:
            return False
        
        # 次要条件：必须包含句子结束标点符号
        return any(punct in text for punct in self.end_punctuation)
    
    def extract_speakable_text(self, text: str) -> tuple[str, str]:
        """从文本中提取可以语音合成的部分
        返回：(可以speak的文本, 剩余文本)
        确保提取的文本至少有 text_chunk_size 个字符且是完整句子
        """
        # 如果总长度小于 text_chunk_size，不进行分割
        if len(text) < self.tts_text_chunk_size:
            return "", text
        
        # 从 text_chunk_size 位置往后寻找第一个句子结束标点
        for i in range(self.tts_text_chunk_size, len(text)):
            if text[i] in self.end_punctuation:
                return text[:i + 1], text[i + 1:]
        
        # 如果没找到完整句子的结束标点，返回空字符串和原文本
        return "", text

    def on_ai_error(self, error: str):
        """处理AI错误信号"""
        logger.error(f"AI处理错误: {error}")
        if self.window.msgbox:
            self.window.msgbox.show_text(f"AI处理错误: {error}")


    def on_ai_content_ready(self, content: str):
        """处理AI内容就绪信号"""
        self.current_response += content
        self.pending_text += content
        self.window.msgbox.update_text(content)
        
        # 检查是否应该进行语音合成
        if self.should_speak_now(self.pending_text):
            speakable_text, remaining_text = self.extract_speakable_text(self.pending_text)
            
            if speakable_text.strip() and self.mouth:
                logger.info(f"流式语音合成: {speakable_text[:50]}...")
                # 根据TTS类型调用不同方法
                if hasattr(self.mouth, 'speak'):
                    self.mouth.speak(speakable_text.strip())
                elif hasattr(self.mouth, 'add_text'):
                    self.mouth.add_text(speakable_text.strip())
            
            # 更新待合成文本为剩余部分
            self.pending_text = remaining_text
    
    def on_ai_response_complete(self, full_response: str):
        """处理AI响应完成信号"""
        logger.info(f"最终合成响应: {full_response[:200]}...")
        
        # 处理剩余的待合成文本
        if self.pending_text.strip() and self.mouth:
            logger.info(f"最终语音合成: {self.pending_text[:50]}...")
            if hasattr(self.mouth, 'speak'):
                self.mouth.speak(self.pending_text.strip())
            elif hasattr(self.mouth, 'add_text'):
                self.mouth.add_text(self.pending_text.strip())
        
        # 清空待合成文本
        self.pending_text = ""
        
        if full_response.strip() and self.window.msgbox and self.agent:
            self.window.msgbox.show_text(f"{full_response}")
            self.agent.short_term_memory.add_ai_message(AIMessage(content=full_response))

    def handle_interrupt(self):
        """打断正在说话
        mode 0: 不打断
        mode 1: 听到声音立即打断
        mode 2: 等待说话人说完后打断并开始新对话
        """
        if self.interrupt_mode == 1:
            # 模式1：听到声音就立即打断
            if self.ai_worker and self.ai_worker.isRunning():
                self.ai_worker.stop()
                logger.info("打断AI生成")
            if self.mouth:
                self.mouth.stream.stop()
                logger.info("打断TTS stream")
            # 清空待合成文本
            self.pending_text = ""
        # 模式0和2在这里不做任何处理

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
        
        # 停止AI工作线程
        if self.ai_worker and self.ai_worker.isRunning():
            self.ai_worker.stop()
            self.ai_worker.wait(1000)
        
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
        self.ai_worker = None
        
        logger.info("大脑已休眠")

if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())