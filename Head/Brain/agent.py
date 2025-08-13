from typing import Dict, Any, List, Optional, Callable, Generator, Union, Tuple
import logging
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from dotmap import DotMap
import toml

config = DotMap(toml.load("config.toml"))

# 导入langchain相关组件
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, SystemMessage
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain.schema import BaseMemory
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain.agents import Agent, AgentExecutor, Tool, create_react_agent
from langchain.schema import AgentAction
from langchain.tools import BaseTool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter





# ============ 行为系统 ============

class ActionType(Enum):
    """行为类型"""
    # # 细粒度行为
    # MOVE = "move"
    # ROTATE = "rotate"
    # SCALE = "scale"
    
    # # 粗粒度行为
    CHAT = "chat"
    # PLAY_SOUND = "play_sound"
    # WEB_SEARCH = "web_search"
    # SEND_IMAGE = "send_image"
    # SEND_EMOJI = "send_emoji"
    # READ_IMAGE = "read_image"
    # READ_VIDEO = "read_video"
    
    # 表情和动作
    EXPRESSION = "expression"
    MOTION = "motion"


# class SetExpressionTool(BaseTool):
#     """设置表情行为工具"""
#     name = "set_expression"
#     description = """设置Live2D角色的表情。
#     可用表情：
#     - happy: 开心表情 (F01, F02, F05)
#     - angry: 生气表情 (F03)
#     - sad: 悲伤表情 (F04)
#     - shock: 震惊表情 (F06)
#     - shy: 害羞表情 (F07)
#     - neutral: 中性表情 (F08)
    
#     参数格式：表情名称，如 'happy', 'sad', 'angry' 等"""
    
#     def __init__(self, body=None):
#         super().__init__()
#         self.body = body
#         self.available_expressions = config.live2d.available_expression

#     def _run(self, expression: str) -> str:
#         """执行设置表情行为"""
#         try:
#             if not self.body or not hasattr(self.body, 'SetExpression'):
#                 return "错误：body对象不存在或没有SetExpression方法"
            
#             # 检查表情是否可用
#             if expression not in self.available_expressions:
#                 available = ', '.join(self.available_expressions.keys())
#                 return f"错误：表情 '{expression}' 不可用。可用表情：{available}"
            
#             # 随机选择一个表情文件
#             import random
#             expression_files = self.available_expressions[expression]
#             selected_expression = random.choice(expression_files)
            
#             self.body.SetExpression(selected_expression)
#             logging.info(f"设置表情: {expression} -> {selected_expression}")
#             return f"成功设置表情为 {expression}"
            
#         except Exception as e:
#             error_msg = f"设置表情失败: {e}"
#             logging.error(error_msg)
#             return error_msg

# class StartMotionTool(BaseTool):
#     """开始动作行为工具"""
#     name = "start_motion"
#     description = """开始Live2D角色的动作。
#     可用动作组：
#     - idle: 闲置动作 (双手交叠放于腹前的礼仪站姿, 双手抱于胸前)
#     - Tapbody: 互动动作 (后退震惊下一跳, 讲解说明的姿势, 一手托腮在思考犹豫, 点头同意招待)
    
#     参数格式：动作组名称,索引 如 'idle,0' 或 'Tapbody,1'"""
    
#     def __init__(self, body=None):
#         super().__init__()
#         self.body = body
#         self.available_motions = config.live2d.available_motion

#     def _run(self, motion_param: str) -> str:
#         """执行开始动作行为"""
#         try:
#             if not self.body or not hasattr(self.body, 'StartMotion'):
#                 return "错误：body对象不存在或没有StartMotion方法"
            
#             # 解析参数
#             parts = motion_param.split(',')
#             if len(parts) != 2:
#                 return "错误：参数格式应为 '动作组,索引'，如 'idle,0'"
            
#             motion_group = parts[0].strip()
#             try:
#                 index = int(parts[1].strip())
#             except ValueError:
#                 return "错误：索引必须是数字"
            
#             # 检查动作组是否可用
#             if motion_group not in self.available_motions:
#                 available = ', '.join(self.available_motions.keys())
#                 return f"错误：动作组 '{motion_group}' 不可用。可用动作组：{available}"
            
#             # 检查索引是否有效
#             motion_descriptions = self.available_motions[motion_group]
#             if index < 0 or index >= len(motion_descriptions):
#                 return f"错误：索引 {index} 超出范围。动作组 '{motion_group}' 有 {len(motion_descriptions)} 个动作 (索引 0-{len(motion_descriptions)-1})"
            
