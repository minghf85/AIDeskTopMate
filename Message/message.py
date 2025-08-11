from typing import Dict, Any, List, Optional, Union
import json
import time
from enum import Enum, auto


class MessageType(Enum):
    """消息类型枚举"""
    TEXT = auto()       # 文本消息
    COMMAND = auto()    # 命令消息
    EVENT = auto()      # 事件消息
    EMOTION = auto()    # 情感消息
    SYSTEM = auto()     # 系统消息
    CUSTOM = auto()     # 自定义消息


class Message:
    """消息基类，用于在系统各组件之间传递信息"""
    
    def __init__(self, 
                 msg_type: MessageType, 
                 content: Any, 
                 sender: str = "", 
                 receiver: str = "", 
                 metadata: Optional[Dict[str, Any]] = None):
        """初始化消息
        
        Args:
            msg_type: 消息类型
            content: 消息内容
            sender: 发送者
            receiver: 接收者
            metadata: 元数据
        """
        self.msg_type = msg_type
        self.content = content
        self.sender = sender
        self.receiver = receiver
        self.metadata = metadata or {}
        self.timestamp = time.time()
        self.id = f"{int(self.timestamp * 1000)}_{sender}_{receiver}"
    
    def to_dict(self) -> Dict[str, Any]:
        """将消息转换为字典
        
        Returns:
            Dict[str, Any]: 消息字典
        """
        return {
            "id": self.id,
            "type": self.msg_type.name,
            "content": self.content,
            "sender": self.sender,
            "receiver": self.receiver,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }
    
    def to_json(self) -> str:
        """将消息转换为JSON字符串
        
        Returns:
            str: JSON字符串
        """
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """从字典创建消息
        
        Args:
            data: 消息字典
            
        Returns:
            Message: 消息实例
        """
        msg_type = MessageType[data["type"]]
        msg = cls(
            msg_type=msg_type,
            content=data["content"],
            sender=data.get("sender", ""),
            receiver=data.get("receiver", ""),
            metadata=data.get("metadata", {})
        )
        msg.id = data.get("id", msg.id)
        msg.timestamp = data.get("timestamp", msg.timestamp)
        return msg
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """从JSON字符串创建消息
        
        Args:
            json_str: JSON字符串
            
        Returns:
            Message: 消息实例
        """
        data = json.loads(json_str)
        return cls.from_dict(data)


class TextMessage(Message):
    """文本消息"""
    
    def __init__(self, text: str, sender: str = "", receiver: str = "", metadata: Optional[Dict[str, Any]] = None):
        """初始化文本消息
        
        Args:
            text: 文本内容
            sender: 发送者
            receiver: 接收者
            metadata: 元数据
        """
        super().__init__(MessageType.TEXT, text, sender, receiver, metadata)


class CommandMessage(Message):
    """命令消息"""
    
    def __init__(self, command: str, params: Optional[Dict[str, Any]] = None, 
                 sender: str = "", receiver: str = "", metadata: Optional[Dict[str, Any]] = None):
        """初始化命令消息
        
        Args:
            command: 命令名称
            params: 命令参数
            sender: 发送者
            receiver: 接收者
            metadata: 元数据
        """
        content = {
            "command": command,
            "params": params or {}
        }
        super().__init__(MessageType.COMMAND, content, sender, receiver, metadata)


class EventMessage(Message):
    """事件消息"""
    
    def __init__(self, event: str, data: Optional[Dict[str, Any]] = None, 
                 sender: str = "", receiver: str = "", metadata: Optional[Dict[str, Any]] = None):
        """初始化事件消息
        
        Args:
            event: 事件名称
            data: 事件数据
            sender: 发送者
            receiver: 接收者
            metadata: 元数据
        """
        content = {
            "event": event,
            "data": data or {}
        }
        super().__init__(MessageType.EVENT, content, sender, receiver, metadata)


class EmotionMessage(Message):
    """情感消息"""
    
    def __init__(self, emotion: str, intensity: float = 0.5, 
                 sender: str = "", receiver: str = "", metadata: Optional[Dict[str, Any]] = None):
        """初始化情感消息
        
        Args:
            emotion: 情感类型
            intensity: 情感强度，范围0-1
            sender: 发送者
            receiver: 接收者
            metadata: 元数据
        """
        content = {
            "emotion": emotion,
            "intensity": intensity
        }
        super().__init__(MessageType.EMOTION, content, sender, receiver, metadata)


class MessageBus:
    """消息总线，用于在系统各组件之间传递消息"""
    
    def __init__(self):
        """初始化消息总线"""
        self.subscribers: Dict[MessageType, List[callable]] = {}
        for msg_type in MessageType:
            self.subscribers[msg_type] = []
        
        # 全局订阅者，接收所有类型的消息
        self.global_subscribers: List[callable] = []
        
        # 消息历史
        self.history: List[Message] = []
        self.max_history_size = 1000  # 最大历史消息数量
    
    def subscribe(self, msg_type: MessageType, callback: callable) -> None:
        """订阅指定类型的消息
        
        Args:
            msg_type: 消息类型
            callback: 回调函数，接收一个Message参数
        """
        if msg_type not in self.subscribers:
            self.subscribers[msg_type] = []
        self.subscribers[msg_type].append(callback)
    
    def subscribe_all(self, callback: callable) -> None:
        """订阅所有类型的消息
        
        Args:
            callback: 回调函数，接收一个Message参数
        """
        self.global_subscribers.append(callback)
    
    def unsubscribe(self, msg_type: MessageType, callback: callable) -> bool:
        """取消订阅指定类型的消息
        
        Args:
            msg_type: 消息类型
            callback: 回调函数
            
        Returns:
            bool: 是否成功取消订阅
        """
        if msg_type in self.subscribers and callback in self.subscribers[msg_type]:
            self.subscribers[msg_type].remove(callback)
            return True
        return False
    
    def unsubscribe_all(self, callback: callable) -> bool:
        """取消订阅所有类型的消息
        
        Args:
            callback: 回调函数
            
        Returns:
            bool: 是否成功取消订阅
        """
        if callback in self.global_subscribers:
            self.global_subscribers.remove(callback)
            return True
        return False
    
    def publish(self, message: Message) -> None:
        """发布消息
        
        Args:
            message: 要发布的消息
        """
        # 添加到历史记录
        self.history.append(message)
        if len(self.history) > self.max_history_size:
            self.history = self.history[-self.max_history_size:]
        
        # 通知全局订阅者
        for callback in self.global_subscribers:
            try:
                callback(message)
            except Exception as e:
                print(f"Error in global subscriber callback: {e}")
        
        # 通知特定类型的订阅者
        if message.msg_type in self.subscribers:
            for callback in self.subscribers[message.msg_type]:
                try:
                    callback(message)
                except Exception as e:
                    print(f"Error in subscriber callback for {message.msg_type}: {e}")
    
    def get_history(self, limit: Optional[int] = None) -> List[Message]:
        """获取历史消息
        
        Args:
            limit: 限制返回的消息数量，如果为None则返回所有历史消息
            
        Returns:
            List[Message]: 历史消息列表
        """
        if limit is None:
            return self.history.copy()
        return self.history[-limit:]
    
    def clear_history(self) -> None:
        """清空历史消息"""
        self.history = []


# 创建全局消息总线实例
message_bus = MessageBus()