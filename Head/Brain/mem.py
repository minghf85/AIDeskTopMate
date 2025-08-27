from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
import toml
import configparser
import os
from utils.log_manager import LogManager
from .long_term_memory import LongTermMemory, MemoryEntry
config = toml.load("config.toml")


class MemoryManager:
    """统一的记忆管理器，整合短期和长期记忆"""
    
    def __init__(self, config=config["agent"]["memory"]):
        """
        初始化记忆管理器
        
        Args:
            config: 记忆配置对象
        """
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('memory_manager')
        
        # 加载配置
        self.config = config
        self.mem_path = self.config.get('mem_path', 'Head/Brain/Memory')
        
        # 修复：正确获取embedding配置
        self.embedding_config = self.config.get('embedding_config', {})
        
        # 调试信息：打印配置内容
        self.logger.info(f"Memory配置: {self.config}")
        self.logger.info(f"Embedding配置: {self.embedding_config}")
        
        # 初始化短期记忆
        self.short_term_memory = ChatMessageHistory()
        
        # 初始化长期记忆
        self._initialize_long_term_memory()
        
        # 记忆管理参数
        self.short_term_limit = 50  # 短期记忆最大条目数
        self.consolidation_threshold = 20  # 触发整理的短期记忆数量
        self.importance_threshold = 0.6  # 转入长期记忆的重要性阈值
        
        self.logger.info("记忆管理器初始化完成")
    
    def _initialize_long_term_memory(self):
        """初始化长期记忆系统"""
        try:
            # 初始化长期记忆
            self.long_term_memory = LongTermMemory(
                storage_path=self.mem_path,
                max_memories=1000,
                embedding_config=self.embedding_config
            )
            
            self.logger.info("长期记忆系统初始化成功")
            
        except Exception as e:
            self.logger.error(f"初始化长期记忆失败: {e}")
            self.long_term_memory = None
    
    def add_message(self, message: BaseMessage, importance: float = 0.5):
        """
        添加消息到记忆系统
        
        Args:
            message: 聊天消息
            importance: 重要性评分 (0.0-1.0)
        """
        # 添加到短期记忆
        self.short_term_memory.add_message(message)
        
        # 检查是否需要整理记忆
        if len(self.short_term_memory.messages) >= self.consolidation_threshold:
            self._consolidate_memories()
        
        # 如果重要性足够高，直接添加到长期记忆
        if importance >= self.importance_threshold and self.long_term_memory:
            self._add_to_long_term_memory(message, importance)
    
    def add_conversation_turn(self, human_message: str, ai_message: str, importance: float = 0.5):
        """
        添加一轮对话到记忆
        
        Args:
            human_message: 用户消息
            ai_message: AI回复
            importance: 重要性评分
        """
        # 添加用户消息
        self.add_message(HumanMessage(content=human_message), importance)
        
        # 添加AI回复
        self.add_message(AIMessage(content=ai_message), importance)
        
        self.logger.debug(f"添加对话轮次，重要性: {importance}")
    
    def _add_to_long_term_memory(self, message: BaseMessage, importance: float):
        """将消息添加到长期记忆"""
        try:
            if not self.long_term_memory:
                return
            
            # 确定记忆类型
            memory_type = "conversation"
            if isinstance(message, HumanMessage):
                memory_type = "user_input"
            elif isinstance(message, AIMessage):
                memory_type = "ai_response"
            
            # 添加到长期记忆
            memory_id = self.long_term_memory.add_memory(
                content=message.content,
                memory_type=memory_type,
                importance=importance,
                metadata={
                    "message_type": type(message).__name__,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            if memory_id:
                self.logger.debug(f"消息已添加到长期记忆: {memory_id}")
                
        except Exception as e:
            self.logger.error(f"添加到长期记忆失败: {e}")
    
    def _consolidate_memories(self):
        """整理记忆：将重要的短期记忆转移到长期记忆"""
        try:
            if not self.long_term_memory:
                return
            
            messages = self.short_term_memory.messages
            
            # 分析消息重要性并转移重要消息
            for message in messages[:-self.short_term_limit//2]:  # 保留最近的一半消息
                importance = self._calculate_message_importance(message)
                
                if importance >= self.importance_threshold:
                    self._add_to_long_term_memory(message, importance)
            
            # 清理旧的短期记忆
            self.short_term_memory.messages = messages[-self.short_term_limit//2:]
            
            self.logger.info(f"记忆整理完成，短期记忆保留 {len(self.short_term_memory.messages)} 条")
            
        except Exception as e:
            self.logger.error(f"记忆整理失败: {e}")
    
    def _calculate_message_importance(self, message: BaseMessage) -> float:
        """计算消息重要性"""
        content = message.content.lower()
        importance = 0.3  # 基础重要性
        
        # 长度因子
        if len(content) > 100:
            importance += 0.1
        
        # 关键词检测
        important_keywords = [
            '重要', '记住', '提醒', '问题', '错误', '帮助', 
            'important', 'remember', 'remind', 'problem', 'error', 'help'
        ]
        
        for keyword in important_keywords:
            if keyword in content:
                importance += 0.2
                break
        
        # 问号表示问题，可能比较重要
        if '?' in content or '？' in content:
            importance += 0.1
        
        return min(importance, 1.0)
    
    def search_relevant_memories(self, query: str, top_k: int = 5) -> List[MemoryEntry]:
        """
        搜索相关记忆
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            
        Returns:
            相关记忆条目列表
        """
        relevant_memories = []
        
        try:
            # 搜索长期记忆
            if self.long_term_memory:
                long_term_results = self.long_term_memory.search_memories(query, k=top_k)
                for entry, score in long_term_results:
                    relevant_memories.append(entry)
            
            self.logger.debug(f"搜索到 {len(relevant_memories)} 条相关记忆")
            
        except Exception as e:
            self.logger.error(f"搜索记忆失败: {e}")
        
        return relevant_memories[:top_k]
    
    def _search_short_term_memory(self, query: str, k: int = 3) -> List[str]:
        """搜索短期记忆"""
        query_lower = query.lower()
        relevant_messages = []
        
        for message in reversed(self.short_term_memory.messages):  # 从最新开始
            content = message.content.lower()
            
            # 简单的关键词匹配
            if any(word in content for word in query_lower.split()):
                relevant_messages.append(message.content)
                
                if len(relevant_messages) >= k:
                    break
        
        return relevant_messages
    
    def get_recent_messages(self, count: int = 10) -> List[BaseMessage]:
        """获取最近的消息"""
        return self.short_term_memory.messages[-count:]
    
    def get_memory_context(self, query: str = "", max_context_length: int = 2000) -> str:
        """
        获取记忆上下文用于对话
        
        Args:
            query: 查询文本，用于搜索相关记忆
            max_context_length: 最大上下文长度
            
        Returns:
            格式化的记忆上下文
        """
        context_parts = []
        
        # 添加相关记忆
        if query:
            relevant_memories = self.search_relevant_memories(query, k=3)
            if relevant_memories:
                context_parts.append("相关记忆:")
                for memory in relevant_memories:
                    context_parts.append(f"- {memory}")
                context_parts.append("")
        
        # 添加最近对话
        recent_messages = self.get_recent_messages(6)
        if recent_messages:
            context_parts.append("最近对话:")
            for message in recent_messages:
                role = "用户" if isinstance(message, HumanMessage) else "AI"
                context_parts.append(f"{role}: {message.content}")
        
        # 组合上下文并限制长度
        context = "\n".join(context_parts)
        if len(context) > max_context_length:
            context = context[:max_context_length] + "..."
        
        return context
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        stats = {
            "short_term_count": len(self.short_term_memory.messages),
            "long_term_available": self.long_term_memory is not None
        }
        
        if self.long_term_memory:
            long_term_stats = self.long_term_memory.get_memory_stats()
            stats.update({f"long_term_{k}": v for k, v in long_term_stats.items()})
        
        return stats
    
    def clear_short_term_memory(self):
        """清空短期记忆"""
        self.short_term_memory.clear()
        self.logger.info("短期记忆已清空")
    
    def force_consolidation(self):
        """强制执行记忆整理"""
        self._consolidate_memories()
        self.logger.info("强制记忆整理完成")
    
    def consolidate_memories(self):
        """公共接口：执行记忆整理"""
        self.force_consolidation()