#             self.body.StartMotion(motion_group, index)
#             description = motion_descriptions[index]
#             logging.info(f"开始动作: {motion_group}[{index}] - {description}")
#             return f"成功开始动作：{motion_group}[{index}] - {description}"
            
#         except Exception as e:
#             error_msg = f"开始动作失败: {e}"
#             logging.error(error_msg)
#             return error_msg


# ============ 主智能体类 ============

class AIFE:
    """AI虚拟伙伴智能体"""

    def __init__(self, agent_config=config.agent, body=None, stream_chat_callback=None):
        # 基础组件
        self.config = agent_config
        self.llm = self._initialize_llm(config.llm.platform, config.llm.llm_config)
        self.body = body
        self.stream_chat_callback = stream_chat_callback
        self.short_term_memory = ChatMessageHistory()
        
        # # LangChain工具
        # self.set_expression_tool = SetExpressionTool(body=body)
        # self.start_motion_tool = StartMotionTool(body=body)
        
        # self.tools = [
        #     self.set_expression_tool,
        #     self.start_motion_tool
        # ]
        
        # # 初始化Agent
        # self._init_agent()
        
        # 系统提示词
        self.system_prompt = self.config.agent.prompt
    
#     def update_body_reference(self, body):
#         """更新body引用"""
#         self.body = body
#         if hasattr(self, 'set_expression_tool'):
#             self.set_expression_tool.body = body
#         if hasattr(self, 'start_motion_tool'):
#             self.start_motion_tool.body = body
#         logging.info("已更新工具的body引用")
    
    def _initialize_llm(self, platform: str, llm_config: Dict[str, Any]):
        """初始化语言模型"""
        if platform == "openai":
            return ChatOpenAI(**llm_config)
        elif platform == "ollama":
            return ChatOllama(**llm_config)
        elif platform == "anthropic":
            return ChatAnthropic(**llm_config)
        else:
            raise ValueError(f"Unsupported platform: {platform}")
    
#     def _init_agent(self):
#         """初始化LangChain Agent"""
#         from langchain import hub
        
#         try:
#             # 使用ReAct提示模板
#             prompt_template = """你是一个AI助手，可以使用工具来控制Live2D角色的表情和动作。

# 你有以下工具可用：
# {tools}

# 使用以下格式：

# Question: 你需要回答的问题
# Thought: 你应该思考该做什么
# Action: 要采取的行动，应该是 [{tool_names}] 中的一个
# Action Input: 行动的输入
# Observation: 行动的结果
# ... (这个思考/行动/行动输入/观察过程可以重复N次)
# Thought: 我现在知道最终答案了
# Final Answer: 对原始输入问题的最终答案

# 开始！

# Question: {input}
# Thought: {agent_scratchpad}"""

#             from langchain.prompts import PromptTemplate
#             prompt = PromptTemplate.from_template(prompt_template)
            
#             self.agent = create_react_agent(
#                 llm=self.llm,
#                 tools=self.tools,
#                 prompt=prompt
#             )
#             self.agent_executor = AgentExecutor(
#                 agent=self.agent,
#                 tools=self.tools,
#                 verbose=True,
#                 max_iterations=5,
#                 early_stopping_method="generate",
#                 handle_parsing_errors=True
#             )
#             logging.info("Agent初始化成功")
#         except Exception as e:
#             logging.warning(f"无法创建Agent: {e}")
#             self.agent = None
#             self.agent_executor = None

#     def agent_chat(self, user_input: str) -> Generator[str, None, None]:
#         """能够规划执行动作，返回迭代消息"""
#         try:
#             if not self.agent_executor:
#                 yield "错误：Agent未正确初始化"
#                 return
            
#             # 添加到短期记忆
#             self.short_term_memory.add_user_message(HumanMessage(content=user_input))
            
#             # 构建增强的系统提示词，包含工具使用指导
#             enhanced_system_prompt = f"""{self.system_prompt}

# ## 工具使用指导

# 你可以使用以下工具来控制Live2D角色：

# 1. **set_expression**: 设置表情
#    - 可用表情：happy, angry, sad, shock, shy, neutral
#    - 使用方法：根据对话情绪选择合适的表情
#    - 例：当用户夸奖时使用 'happy'，当被批评时使用 'sad'

# 2. **start_motion**: 开始动作
#    - 可用动作组：idle, Tapbody
#    - 使用方法：动作组,索引 如 'idle,0' 或 'Tapbody,1'
#    - idle动作适合日常对话，Tapbody动作适合互动场景

