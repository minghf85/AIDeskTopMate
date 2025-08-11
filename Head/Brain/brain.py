import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from Body.tlw import TransparentLive2dWindow, Live2DSignals
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from Message.MessageBox import MessageBox
from Head.Brain.agent import AIFE
from Head.ear import ASR
from Head.mouth import TTS_GSV,TTS_realtime
from dotmap import DotMap
import toml
from loguru import logger

config = DotMap(toml.load("config.toml"))

class Brain:
    """统筹管理所有的功能模块，在各个线程模块之间传递信息"""
    def __init__(self):
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        self.msg = None
        self.current_response = ""
        self.interrupted = False
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
        self.ear.transcriptionReady.connect(self.handle_transcription)
        self.ear.errorOccurred.connect(self.handle_asr_error)
        
        # 设置音频设备并启动ASR
        try:
            self.ear.setup_audio()
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
        self.window._load_model(config.live2d.model_path)
        self.msg = MessageBox()  # 使用self.msg而不是self.msgbox
        self.msg.show()
        self.msg.show_text("大脑已唤醒，系统运行中...")
        return self.window.model

    def handle_transcription(self, text: str):
        """处理ASR识别结果"""
        if text.strip():  # 只处理非空文本
            try:
                if self.agent:
                    full_response = ""
                    # current_segment = ""
                    # first_sentence_in = True
                    
                    try:
                        self.msg.clear_content()
                        for content in self.agent.common_chat(text):
                            if self.interrupted:
                                logger.info("生成被打断")
                                break
                                
                            if content:
                                full_response += content
                                # current_segment += content
                                self.msg.update_text(content)
                                
                                # # TTS处理
                                # if self.mouth:
                                #     if len(current_segment) < 8:
                                #         continue
                                    
                                #     if any(current_segment.endswith(p) for p in ',.?!，。！？；：…—'):
                                #         if first_sentence_in:
                                #             self.mouth.speak("." + current_segment)
                                #             first_sentence_in = False
                                #         else:
                                #             self.mouth.speak(current_segment)
                                #         current_segment = ""
                                
                                # self.app.processEvents()

                    except Exception as e:
                        logger.error(f"流式处理异常: {str(e)}", exc_info=True)
                        full_response = f"处理请求时出错: {str(e)}"
                    finally:
                        logger.info(f"最终合成响应: {full_response[:200]}...")  # 日志截断长文本
                    
                    # 显示AI响应
                    if full_response.strip() and self.msg:
                        self.mouth.speak(full_response)
                        self.msg.show_text(f"{full_response}")
                        self.agent.short_term_memory.add_ai_message(AIMessage(content=full_response))
                            
            except Exception as e:
                logger.error(f"处理AIFE响应时出错: {e}")
                if self.msg:
                    self.msg.show_text(f"AI处理错误: {str(e)}")

    def handle_asr_error(self, error: str):
        """处理ASR错误"""
        logger.error(f"ASR错误: {error}")
        if self.msg:
            self.msg.show_text(f"语音识别错误: {error}")

    def clear_accumulated_text(self):
        """清空累计文本"""
        self.accumulated_text = ""
        if self.msg:
            self.msg.show_text("文本已清空")
    
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
        
        # 停止ASR
        if self.ear:
            self.ear.stop()
            logger.info("ASR已停止")
        
        # 关闭消息窗口
        if self.msg:
            self.msg.close()
            
        # 关闭Live2D窗口
        if hasattr(self, 'window') and self.window:
            self.window.close()
            
        # 清理资源
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        self.msg = None
        
        logger.info("大脑已休眠")

if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())