import sys
import signal
import threading
import queue
import time
from typing import Dict, Any, Callable, Optional
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from Body.tlw import TransparentLive2dWindow, Live2DSignals
from Head.Brain.agent import Agent,LangchainAgent
from Head.ear import ASR
from Head.mouth import TTS_GSV,TTS_realtime
from Message.message import Message, MessageType
from Message.MessageBox import MessageBox
from dotmap import DotMap
import toml

config = DotMap(toml.load("config.toml"))

class BrainSignals(QObject):
    """大脑信号类，用于Qt信号通信"""
    message_received = pyqtSignal(object)  # 接收到消息
    response_generated = pyqtSignal(str)   # 生成响应
    emotion_changed = pyqtSignal(str)      # 情感变化
    action_triggered = pyqtSignal(str, dict)  # 动作触发

class Brain:
    """统筹管理所有的功能模块，在各个线程模块之间传递信息"""
    def __init__(self):
        # 核心模块
        self.agent = None
        self.asr = None
        self.mouth = None
        self.body = None
        self.message_box = None
        
        # 通信系统
        self.signals = BrainSignals()
        self.message_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.running = True
        
        # 消息处理器注册表
        self.message_handlers: Dict[MessageType, Callable] = {}
        self.register_default_handlers()
        
        # 启动系统
        self.wakeup()
        
        # 启动消息处理线程
        self.message_thread = threading.Thread(target=self._message_processor, daemon=True)
        self.message_thread.start()
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, lambda s, f: self.signal_handler(s, f))

    def register_default_handlers(self):
        """注册默认的消息处理器"""
        self.message_handlers[MessageType.TEXT] = self.handle_text_message
        self.message_handlers[MessageType.COMMAND] = self.handle_command_message
        self.message_handlers[MessageType.EVENT] = self.handle_event_message
        self.message_handlers[MessageType.EMOTION] = self.handle_emotion_message
        self.message_handlers[MessageType.SYSTEM] = self.handle_system_message
    
    def register_message_handler(self, msg_type: MessageType, handler: Callable):
        """注册自定义消息处理器"""
        self.message_handlers[msg_type] = handler
    
    def send_message(self, msg_type: MessageType, content: Any, sender: str = "brain", receiver: str = "", metadata: Optional[Dict] = None):
        """发送消息到消息队列"""
        message = Message(msg_type, content, sender, receiver, metadata)
        self.message_queue.put(message)
        return message
    
    def _message_processor(self):
        """消息处理器主循环（在后台线程运行）"""
        while self.running:
            try:
                # 获取消息（阻塞等待）
                message = self.message_queue.get(timeout=1.0)
                
                # 处理消息
                if message.msg_type in self.message_handlers:
                    try:
                        response = self.message_handlers[message.msg_type](message)
                        if response:
                            self.response_queue.put(response)
                    except Exception as e:
                        print(f"处理消息时出错: {e}")
                
                # 标记任务完成
                self.message_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"消息处理器错误: {e}")
    
    def handle_text_message(self, message: Message) -> Optional[Message]:
        """处理文本消息"""
        print(f"收到文本消息: {message.content}")
        
        # 如果有智能体，让智能体处理
        if self.agent:
            try:
                # 准备输入数据
                input_data = {
                    "message": message.content,
                    "sender": message.sender,
                    "metadata": message.metadata
                }
                
                # 智能体处理
                response = self.agent.process(input_data)
                
                # 显示响应
                if "response" in response and self.message_box:
                    self.message_box.show_text(response["response"])
                
                # 如果有TTS，播放语音
                if "response" in response and self.mouth:
                    self.mouth.speak(response["response"])
                
                return Message(MessageType.TEXT, response.get("response", ""), "agent", message.sender)
                
            except Exception as e:
                print(f"智能体处理错误: {e}")
                return Message(MessageType.SYSTEM, f"处理错误: {e}", "brain", message.sender)
        
        return None
    
    def handle_command_message(self, message: Message) -> Optional[Message]:
        """处理命令消息"""
        print(f"收到命令消息: {message.content}")
        
        command = message.content
        if isinstance(command, dict):
            cmd_type = command.get("type")
            cmd_data = command.get("data")
            
            if cmd_type == "show_image" and self.message_box:
                self.message_box.show_image(cmd_data)
            elif cmd_type == "show_gif" and self.message_box:
                self.message_box.show_gif(cmd_data)
            elif cmd_type == "clear_display" and self.message_box:
                self.message_box.clear_content()
            elif cmd_type == "set_emotion" and self.body:
                # 设置Live2D情感
                pass
        
        return Message(MessageType.SYSTEM, "命令已执行", "brain", message.sender)
    
    def handle_event_message(self, message: Message) -> Optional[Message]:
        """处理事件消息"""
        print(f"收到事件消息: {message.content}")
        # 可以在这里处理各种系统事件
        return None
    
    def handle_emotion_message(self, message: Message) -> Optional[Message]:
        """处理情感消息"""
        print(f"收到情感消息: {message.content}")
        # 可以在这里处理情感变化，影响Live2D表情等
        if self.body:
            # 触发Live2D情感变化
            pass
        return None
    
    def handle_system_message(self, message: Message) -> Optional[Message]:
        """处理系统消息"""
        print(f"收到系统消息: {message.content}")
        return None

    def signal_handler(self, signum, frame):
        """处理Ctrl+C信号"""
        print("\nReceived Ctrl+C, shutting down...")
        self.running = False
        self.app.quit()
        sys.exit(0)

    def wakeup(self):
        """唤醒大脑，从头往下激活"""
        print("正在唤醒大脑...")
        
        # 初始化智能体
        self.agent = LangchainAgent(llm=config.llm.model, name="LangchainAgent", prompt_template="一个人工智能助手")
        print("智能体已激活")
        
        # 初始化语音识别
        self.ear = ASR()
        print("语音识别已激活")
        
        # 初始化语音合成
        if config.tts.mode == "GSV":
            self.mouth = TTS_GSV()
        elif config.tts.mode == "realtime":
            self.mouth = TTS_realtime()
        print(f"语音合成已激活 ({config.tts.mode})")
        
        # 激活身体和消息显示
        self.body = self.activate_body()
        self.message_box = MessageBox()
        self.message_box.show()
        print("身体和消息显示已激活")
        
        print("大脑唤醒完成！")

    def activate_body(self):
        """激活Live2D身体"""
        self.live2d_signals = Live2DSignals()
        self.app = QApplication(sys.argv)
        self.window = TransparentLive2dWindow(self.live2d_signals, self.mouth)
        self.window.show()
        self.window._load_model(config.live2d.model_path)
        return self.window.model

    # 便捷API方法
    def say(self, text: str, show_in_ui: bool = True, speak_aloud: bool = True):
        """让AI说话（显示文本和/或语音播放）"""
        if show_in_ui and self.message_box:
            self.message_box.show_text(text)
        
        if speak_aloud and self.mouth:
            self.mouth.speak(text)
    
    def show_image(self, image_path: str):
        """显示图片"""
        if self.message_box:
            self.message_box.show_image(image_path)
    
    def show_gif(self, gif_path: str):
        """显示GIF"""
        if self.message_box:
            self.message_box.show_gif(gif_path)
    
    def clear_display(self):
        """清除显示内容"""
        if self.message_box:
            self.message_box.clear_content()
    
    def process_user_input(self, user_input: str, sender: str = "user"):
        """处理用户输入（便捷方法）"""
        return self.send_message(MessageType.TEXT, user_input, sender)
    
    def execute_command(self, command_type: str, data: Any, sender: str = "system"):
        """执行命令（便捷方法）"""
        command = {"type": command_type, "data": data}
        return self.send_message(MessageType.COMMAND, command, sender)
    
    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """设置情感状态"""
        emotion_data = {"emotion": emotion, "intensity": intensity}
        return self.send_message(MessageType.EMOTION, emotion_data, "brain")
    
    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "running": self.running,
            "agent_active": self.agent is not None,
            "asr_active": self.ear is not None,
            "tts_active": self.mouth is not None,
            "body_active": self.body is not None,
            "message_box_active": self.message_box is not None,
            "message_queue_size": self.message_queue.qsize(),
            "response_queue_size": self.response_queue.qsize()
        }

    def sleep(self):
        """让大脑进入休眠状态"""
        print("正在让大脑进入休眠状态...")
        
        # 停止消息处理
        self.running = False
        
        # 清理资源
        if self.message_box:
            self.message_box.close()
            self.message_box = None
        
        if self.window:
            self.window.close()
        
        self.agent = None
        self.ear = None
        self.mouth = None
        self.body = None
        
        print("大脑已进入休眠状态")

if __name__ == "__main__":
    brain = Brain()
    sys.exit(brain.app.exec())