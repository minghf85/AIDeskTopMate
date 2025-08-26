import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import threading
import time
from utils.log_manager import LogManager


@dataclass
class ConversationEntry:
    """对话条目数据类"""
    timestamp: str
    user_message: str
    ai_response: str
    session_id: str = "default"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationEntry':
        return cls(**data)


class JSONMemoryStorage:
    """基于JSON的简单记忆存储系统"""
    
    def __init__(self, storage_path: str = "memory_storage.json", max_entries: int = 1000):
        self.storage_path = storage_path
        self.max_entries = max_entries
        self.conversations: List[ConversationEntry] = []
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('memory')
        self._lock = threading.Lock()
        
        # 加载现有记忆
        self.load_memory()
    
    def add_conversation(self, user_message: str, ai_response: str, session_id: str = "default") -> None:
        """添加对话到记忆中"""
        with self._lock:
            entry = ConversationEntry(
                timestamp=datetime.now().isoformat(),
                user_message=user_message,
                ai_response=ai_response,
                session_id=session_id
            )
            
            self.conversations.append(entry)
            
            # 如果超过最大条目数，删除最旧的记录
            if len(self.conversations) > self.max_entries:
                self.conversations = self.conversations[-self.max_entries:]
            
            # 自动保存
            self.save_memory()
            self.logger.info(f"Added conversation entry: {user_message[:50]}...")
    
    def get_recent_conversations(self, count: int = 10, session_id: str = "default") -> List[ConversationEntry]:
        """获取最近的对话记录"""
        with self._lock:
            # 过滤指定session的对话
            session_conversations = [conv for conv in self.conversations if conv.session_id == session_id]
            return session_conversations[-count:] if session_conversations else []
    
    def get_conversations_by_timerange(self, hours: int = 24, session_id: str = "default") -> List[ConversationEntry]:
        """获取指定时间范围内的对话记录"""
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            recent_conversations = []
            
            for conv in self.conversations:
                if conv.session_id == session_id:
                    conv_time = datetime.fromisoformat(conv.timestamp)
                    if conv_time >= cutoff_time:
                        recent_conversations.append(conv)
            
            return recent_conversations
    
    def search_conversations(self, keyword: str, session_id: str = "default") -> List[ConversationEntry]:
        """搜索包含关键词的对话"""
        with self._lock:
            results = []
            for conv in self.conversations:
                if conv.session_id == session_id:
                    if (keyword.lower() in conv.user_message.lower() or 
                        keyword.lower() in conv.ai_response.lower()):
                        results.append(conv)
            return results
    
    def save_memory(self) -> bool:
        """保存记忆到JSON文件"""
        try:
            with self._lock:
                data = {
                    "conversations": [conv.to_dict() for conv in self.conversations],
                    "last_updated": datetime.now().isoformat()
                }
                
                with open(self.storage_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                self.logger.debug(f"Memory saved to {self.storage_path}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to save memory: {e}")
            return False
    
    def load_memory(self) -> bool:
        """从JSON文件加载记忆"""
        try:
            if not os.path.exists(self.storage_path):
                self.logger.info(f"Memory file {self.storage_path} not found, starting with empty memory")
                return True
            
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.conversations = [ConversationEntry.from_dict(conv_data) 
                                for conv_data in data.get("conversations", [])]
            
            self.logger.info(f"Loaded {len(self.conversations)} conversations from memory")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load memory: {e}")
            self.conversations = []  # 重置为空列表
            return False
    
    def clear_memory(self, session_id: Optional[str] = None) -> None:
        """清除记忆"""
        with self._lock:
            if session_id:
                # 只清除指定session的记忆
                self.conversations = [conv for conv in self.conversations if conv.session_id != session_id]
                self.logger.info(f"Cleared memory for session: {session_id}")
            else:
                # 清除所有记忆
                self.conversations = []
                self.logger.info("Cleared all memory")
            
            self.save_memory()
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        with self._lock:
            sessions = set(conv.session_id for conv in self.conversations)
            return {
                "total_conversations": len(self.conversations),
                "sessions": list(sessions),
                "storage_path": self.storage_path,
                "last_conversation": self.conversations[-1].timestamp if self.conversations else None
            }


class ProactiveDialogue:
    """主动对话管理器"""
    
    def __init__(self, idle_threshold_minutes: int = 30, check_interval_seconds: int = 60):
        self.idle_threshold = timedelta(minutes=idle_threshold_minutes)
        self.check_interval = check_interval_seconds
        self.last_user_activity = datetime.now()
        self.is_running = False
        self.thread = None
        self.proactive_callback = None
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('proactive')
        self._lock = threading.Lock()
        
        # 主动对话的候选消息
        self.proactive_messages = [
            "你还在吗？有什么我可以帮助你的吗？",
            "好久没有聊天了，最近怎么样？",
            "我在这里等你哦，有什么想聊的吗？",
            "要不要听个笑话放松一下？",
            "今天过得怎么样？想分享什么吗？",
            "我想你了，快来和我聊天吧！",
            "有什么新鲜事想告诉我吗？",
            "要不要我给你讲个故事？"
        ]
    
    def update_user_activity(self) -> None:
        """更新用户活动时间"""
        with self._lock:
            self.last_user_activity = datetime.now()
            self.logger.debug("User activity updated")
    
    def set_proactive_callback(self, callback) -> None:
        """设置主动对话回调函数"""
        self.proactive_callback = callback
        self.logger.info("Proactive callback set")
    
    def start_monitoring(self) -> None:
        """开始监控用户活动"""
        if self.is_running:
            self.logger.warning("Proactive monitoring already running")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        self.logger.info(f"Started proactive monitoring (threshold: {self.idle_threshold})")
    
    def stop_monitoring(self) -> None:
        """停止监控"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("Stopped proactive monitoring")
    
    def _monitor_loop(self) -> None:
        """监控循环"""
        while self.is_running:
            try:
                with self._lock:
                    time_since_activity = datetime.now() - self.last_user_activity
                
                if time_since_activity >= self.idle_threshold:
                    self._trigger_proactive_dialogue()
                    # 重置活动时间，避免频繁触发
                    with self._lock:
                        self.last_user_activity = datetime.now()
                
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"Error in proactive monitoring loop: {e}")
                time.sleep(self.check_interval)
    
    def _trigger_proactive_dialogue(self) -> None:
        """触发主动对话"""
        if self.proactive_callback:
            import random
            message = random.choice(self.proactive_messages)
            self.logger.info(f"Triggering proactive dialogue: {message}")
            try:
                self.proactive_callback(message)
            except Exception as e:
                self.logger.error(f"Error in proactive callback: {e}")
        else:
            self.logger.warning("No proactive callback set")
    
    def add_proactive_message(self, message: str) -> None:
        """添加自定义主动对话消息"""
        self.proactive_messages.append(message)
        self.logger.info(f"Added proactive message: {message}")
    
    def get_status(self) -> Dict[str, Any]:
        """获取主动对话状态"""
        with self._lock:
            return {
                "is_running": self.is_running,
                "last_activity": self.last_user_activity.isoformat(),
                "idle_threshold_minutes": self.idle_threshold.total_seconds() / 60,
                "check_interval_seconds": self.check_interval,
                "proactive_messages_count": len(self.proactive_messages)
            }