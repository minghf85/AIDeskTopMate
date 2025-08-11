from typing import Dict, Any, List, Optional, Callable
import logging
from abc import ABC, abstractmethod
from dotmap import DotMap
import toml

config = DotMap(toml.load("config.toml"))
# 导入langchain相关组件
try:
    from langchain.chains import LLMChain
    from langchain.prompts import PromptTemplate
    from langchain.memory import ConversationBufferMemory
    from langchain.schema import BaseMemory
except ImportError:
    logging.warning("Langchain not installed. Please install with 'pip install langchain'")

# 导入本地模块
from Actions.action import ActionRegistry, Action

class AIFE:




