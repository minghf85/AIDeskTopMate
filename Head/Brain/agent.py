from typing import Dict, Any, List, Optional, Callable, Generator, Union, Tuple
import logging
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from dotmap import DotMap
from Body.tlw import Live2DSignals
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


live2dsignal = Live2DSignals()

@dataclass
class Action:
    """智能体动作基类"""
    name: str
    description: str
    parameters: Dict[str, Any]
    
    def validate_parameters(self, params: Dict[str, Any]) -> bool:
        """验证输入参数是否符合要求"""
        required_params = set(self.parameters.keys())
        provided_params = set(params.keys())
        
        # 检查必填参数
        if required_params != provided_params:
            missing = required_params - provided_params
            raise ValueError(f"缺少必要参数: {missing}")
            
        # 类型检查 (简化版)
        for param, spec in self.parameters.items():
            if not isinstance(params[param], spec["type"]):
                raise TypeError(f"参数 '{param}' 需要 {spec['type']} 类型")
                
        # 自定义验证
        if hasattr(self, "_custom_validate"):
            return self._custom_validate(params)
            
        return True
    
    def execute(self, **kwargs) -> Any:
        """执行动作（子类必须实现）"""
        raise NotImplementedError("子类必须实现 execute 方法")
    
class SetExpression(Action):
    def __init__(self):
        # 动态加载配置
        config = DotMap(toml.load("config.toml"))
        available_expressions = list(config.live2d.available_expression.keys())
        super().__init__(
            name="set_expression",
            description="set your personal live2d expression",
            parameters={
                "expression": {
                    "type": str,
                    "description": "expression name",
                    "enum": available_expressions  # 可选值限制
                }
            }
        )
    
    def _custom_validate(self, params: Dict[str, Any]) -> bool:
        """自定义验证逻辑"""
        if params["expression"] not in self.parameters["expression"]["enum"]:
            raise ValueError(
                f"Not a valid expression: {self.parameters['expression']['enum']}"
            )
        return True
    
    def execute(self, expression: str) -> str:
        """执行表情设置"""
        live2dsignal.expression_requested.emit(expression)
        return f"expression has been set: {expression}"
    
class StartMotion(Action):
    """开始Live2D动作的动作类"""
    def __init__(self):
        # 动态加载配置
        config = DotMap(toml.load("config.toml"))
        self.motion_groups = config.live2d.available_motion
        
        # 构建动作描述字典
        motion_descriptions = {}
        for group, descriptions in self.motion_groups.items():
            for idx, desc in enumerate(descriptions):
                motion_descriptions[f"{group}_{idx}"] = desc
                
        super().__init__(
            name="start_motion",
            description="start a live2d motion by specifying the motion group and index",
            parameters={
                "motion_name": {
                    "type": str,
                    "description": "motion name in format 'group_index'",
                    "enum": list(motion_descriptions.keys()),  # 可用动作列表
                    "descriptions": motion_descriptions  # 动作描述字典
                }
            }
        )

    def _custom_validate(self, params: Dict[str, Any]) -> bool:
        """自定义验证逻辑"""
        motion_name = params["motion_name"]
        if motion_name not in self.parameters["motion_name"]["enum"]:
            raise ValueError(
                f"Invalid motion: {motion_name}. Available motions: {self.parameters['motion_name']['enum']}"
            )
        return True
    
    def execute(self, motion_name: str) -> str:
        """执行动作
        参数格式: 'group_index', 例如 'idle_0', 'Tapbody_1' 等
        """
        try:
            group, index = motion_name.split('_')
            index = int(index)
            
            # 验证动作组和索引是否有效
            if group not in self.motion_groups:
                return f"Invalid motion group: {group}"
            if index >= len(self.motion_groups[group]):
                return f"Invalid motion index {index} for group {group}"
            
            # 发送动作信号
            live2dsignal.motion_requested.emit(group, index, 3)
            
            # 返回执行结果描述
            description = self.parameters["motion_name"]["descriptions"][motion_name]
            return f"Motion executed: {group} {index} - {description}"
            
        except ValueError:
            return f"Invalid motion format: {motion_name}. Expected format: 'group_index'"
        except Exception as e:
            return f"Error executing motion: {str(e)}"

