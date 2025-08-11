from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import logging

class Action(ABC):
    """动作基类，所有具体动作都应该继承这个类"""
    
    def __init__(self, name: str, description: str = ""):
        """初始化动作
        
        Args:
            name: 动作名称
            description: 动作描述
        """
        self.name = name
        self.description = description
        self.logger = logging.getLogger(f"Action.{name}")
    
    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行动作的抽象方法，需要被子类实现
        
        Args:
            **kwargs: 动作执行所需的参数
            
        Returns:
            Dict[str, Any]: 动作执行的结果
        """
        pass
    
    def __str__(self) -> str:
        return f"Action({self.name}): {self.description}"


class ActionRegistry:
    """动作注册表，管理所有可用的动作"""
    
    def __init__(self):
        self._actions: Dict[str, Action] = {}
    
    def register(self, action: Action) -> None:
        """注册一个动作
        
        Args:
            action: 要注册的动作实例
        """
        if action.name in self._actions:
            logging.warning(f"Action {action.name} already registered, overwriting")
        self._actions[action.name] = action
        logging.info(f"Registered action: {action.name}")
    
    def get(self, name: str) -> Optional[Action]:
        """获取指定名称的动作
        
        Args:
            name: 动作名称
            
        Returns:
            Optional[Action]: 找到的动作实例，如果不存在则返回None
        """
        return self._actions.get(name)
    
    def execute(self, name: str, **kwargs) -> Dict[str, Any]:
        """执行指定名称的动作
        
        Args:
            name: 动作名称
            **kwargs: 传递给动作的参数
            
        Returns:
            Dict[str, Any]: 动作执行的结果
            
        Raises:
            KeyError: 如果指定名称的动作不存在
        """
        action = self.get(name)
        if action is None:
            raise KeyError(f"Action {name} not found")
        return action.execute(**kwargs)
    
    def list_actions(self) -> List[str]:
        """列出所有已注册的动作名称
        
        Returns:
            List[str]: 动作名称列表
        """
        return list(self._actions.keys())
    
    def get_descriptions(self) -> Dict[str, str]:
        """获取所有动作的描述
        
        Returns:
            Dict[str, str]: 动作名称到描述的映射
        """
        return {name: action.description for name, action in self._actions.items()}


# 一些基本动作的实现示例
class DialogAction(Action):
    """对话动作，用于与用户进行交互"""
    
    def __init__(self):
        super().__init__("dialog", "与用户进行对话交互")
    
    def execute(self, text: str, **kwargs) -> Dict[str, Any]:
        """执行对话动作
        
        Args:
            text: 对话内容
            **kwargs: 其他参数
            
        Returns:
            Dict[str, Any]: 对话结果
        """
        # 这里应该实现实际的对话逻辑，可能涉及TTS等
        self.logger.info(f"Dialog: {text}")
        return {"status": "success", "message": text}


class EmotionAction(Action):
    """情感动作，用于改变角色的情感状态"""
    
    def __init__(self):
        super().__init__("emotion", "改变角色的情感状态")
    
    def execute(self, emotion: str, intensity: float = 0.5, **kwargs) -> Dict[str, Any]:
        """执行情感动作
        
        Args:
            emotion: 情感类型，如happy, sad, angry等
            intensity: 情感强度，范围0-1
            **kwargs: 其他参数
            
        Returns:
            Dict[str, Any]: 情感变化结果
        """
        # 这里应该实现实际的情感变化逻辑
        self.logger.info(f"Emotion change: {emotion} (intensity: {intensity})")
        return {"status": "success", "emotion": emotion, "intensity": intensity}