# ## 使用原则：
# - 根据对话内容和情绪自然地使用表情和动作
# - 优先使用表情，动作作为补充
# - 保持角色的一致性和自然性
# - 在回复开始时就设置合适的表情或动作
# """

#             # 执行Agent
#             result = self.agent_executor.invoke({
#                 "input": user_input,
#                 "system_prompt": enhanced_system_prompt
#             })
            
#             # 流式返回结果
#             if isinstance(result, dict) and "output" in result:
#                 response = result["output"]
#                 # 添加AI回复到记忆
#                 self.short_term_memory.add_ai_message(AIMessage(content=response))
                
#                 # 分块返回响应
#                 words = response.split()
#                 current_chunk = ""
#                 for word in words:
#                     current_chunk += word + " "
#                     if len(current_chunk) >= 10:  # 每10个字符返回一次
#                         if self.stream_chat_callback:
#                             self.stream_chat_callback(current_chunk)
#                         yield current_chunk
#                         current_chunk = ""
                
#                 # 返回剩余内容
#                 if current_chunk:
#                     if self.stream_chat_callback:
#                         self.stream_chat_callback(current_chunk)
#                     yield current_chunk
#             else:
#                 error_msg = "Agent执行失败"
#                 logging.error(f"{error_msg}: {result}")
#                 yield error_msg
                
#         except Exception as e:
#             error_msg = f"Agent对话处理失败: {str(e)}"
#             logging.error(error_msg)
#             yield error_msg
    def common_chat(self, user_input: str) -> Generator[str, None, None]:
        """流式聊天对话生成器"""
        try:
            # 添加到短期记忆
            self.short_term_memory.add_user_message(HumanMessage(content=user_input))
            
            messages = [
                SystemMessage(content=self.system_prompt),
                *self.short_term_memory.messages
            ]
        
            for chunk in self.llm.stream(messages):
                if isinstance(chunk, AIMessageChunk):
                    if chunk.content:
                        if self.stream_chat_callback:
                            self.stream_chat_callback(chunk.content)
                        yield str(chunk.content)
                
        except Exception as e:
            error_msg = f"对话处理失败: {str(e)}"
            logging.error(error_msg)
            yield error_msg
    
    # # ============ 便捷方法 ============
    
    # def set_expression(self, expression: str) -> bool:
    #     """便捷方法：直接设置表情"""
    #     try:
    #         result = self.set_expression_tool._run(expression)
    #         return not result.startswith("错误")
    #     except Exception as e:
    #         logging.error(f"设置表情失败: {e}")
    #         return False
    
    # def start_motion(self, motion_group: str, index: int) -> bool:
    #     """便捷方法：直接开始动作"""
    #     try:
    #         motion_param = f"{motion_group},{index}"
    #         result = self.start_motion_tool._run(motion_param)
    #         return not result.startswith("错误")
    #     except Exception as e:
    #         logging.error(f"开始动作失败: {e}")
    #         return False
    
    # def get_available_expressions(self) -> Dict[str, List[str]]:
    #     """获取可用表情列表"""
    #     return dict(self.set_expression_tool.available_expressions)
    
    # def get_available_motions(self) -> Dict[str, List[str]]:
    #     """获取可用动作列表"""
    #     return dict(self.start_motion_tool.available_motions)


    # # ============ 主动对话系统 ============
    
    # def initiate_conversation(self) -> str:
    #     """主动发起对话"""
    #     try:
    #         greetings = [
    #             "你好！我是Neuro-sama，今天想聊什么呢？",
    #             "嗨！有什么有趣的事情要分享吗？",
    #             "Hello there! 准备好和我聊天了吗？",
    #             "哟！又见面了，今天过得怎么样？"
    #         ]
    #         import random
    #         greeting = random.choice(greetings)
            
    #         # 设置一个友好的表情
    #         if self.body and hasattr(self.body, 'SetExpression'):
    #             try:
    #                 self.body.SetExpression("F01")  # 设置开心表情
    #                 logging.info("主动对话时设置了开心表情")
    #             except Exception as e:
    #                 logging.warning(f"设置表情失败: {e}")
            
    #         return greeting
    #     except Exception as e:
    #         logging.error(f"主动对话生成失败: {e}")
    #         return "Hello! 很高兴见到你！"

    
    
    # ============ 系统状态查询 ============
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
        }
        
        