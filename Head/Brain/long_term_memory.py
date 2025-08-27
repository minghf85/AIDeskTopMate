from typing import List, Dict, Any, Optional, Tuple
import os
import json
import pickle
from datetime import datetime
from dataclasses import dataclass, asdict
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.messages import HumanMessage, AIMessage
from langchain.text_splitter import RecursiveCharacterTextSplitter
import logging
from utils.log_manager import LogManager


@dataclass
class MemoryEntry:
    """记忆条目数据结构"""
    id: str
    content: str
    timestamp: datetime
    memory_type: str  # "conversation", "event", "knowledge", "emotion"
    importance: float  # 0.0-1.0 重要性评分
    tags: List[str]  # 标签列表
    metadata: Dict[str, Any]  # 额外元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryEntry':
        """从字典创建记忆条目"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class LongTermMemory:
    """长期记忆管理类，基于FAISS向量数据库"""
    
    def __init__(self, 
                 storage_path: str = "Head/Brain/Memory",
                 max_memories: int = 10000,
                 embedding_config: Dict[str, Any] = None,
                 similarity_threshold: float = 0.7):
        """
        初始化长期记忆系统
        
        Args:
            storage_path: 记忆存储目录
            max_memories: 最大记忆条目数
            embedding_config: 嵌入模型配置
            similarity_threshold: 相似度阈值
        """
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('long_term_memory')
        
        # 初始化嵌入模型
        embedding_config = embedding_config or {}
        api_key = embedding_config.get('api_key', '')
        base_url = embedding_config.get('base_url', '')
        model = embedding_config.get('model', 'text-embedding-ada-002')
        
        # 检查必要的配置
        if not api_key:
            self.logger.warning("嵌入模型API密钥未配置，长期记忆功能可能无法正常工作")
        if not base_url:
            self.logger.warning("嵌入模型base_url未配置，将使用默认OpenAI端点")
            
        self.embeddings = OpenAIEmbeddings(
            api_key=api_key,
            base_url=base_url,
            model=model
        )
        
        # 测试嵌入模型连接并设置可用性标志
        self.vector_store_available = self._test_embedding_connection()
        
        self.memory_dir = storage_path
        self.max_memories = max_memories
        self.similarity_threshold = similarity_threshold
        
        # 确保目录存在
        os.makedirs(self.memory_dir, exist_ok=True)
        
        # 文件路径
        self.vector_store_path = os.path.join(self.memory_dir, "vector_store")
        self.metadata_path = os.path.join(self.memory_dir, "metadata.json")
        self.index_path = os.path.join(self.memory_dir, "memory_index.pkl")
        
        # 初始化组件
        self.vector_store: Optional[FAISS] = None
        self.memory_entries: Dict[str, MemoryEntry] = {}
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?"]
        )
        
        # 加载现有记忆
        self._load_memories()
        
        self.logger.info(f"长期记忆系统初始化完成，当前记忆条目数: {len(self.memory_entries)}")
    
    def _test_embedding_connection(self) -> bool:
        """测试嵌入模型连接"""
        try:
            # 尝试生成一个简单的嵌入向量来测试连接
            test_text = "测试连接"
            self.embeddings.embed_query(test_text)
            self.logger.info("嵌入模型连接测试成功")
            return True
        except Exception as e:
            self.logger.error(f"嵌入模型连接测试失败: {e}")
            self.logger.warning("长期记忆功能将受到影响，请检查API配置和网络连接")
            return False
    
    def _load_memories(self):
        """加载现有记忆数据"""
        try:
            # 仅在向量存储可用时加载向量存储
            if self.vector_store_available and os.path.exists(self.vector_store_path):
                try:
                    self.vector_store = FAISS.load_local(
                        self.vector_store_path, 
                        self.embeddings,
                        allow_dangerous_deserialization=True
                    )
                    self.logger.info("成功加载向量存储")
                except Exception as e:
                    self.logger.warning(f"加载向量存储失败: {e}，将使用关键词搜索")
                    self.vector_store_available = False
                    self.vector_store = None
            elif not self.vector_store_available:
                self.logger.info("向量存储不可用，跳过向量存储加载")
            
            # 加载元数据
            if os.path.exists(self.metadata_path):
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    for entry_data in metadata:
                        entry = MemoryEntry.from_dict(entry_data)
                        self.memory_entries[entry.id] = entry
                self.logger.info(f"成功加载 {len(self.memory_entries)} 条记忆元数据")
                
        except Exception as e:
            self.logger.error(f"加载记忆数据时出错: {e}")
            self.memory_entries = {}
            self.vector_store = None
    
    def _save_memories(self):
        """保存记忆数据"""
        try:
            # 仅在向量存储可用且存在时保存向量存储
            if self.vector_store_available and self.vector_store:
                try:
                    self.vector_store.save_local(self.vector_store_path)
                    self.logger.debug("向量存储已保存")
                except Exception as e:
                    self.logger.warning(f"保存向量存储失败: {e}")
            
            # 保存元数据
            metadata = [entry.to_dict() for entry in self.memory_entries.values()]
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"成功保存 {len(self.memory_entries)} 条记忆")
            
        except Exception as e:
            self.logger.error(f"保存记忆数据时出错: {e}")
    
    def add_memory(self, 
                   content: str, 
                   memory_type: str = "conversation",
                   importance: float = 0.5,
                   tags: List[str] = None,
                   metadata: Dict[str, Any] = None) -> str:
        """
        添加新记忆
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要性评分 (0.0-1.0)
            tags: 标签列表
            metadata: 额外元数据
            
        Returns:
            记忆ID
        """
        try:
            # 生成唯一ID
            memory_id = f"{memory_type}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # 创建记忆条目
            entry = MemoryEntry(
                id=memory_id,
                content=content,
                timestamp=datetime.now(),
                memory_type=memory_type,
                importance=importance,
                tags=tags or [],
                metadata=metadata or {}
            )
            
            # 文本分块
            chunks = self.text_splitter.split_text(content)
            
            # 创建或更新向量存储（仅在可用时进行）
            vector_store_success = False
            if self.vector_store_available:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if self.vector_store is None:
                            # 首次创建
                            texts = chunks
                            metadatas = [{"memory_id": memory_id, "chunk_index": i} 
                                       for i in range(len(chunks))]
                            self.vector_store = FAISS.from_texts(
                                texts, self.embeddings, metadatas=metadatas
                            )
                        else:
                            # 添加到现有存储
                            texts = chunks
                            metadatas = [{"memory_id": memory_id, "chunk_index": i} 
                                       for i in range(len(chunks))]
                            self.vector_store.add_texts(texts, metadatas=metadatas)
                        vector_store_success = True
                        break  # 成功则跳出重试循环
                    except Exception as embed_error:
                        if attempt < max_retries - 1:
                            self.logger.warning(f"嵌入API调用失败，第{attempt + 1}次重试: {embed_error}")
                            import time
                            time.sleep(2 ** attempt)  # 指数退避
                        else:
                            self.logger.error(f"嵌入API调用最终失败: {embed_error}")
                            self.logger.warning("将跳过向量存储，仅保存记忆元数据")
                            # 标记向量存储为不可用
                            self.vector_store_available = False
                            break
            else:
                self.logger.debug(f"向量存储不可用，跳过嵌入操作，仅保存记忆元数据: {memory_id}")
            
            # 存储记忆条目
            self.memory_entries[memory_id] = entry
            
            # 检查记忆数量限制
            self._manage_memory_capacity()
            
            # 保存到磁盘
            self._save_memories()
            
            if vector_store_success:
                self.logger.info(f"成功添加记忆: {memory_id}, 类型: {memory_type}, 重要性: {importance}")
            else:
                self.logger.warning(f"记忆已保存但向量搜索功能不可用: {memory_id}, 类型: {memory_type}, 重要性: {importance}")
            return memory_id
            
        except Exception as e:
            self.logger.error(f"添加记忆时出错: {e}")
            return ""
    
    def search_memories(self, 
                       query: str, 
                       k: int = 5,
                       memory_types: List[str] = None,
                       min_importance: float = 0.0) -> List[Tuple[MemoryEntry, float]]:
        """
        搜索相关记忆
        
        Args:
            query: 查询文本
            k: 返回结果数量
            memory_types: 限制记忆类型
            min_importance: 最小重要性阈值
            
        Returns:
            (记忆条目, 相似度分数) 的列表
        """
        try:
            if not self.vector_store:
                self.logger.warning("向量存储不可用，使用关键词搜索作为备用方案")
                return self._fallback_keyword_search(query, k, memory_types, min_importance)
            
            # 向量搜索
            docs_and_scores = self.vector_store.similarity_search_with_score(
                query, k=k*2  # 获取更多结果用于过滤
            )
            
            # 收集记忆ID和分数
            memory_scores = {}
            for doc, score in docs_and_scores:
                memory_id = doc.metadata.get("memory_id")
                if memory_id in self.memory_entries:
                    # 使用最高分数
                    if memory_id not in memory_scores or score > memory_scores[memory_id]:
                        memory_scores[memory_id] = score
            
            # 过滤和排序
            results = []
            for memory_id, score in memory_scores.items():
                entry = self.memory_entries[memory_id]
                
                # 应用过滤条件
                if memory_types and entry.memory_type not in memory_types:
                    continue
                if entry.importance < min_importance:
                    continue
                if score < self.similarity_threshold:
                    continue
                
                results.append((entry, score))
            
            # 按相似度排序
            results.sort(key=lambda x: x[1], reverse=True)
            
            self.logger.info(f"向量搜索查询: '{query}', 找到 {len(results)} 条相关记忆")
            return results[:k]
            
        except Exception as e:
            self.logger.error(f"向量搜索记忆时出错: {e}，尝试备用搜索方案")
            return self._fallback_keyword_search(query, k, memory_types, min_importance)
    
    def _fallback_keyword_search(self, query: str, k: int = 5, 
                                memory_types: List[str] = None, 
                                min_importance: float = 0.0) -> List[Tuple[MemoryEntry, float]]:
        """
        备用关键词搜索方案（当向量搜索不可用时使用）
        
        Args:
            query: 查询文本
            k: 返回结果数量
            memory_types: 限制记忆类型
            min_importance: 最小重要性阈值
            
        Returns:
            (记忆条目, 相似度分数) 的列表
        """
        try:
            query_lower = query.lower()
            query_words = set(query_lower.split())
            
            results = []
            for entry in self.memory_entries.values():
                # 应用过滤条件
                if memory_types and entry.memory_type not in memory_types:
                    continue
                if entry.importance < min_importance:
                    continue
                
                # 计算关键词匹配分数
                content_lower = entry.content.lower()
                content_words = set(content_lower.split())
                
                # 计算交集比例作为相似度分数
                if query_words:
                    intersection = query_words.intersection(content_words)
                    score = len(intersection) / len(query_words)
                    
                    # 如果有匹配的关键词，添加到结果中
                    if score > 0:
                        # 额外加分：完整短语匹配
                        if query_lower in content_lower:
                            score += 0.5
                        
                        # 重要性加权
                        score = score * (0.5 + 0.5 * entry.importance)
                        
                        results.append((entry, score))
            
            # 按分数排序
            results.sort(key=lambda x: x[1], reverse=True)
            
            self.logger.info(f"关键词搜索查询: '{query}', 找到 {len(results)} 条相关记忆")
            return results[:k]
            
        except Exception as e:
            self.logger.error(f"关键词搜索失败: {e}")
            return []
    
    def get_memory_by_id(self, memory_id: str) -> Optional[MemoryEntry]:
        """根据ID获取记忆"""
        return self.memory_entries.get(memory_id)
    
    def update_memory_importance(self, memory_id: str, importance: float):
        """更新记忆重要性"""
        if memory_id in self.memory_entries:
            self.memory_entries[memory_id].importance = importance
            self._save_memories()
            self.logger.info(f"更新记忆重要性: {memory_id} -> {importance}")
    
    def delete_memory(self, memory_id: str):
        """删除记忆（注意：向量存储中的数据不会被删除）"""
        if memory_id in self.memory_entries:
            del self.memory_entries[memory_id]
            self._save_memories()
            self.logger.info(f"删除记忆: {memory_id}")
    
    def _manage_memory_capacity(self):
        """管理记忆容量，删除旧的低重要性记忆"""
        if len(self.memory_entries) <= self.max_memories:
            return
        
        # 按重要性和时间排序
        sorted_memories = sorted(
            self.memory_entries.values(),
            key=lambda x: (x.importance, x.timestamp)
        )
        
        # 删除最不重要的记忆
        to_delete = len(self.memory_entries) - self.max_memories
        for i in range(to_delete):
            memory_id = sorted_memories[i].id
            del self.memory_entries[memory_id]
            self.logger.info(f"容量管理：删除记忆 {memory_id}")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        if not self.memory_entries:
            return {"total": 0}
        
        # 按类型统计
        type_counts = {}
        importance_sum = 0
        
        for entry in self.memory_entries.values():
            type_counts[entry.memory_type] = type_counts.get(entry.memory_type, 0) + 1
            importance_sum += entry.importance
        
        return {
            "total": len(self.memory_entries),
            "by_type": type_counts,
            "average_importance": importance_sum / len(self.memory_entries),
            "vector_store_exists": self.vector_store is not None
        }
    
    def clear_all_memories(self):
        """清空所有记忆（谨慎使用）"""
        self.memory_entries.clear()
        self.vector_store = None
        
        # 删除文件
        try:
            if os.path.exists(self.metadata_path):
                os.remove(self.metadata_path)
            if os.path.exists(self.vector_store_path):
                import shutil
                shutil.rmtree(self.vector_store_path)
        except Exception as e:
            self.logger.error(f"清理文件时出错: {e}")
        
        self.logger.warning("已清空所有长期记忆")
    
    def load_memories(self):
        """手动加载记忆数据（通常在初始化时自动调用）"""
        self._load_memories()
    
    def save_memories(self):
        """手动保存记忆数据"""
        self._save_memories()