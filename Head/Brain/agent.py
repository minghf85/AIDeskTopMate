from typing import Dict, Any, List, Optional, Callable, Generator, Union
import logging
from abc import ABC, abstractmethod
from dotmap import DotMap
import time
import toml

config = DotMap(toml.load("config.toml"))
# 导入langchain相关组件
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory, ChatMessageHistory
from langchain.schema import BaseMemory
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

# 导入本地模块
from Actions.action import ActionRegistry, Action

# 定义AIFE类
class AIFE:
    def __init__(self, platform, llm_config, stream_chat_callback) -> None:
        self.llm = self._initialize_llm(platform, llm_config)
        self.short_term_memory = ChatMessageHistory()
        self.stream_chat_callback = stream_chat_callback

    def common_chat(self, user_input: str) -> Generator[Union[str, AIMessageChunk], None, None]:
        """流式聊天对话生成器
        
        Args:
            user_input: 用户输入文本
            
        Yields:
            每次生成的文本片段或消息对象
            
        Raises:
            RuntimeError: 当模型调用失败时抛出
        """
        try:
            # 创建消息并调用流式接口
            self.short_term_memory.add_user_message(HumanMessage(content=user_input))
            messages = self.short_term_memory.messages

            # 遍历流式响应
            for chunk in self.llm.stream(messages):
                if isinstance(chunk, AIMessageChunk):
                    self.stream_chat_callback(chunk.content)
                    yield chunk.content  # 产出文本内容
                else:
                    self.stream_chat_callback(str(chunk))
                    yield str(chunk)  # 兜底处理其他类型
            
        except Exception as e:
            raise RuntimeError(f"模型调用失败: {str(e)}") from e
        
    def _initialize_llm(self, platform: str, llm_config: Dict[str, Any]):
        if platform == "openai":
            return ChatOpenAI(**llm_config)
        elif platform == "ollama":
            return ChatOllama(**llm_config)
        else:
            raise ValueError(f"Unsupported platform: {platform}")
        