class AIFE:
    """AI虚拟伙伴智能体"""

    def __init__(self, agent_config=config.agent, stream_chat_callback=None):
        # 基础组件
        self.config = agent_config
        self.llm = self._initialize_llm(self.config.llm.platform, self.config.llm.llm_config)
        self.stream_chat_callback = stream_chat_callback
        self.short_term_memory = ChatMessageHistory()
        self.short_term_memory.clear()
        self.system_prompt = str(self.config.prompt)
        self.short_term_memory.add_message(SystemMessage(content=self.system_prompt))
        
        # 初始化智能体（延迟初始化，在第一次调用agent_chat时进行）
        # self._init_agent()

    
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

    def _init_agent(self):
        """初始化智能体"""
        # 初始化Action实例
        self.set_expression_action = SetExpression()
        self.start_motion_action = StartMotion()
        
        # 创建langchain工具
        self.tools = [
            Tool(
                name=self.set_expression_action.name,
                description=self.set_expression_action.description,
                func=self._execute_set_expression
            ),
            Tool(
                name=self.start_motion_action.name,
                description=self.start_motion_action.description,
                func=self._execute_start_motion
            )
        ]
        
        # 格式化可用的表情和动作信息
        expressions = list(self.set_expression_action.parameters["expression"]["enum"])
        motions_info = []
        for motion_name, desc in self.start_motion_action.parameters["motion_name"]["descriptions"].items():
            motions_info.append(f"{motion_name}: {desc}")
        
        # 创建适合create_react_agent的提示模板
        template = f"""{self.system_prompt}

You can use the following tools to control the Live2D character:
1. set_expression: Set facial expression, parameter is expression (name of expression)
2. start_motion: Play motion, parameter is motion_name (format: group_index, e.g., idle_0)

Available expressions: {", ".join(expressions)}
Available motions: {"; ".join(motions_info)}

When the user wants you to express emotions or perform actions, please use the appropriate tool(Every tool can only be used once).

TOOLS:
------

You have access to the following tools:

{{tools}}

To use a tool, please use the following format:

```
Thought: Do I need to use a tool? Yes
Action: the action to take, should be one of [{{tool_names}}]
Action Input: the input to the action
Observation: the result of the action
```

When you have a response to say to the Human, or if you do not need to use a tool, you MUST use the format:

```
Thought: Do I need to use a tool? No
Final Answer: [your response here]
```

Begin!

{{chat_history}}
Question: {{input}}
Thought: {{agent_scratchpad}}"""

        # 创建PromptTemplate
        self.agent_prompt = PromptTemplate.from_template(template)
        
        # 创建智能体
        self.agent = create_react_agent(self.llm, self.tools, self.agent_prompt)
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=3
        )

    def _execute_set_expression(self, expression: str) -> str:
        """执行设置表情的工具函数"""
        try:
            self.set_expression_action.validate_parameters({"expression": expression})
            return self.set_expression_action.execute(expression=expression)
        except Exception as e:
            return f"设置表情失败: {str(e)}"
    
    def _execute_start_motion(self, motion_name: str) -> str:
        """执行开始动作的工具函数"""
        try:
            self.start_motion_action.validate_parameters({"motion_name": motion_name})
            return self.start_motion_action.execute(motion_name=motion_name)
        except Exception as e:
            return f"执行动作失败: {str(e)}"

    def agent_chat(self, user_input: str) -> Generator[str, None, None]:
        """智能体聊天对话生成器"""
        try:
            # 初始化智能体（如果还没有初始化）
            if not hasattr(self, 'agent_executor'):
                self._init_agent()
            
            # 添加用户消息到短期记忆
            self.short_term_memory.add_user_message(HumanMessage(content=user_input))
            
            # 准备智能体输入
            agent_input = {
                "input": user_input,
                "chat_history": self.short_term_memory.messages
            }
            
            # 执行智能体
            result = self.agent_executor.invoke(agent_input)
            
            # 获取最终输出
            final_output = result.get("output", "Sorry, I cannot process this request.")
            
            
            # 逐字符输出以模拟流式效果
            for char in final_output:
                            # 流式输出结果
                if self.stream_chat_callback:
                    self.stream_chat_callback(char)
                yield char
                time.sleep(0.001)  # 小延迟以模拟打字效果
                
        except Exception as e:
            error_msg = f"智能体对话处理失败: {str(e)}"
            logging.error(error_msg)
            yield error_msg

    def common_chat(self, user_input: str) -> Generator[str, None, None]:
        """流式聊天对话生成器"""
        try:
            # 添加到短期记忆
            self.short_term_memory.add_user_message(HumanMessage(content=user_input))
            print(self.short_term_memory.messages)

            for chunk in self.llm.stream(self.short_term_memory.messages):
                if isinstance(chunk, AIMessageChunk):
                    if chunk.content:
                        if self.stream_chat_callback:
                            self.stream_chat_callback(chunk.content)
                        yield str(chunk.content)
                
        except Exception as e:
            error_msg = f"对话处理失败: {str(e)}"
            logging.error(error_msg)
            yield error_msg

    # ============ 系统状态查询 ============
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
        }

