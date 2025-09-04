from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_openai import OpenAIEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
import toml
import configparser
import os
import faiss
from utils.log_manager import LogManager
config = toml.load("config.toml")


class MemoryManager:
    """统一的记忆管理器，整合短期和长期记忆"""
    
    def __init__(self, agent_name: str = None, agent_user: str = None, config=config["agent"]["memory"]):
        """
        初始化记忆管理器
        
        Args:
            agent_name: agent的名称
            agent_user: agent的用户
            config: 记忆配置对象
        """
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('memory_manager')
        
        # 加载配置
        self.config = config
        self.agent_name = agent_name
        self.agent_user = agent_user
        
        # 设置路径结构
        if agent_name and agent_user:
            # 长期记忆路径：Head/Brain/Memory/agent_name/LongTermMemory
            self.long_term_memory_path = f"Head/Brain/Memory/{agent_name}/LongTermMemory"
            # 聊天记录路径：Head/Brain/Memory/agent_name/agent_user/
            self.chat_history_path = f"Head/Brain/Memory/{agent_name}/{agent_user}"
        else:
            # 使用默认路径或配置文件中的路径
            default_path = self.config.get('mem_path', 'Head/Brain/Memory')
            self.long_term_memory_path = default_path
            self.chat_history_path = default_path
        
        self.short_term_memory = ChatMessageHistory()
        self.short_term_memory.clear()
        self.long_term_memory = LongTermMemory(agent_name, agent_user, self.long_term_memory_path, config)
        
        # 初始化当前会话的聊天记录文件
        self._init_chat_session()
    
    def save_all_memories(self):
        """保存所有记忆（长期记忆和聊天历史）"""
        try:
            # 保存长期记忆
            self.long_term_memory.save_memory()
            self.logger.info("长期记忆已保存")
            
            # 保存聊天历史
            self.save_ChatHistory()
            self.logger.info("聊天历史已保存")
        except Exception as e:
            self.logger.error(f"保存记忆失败: {e}")
    
    def get_memory_context(self, query: str, max_memories: int = 3) -> str:
        """获取与查询相关的记忆上下文"""
        try:
            memories = self.long_term_memory.recall_memory_with_user(query, self.agent_user, max_memories)
            if not memories:
                return ""
            
            context_parts = []
            for memory in memories:
                content = memory.get('content', '')
                similarity = memory.get('similarity', 0)
                time_info = memory.get('metadata', {}).get('time', 'Unknown time')
                context_parts.append(f"[{time_info}] {content} (similarity: {similarity:.3f})")
            
            return "\n".join(context_parts)
        except Exception as e:
            self.logger.error(f"获取记忆上下文失败: {e}")
            return ""
    
    def get_recent_messages(self, count: int = 10) -> List[BaseMessage]:
        """获取最近的消息"""
        messages = self.short_term_memory.messages
        return messages[-count:] if len(messages) > count else messages
    
    def clear_short_term_memory(self):
        """清空短期记忆"""
        self.short_term_memory.clear()
        self.logger.info("短期记忆已清空")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        try:
            short_term_count = len(self.short_term_memory.messages)
            # 尝试获取长期记忆数量（如果向量存储支持）
            long_term_count = "Unknown"
            try:
                if hasattr(self.long_term_memory.vectorstore, 'index') and hasattr(self.long_term_memory.vectorstore.index, 'ntotal'):
                    long_term_count = self.long_term_memory.vectorstore.index.ntotal
            except:
                pass
            
            return {
                "short_term_messages": short_term_count,
                "long_term_memories": long_term_count,
                "agent_name": self.agent_name,
                "agent_user": self.agent_user,
                "long_term_path": self.long_term_memory_path,
                "chat_history_path": self.chat_history_path
            }
        except Exception as e:
            self.logger.error(f"获取记忆统计失败: {e}")
            return {}
    
    def _init_chat_session(self):
        """初始化当前聊天会话文件"""
        if not self.agent_name or not self.agent_user:
            self.current_chat_file = None
            return
        
        # 确保目录存在
        os.makedirs(self.chat_history_path, exist_ok=True)
        
        # 生成当前会话的文件名：会话开始时间.json
        session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"session_{session_timestamp}.json"
        self.current_chat_file = os.path.join(self.chat_history_path, filename)
        
        # 创建初始的聊天记录文件
        import json
        initial_data = {
            "agent_name": self.agent_name,
            "user_name": self.agent_user,
            "session_start_time": session_timestamp,
            "messages": []
        }
        
        with open(self.current_chat_file, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"新聊天会话已创建: {self.current_chat_file}")
    
    def save_ChatHistory(self):
        """保存聊天记录到当前会话文件"""
        if not self.current_chat_file:
            return
        
        # 将聊天记录转换为可序列化的格式
        chat_data = []
        for message in self.short_term_memory.messages:
            if isinstance(message, HumanMessage):
                chat_data.append({
                    "type": "human",
                    "content": message.content,
                    "timestamp": datetime.now().isoformat()
                })
            elif isinstance(message, AIMessage):
                chat_data.append({
                    "type": "ai",
                    "content": message.content,
                    "timestamp": datetime.now().isoformat()
                })
        
        # 读取现有文件并更新消息
        import json
        try:
            with open(self.current_chat_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 更新消息列表
            data["messages"] = chat_data
            data["last_updated"] = datetime.now().isoformat()
            
            # 写回文件
            with open(self.current_chat_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"聊天记录已更新到: {self.current_chat_file}")
        except Exception as e:
            self.logger.error(f"保存聊天记录失败: {e}")


class LongTermMemory:
    def __init__(self, agent_name: str, agent_user: str, storage_path: str, config):
        self.agent_name = agent_name
        self.agent_user = agent_user
        self.config = config
        self.storage_path = storage_path
        self.is_initialized = False
        
        # 初始化日志管理器
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('long_term_memory')
        
        try:
            self.embedding = self._init_embedding()
            self.vectorstore = self._init_vectorstore()
            self.logger.info(f"长期记忆初始化成功，存储路径: {self.storage_path}")
        except Exception as e:
            self.logger.error(f"长期记忆初始化失败: {e}")
            raise
    
    def _init_embedding(self):
        """初始化嵌入模型"""
        try:
            platform = self.config.get("platform", "")
            embedding_config = self.config.get("embedding_config", {})
            
            if platform == "openai":
                self.logger.info("初始化OpenAI嵌入模型")
                return OpenAIEmbeddings(**embedding_config)
            elif platform == "ollama":
                self.logger.info("初始化Ollama嵌入模型")
                return OllamaEmbeddings(**embedding_config)
            else:
                error_msg = f"不支持的嵌入平台: {platform}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
        except Exception as e:
            self.logger.error(f"嵌入模型初始化失败: {e}")
            raise
        
    def _init_vectorstore(self):
        """初始化向量数据库"""
        try:
            # 检查是否存在FAISS向量库文件
            index_file = os.path.join(self.storage_path, "index.faiss")
            pkl_file = os.path.join(self.storage_path, "index.pkl")
            
            # 如果FAISS相关文件存在，则加载现有的向量库
            if os.path.exists(index_file) and os.path.exists(pkl_file):
                self.logger.info(f"加载现有FAISS向量库: {self.storage_path}")
                vectorstore = FAISS.load_local(
                    self.storage_path, 
                    self.embedding, 
                    allow_dangerous_deserialization=True
                )
                self.is_initialized = True  # 已有数据库，标记为已初始化
                self.logger.info(f"成功加载现有向量库，包含 {vectorstore.index.ntotal} 条记录")
                return vectorstore
            else:
                # 创建新的向量库
                self.logger.info(f"创建新的FAISS向量库: {self.storage_path}")
                # 确保目录存在
                os.makedirs(self.storage_path, exist_ok=True)
                
                # 根据LangChain文档，使用正确的FAISS构造方法
                # 获取嵌入维度
                test_embedding = self.embedding.embed_query("test")
                dimension = len(test_embedding)
                self.logger.info(f"嵌入维度: {dimension}")
                
                # 创建FAISS索引
                index = faiss.IndexFlatL2(dimension)
                
                # 使用正确的构造函数创建FAISS向量存储
                vectorstore = FAISS(
                    embedding_function=self.embedding,
                    index=index,
                    docstore=InMemoryDocstore(),
                    index_to_docstore_id={}
                )
                self.logger.info("成功创建新的向量库")
                return vectorstore
                
        except Exception as e:
            self.logger.error(f"向量数据库初始化失败: {e}")
            raise
            
    def save_memory(self):
        """保存记忆"""
        try:
            if not hasattr(self, 'vectorstore') or self.vectorstore is None:
                self.logger.warning("向量存储未初始化，无法保存记忆")
                return
                
            self.vectorstore.save_local(self.storage_path)
            record_count = getattr(self.vectorstore.index, 'ntotal', 'Unknown')
            self.logger.info(f"记忆已保存到 {self.storage_path}，包含 {record_count} 条记录")
        except Exception as e:
            self.logger.error(f"保存记忆失败: {e}")
            raise

    def add_memory(self, memory: str, metadata: Optional[Dict[str, Any]] = None):
        """添加记忆"""
        try:
            if not memory or not memory.strip():
                self.logger.warning("尝试添加空记忆，已跳过")
                return
                
            # 在metadata中添加时间戳
            if metadata is None:
                metadata = {}
            metadata["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            metadata["agent_name"] = self.agent_name
            metadata["agent_user"] = self.agent_user
            
            # 向向量数据库添加记忆
            self.vectorstore.add_texts([memory], metadatas=[metadata])
            self.is_initialized = True
            
            self.logger.info(f"成功添加记忆: {memory[:50]}...")
            self.save_memory()
        except Exception as e:
            self.logger.error(f"添加记忆失败: {e}")
            raise  
    
    def search_memory(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索记忆"""
        try:
            if not query or not query.strip():
                self.logger.warning("搜索查询为空")
                return []
                
            if not self.is_initialized:
                self.logger.warning("向量存储未初始化，无法搜索记忆")
                return []
                
            # 搜索数据库
            results = self.vectorstore.similarity_search_with_score(query, k=top_k)
            formatted_results = [
                {
                    "content": doc.page_content, 
                    "metadata": doc.metadata, 
                    "similarity": 1 - score  # 转换为相似度分数
                } 
                for doc, score in results
            ]
            
            self.logger.info(f"搜索查询 '{query[:30]}...' 返回 {len(formatted_results)} 条结果")
            return formatted_results
            
        except Exception as e:
            self.logger.error(f"搜索记忆失败: {e}")
            return []
    
    def add_memory_with_user(self, memory: str, user: str):
        """添加带用户标识的记忆"""
        try:
            if not memory or not memory.strip():
                self.logger.warning("尝试添加空记忆，已跳过")
                return
                
            if not user or not user.strip():
                self.logger.warning("用户标识为空，使用默认用户")
                user = "default_user"
                
            # 向数据库添加记忆，在metadata中添加用户
            metadata = {"user": user}
            self.add_memory(memory, metadata)
            
            # 添加记忆后立即保存到磁盘
            self.save_memory()
            
            self.logger.info(f"成功为用户 {user} 添加记忆: {memory[:50]}...")
            
        except Exception as e:
            self.logger.error(f"为用户 {user} 添加记忆失败: {e}")
            raise
    
    def recall_memory_with_user(self, query: str, user: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """根据用户身份查询记忆"""
        try:
            if not query or not query.strip():
                self.logger.warning("查询为空")
                return []
                
            if not user or not user.strip():
                self.logger.warning("用户标识为空")
                return []
                
            # 搜索数据库
            results = self.search_memory(query, top_k * 2)  # 获取更多结果以便筛选
            
            # 筛选出用户记忆
            user_results = [
                doc for doc in results 
                if doc.get("metadata", {}).get("user") == user
            ][:top_k]  # 限制返回数量
            
            self.logger.info(f"为用户 {user} 查询 '{query[:30]}...' 返回 {len(user_results)} 条结果")
            return user_results
            
        except Exception as e:
            self.logger.error(f"为用户 {user} 查询记忆失败: {e}")
            return []



    def delete_memory(self, memory: str, metadata: Optional[Dict[str, Any]] = None):
        """删除单条记忆"""
        try:
            if not memory or not memory.strip():
                self.logger.warning("尝试删除空记忆，已跳过")
                return
                
            # 注意：FAISS不直接支持按内容删除，这里需要重新实现
            self.logger.warning("FAISS不支持直接删除操作，建议重建向量库")
            
        except Exception as e:
            self.logger.error(f"删除记忆失败: {e}")
            raise

    def delete_memory_with_user(self, user: str):
        """删除指定用户的所有记忆"""
        try:
            if not user or not user.strip():
                self.logger.warning("用户标识为空，无法删除记忆")
                return
                
            # 注意：FAISS不直接支持按元数据删除，这里需要重新实现
            self.logger.warning(f"FAISS不支持直接删除操作，无法删除用户 {user} 的记忆，建议重建向量库")
            
        except Exception as e:
            self.logger.error(f"删除用户 {user} 记忆失败: {e}")
            raise
    
    def get_memory_count(self) -> int:
        """获取记忆总数"""
        try:
            if hasattr(self.vectorstore, 'index') and hasattr(self.vectorstore.index, 'ntotal'):
                return self.vectorstore.index.ntotal
            return 0
        except Exception as e:
            self.logger.error(f"获取记忆数量失败: {e}")
            return 0
    
    def add_memories_batch(self, memories: List[str], user: str = None):
        """批量添加记忆"""
        try:
            if not memories:
                self.logger.warning("批量添加记忆列表为空")
                return
                
            valid_memories = [m for m in memories if m and m.strip()]
            if not valid_memories:
                self.logger.warning("批量添加记忆中没有有效内容")
                return
                
            metadatas = []
            for memory in valid_memories:
                metadata = {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "agent_name": self.agent_name,
                    "agent_user": self.agent_user
                }
                if user:
                    metadata["user"] = user
                metadatas.append(metadata)
            
            # 批量添加到向量数据库
            self.vectorstore.add_texts(valid_memories, metadatas=metadatas)
            self.is_initialized = True
            
            # 保存到磁盘
            self.save_memory()
            
            self.logger.info(f"成功批量添加 {len(valid_memories)} 条记忆")
            
        except Exception as e:
            self.logger.error(f"批量添加记忆失败: {e}")
            raise
    
    def rebuild_vectorstore(self):
        """重建向量存储（用于清理或重新组织数据）"""
        try:
            self.logger.info("开始重建向量存储")
            
            # 备份当前数据
            backup_path = f"{self.storage_path}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            if os.path.exists(self.storage_path):
                import shutil
                shutil.copytree(self.storage_path, backup_path)
                self.logger.info(f"已备份当前数据到: {backup_path}")
            
            # 重新初始化向量存储
            self.is_initialized = False
            self.vectorstore = self._init_vectorstore()
            
            self.logger.info("向量存储重建完成")
            
        except Exception as e:
            self.logger.error(f"重建向量存储失败: {e}")
            raise
            
