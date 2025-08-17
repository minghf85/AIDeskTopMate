from typing import Dict, Any, List, Optional, Callable, Generator, Union, Tuple, AsyncGenerator
import logging
from loguru import logger
import json
import time
from aiostream import stream
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from dotmap import DotMap
from Body.tlw import Live2DSignals
import toml
import os
import random
import asyncio
import inspect
config = DotMap(toml.load("config.toml"))

# 导入langchain相关组件
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, SystemMessage
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain.schema import BaseMemory
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain.agents import Agent, AgentExecutor, Tool, create_react_agent
from langchain.schema import AgentAction
from langchain.tools import BaseTool
from langchain_core.callbacks import BaseCallbackHandler, AsyncCallbackHandler
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter


live2dsignal = Live2DSignals()


class AIFE:
    """AI虚拟伙伴智能体"""

    def __init__(self, agent_config=config.agent, stream_chat_callback=None, live2d_signals=None, message_signals=None):
        # 基础组件
        self.config = agent_config
        self.llm = self._initialize_llm(self.config.llm.platform, self.config.llm.llm_config)
        self.stream_chat_callback = stream_chat_callback
        self.short_term_memory = ChatMessageHistory()
        self.short_term_memory.clear()
        self.persona = str(self.config.persona)
        self.short_term_memory.add_message(SystemMessage(content=self.persona))
        
        # 信号连接
        self.live2d_signals = live2d_signals or live2dsignal
        self.message_signals = message_signals  # 接收MessageSignals对象
        
        # 记录执行的动作
        self.executed_actions = []
        self.current_user_input = ""
        
        # 初始化工具
        self.tools = self._create_tools()
        
        # 创建agent
        self.agent = self._create_agent()
        
        # 创建agent executor
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=3
        )
    
    def _create_tools(self):
        """创建工具列表"""
        tools = []
        
        # 表情设置工具
        if "set_expression" in self.config.actions.enabled:
            tools.append(Tool(
                name="SetExpression",
                func=lambda x: asyncio.run(self._set_expression(x)),
                description=f"设置Live2D表情。可用表情: {', '.join(self.config.live2d.available_expression.keys())}"
            ))
        
        # 动作开始工具
        if "start_motion" in self.config.actions.enabled:
            motion_desc = []
            for group, motions in self.config.live2d.available_motion.items():
                for i, desc in enumerate(motions):
                    motion_desc.append(f"{group}_{i}: {desc}")
            
            tools.append(Tool(
                name="StartMotion",
                func=lambda x: asyncio.run(self._start_motion(x)),
                description=f"开始Live2D动作。格式: group_index。可用动作: {'; '.join(motion_desc)}"
            ))
        
        # 网页搜索工具
        if "web_search" in self.config.actions.enabled:
            wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
            tools.append(Tool(
                name="WebSearch",
                func=wikipedia.run,
                description="搜索Wikipedia获取信息"
            ))

        # 表情包显示工具
        if "show_emoji" in self.config.actions.enabled:
            emoji_list = self._get_available_emojis()
            tools.append(Tool(
                name="ShowEmoji",
                func=lambda x: asyncio.run(self._show_emoji(x)),
                description=f"显示表情包。可用表情包: {', '.join(emoji_list)}"
            ))
        
        # 音频播放工具
        if "play_audio" in self.config.actions.enabled:
            audio_list = self._get_available_audio()
            tools.append(Tool(
                name="PlayAudio",
                func=lambda x: asyncio.run(self._play_audio(x)),
                description=f"播放音效。可用音效: {', '.join(audio_list)}"
            ))
        
        # 通用聊天工具（可选执行）
        if "common_chat" in self.config.actions.enabled:
            tools.append(Tool(
                name="CommonChat",
                func=lambda x: asyncio.run(self._common_chat(x)),
                description="是否回应用户的工具。输入true表示需要回应用户，输入false表示不需要回应。格式: true 或 false"
            ))
        
        return tools
    
    def _create_agent(self):
        """创建ReAct agent"""
        # 准备工具信息
        tool_names = [tool.name for tool in self.tools]
        tool_descriptions = "\n".join([f"{tool.name}: {tool.description}" for tool in self.tools])
        
        # 创建prompt模板
        prompt_template = """你是一个AI live2D数字人。你的人设是{persona}
请根据{user}请求执行相应的动作。

你可以使用的工具:
{tools}

执行规则:
1. 首先分析用户需求，确定需要执行哪些动作（表情、动作、表情包、音效等）
2. 执行相应的动作工具，每个工具最多执行一次
3. 最后使用CommonChat工具决定是否需要语言回应用户：
   - 如果用户的请求已经通过动作完全表达了（如纯粹的表情、动作请求），使用CommonChat false
   - 如果需要语言回应或解释，使用CommonChat true
4. 每个Action Input只能是简单参数，不包含多行文本

请严格按照以下格式执行:
Action: 工具名称，必须是[{tool_names}]中的一个
Action Input: 工具的输入参数（只能是一个简单的单词或短语）

用户输入: {input}
{agent_scratchpad}"""
        
        prompt = PromptTemplate.from_template(prompt_template)
        
        # 创建agent
        return create_react_agent(
            self.llm,
            self.tools,
            prompt.partial(
                persona=self.config.persona,
                user=self.config.user,
                tools=tool_descriptions,
                tool_names=", ".join(tool_names)
            )
        )
    
    def _get_available_emojis(self):
        """获取可用的表情包列表"""
        assets_path = self.config.assets.assets_path
        if os.path.exists(assets_path):
            return [f for f in os.listdir(assets_path) 
                   if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        return []
    
    def _get_available_audio(self):
        """获取可用的音频列表"""
        assets_path = self.config.assets.assets_path
        if os.path.exists(assets_path):
            return [f for f in os.listdir(assets_path) 
                   if f.endswith(('.mp3', '.wav', '.ogg'))]
        return []
    
    async def _set_expression(self, expression: str) -> str:
        """设置Live2D表情"""
        # 清理输入参数，只保留第一行或第一个单词
        expression = expression.strip().split('\n')[0].split()[0]
        
        try:
            if expression in self.config.live2d.available_expression:
                # 随机选择一个表情ID
                expression_id = random.choice(
                    self.config.live2d.available_expression[expression]
                )
                # 发送信号到Live2D
                if self.live2d_signals:
                    self.live2d_signals.expression_requested.emit(expression_id)
                logger.info(f"设置表情: {expression} (ID: {expression_id})")
                return f"✓ 设置表情: {expression}"
            else:
                available = list(self.config.live2d.available_expression.keys())
                return f"✗ 无效表情: {expression}"
        except Exception as e:
            logger.error(f"设置表情时出错: {e}")
            return f"✗ 表情设置失败"
    
    async def _start_motion(self, motion_input: str) -> str:
        """开始Live2D动作"""
        # 清理输入参数
        motion_input = motion_input.strip().split('\n')[0].split()[0]
        logger.info(f"_start_motion传入参数{len(motion_input)}: {motion_input}")
        
        try:
            # 解析输入格式: group_index
            if '_' not in motion_input:
                return "✗ 动作格式错误"
            
            group, index_str = motion_input.split('_', 1)
            index = int(index_str)
            
            # 验证动作组
            if group not in self.config.live2d.available_motion:
                return f"✗ 无效动作组"
            
            # 验证索引
            motions = self.config.live2d.available_motion[group]
            if index >= len(motions):
                return f"✗ 动作索引超出范围"
            
            # 发送信号到Live2D
            if self.live2d_signals:
                self.live2d_signals.motion_requested.emit(group, index, 3)
            
            motion_desc = motions[index]
            logger.info(f"开始动作: {group}_{index} - {motion_desc}")
            return f"✓ 执行动作: {group}_{index}"
            
        except ValueError:
            return f"✗ 动作格式错误"
        except Exception as e:
            logger.error(f"开始动作时出错: {e}")
            return f"✗ 动作执行失败"
    
    async def _show_emoji(self, emoji_name: str) -> str:
        """发送表情包"""
        # 清理输入参数
        emoji_name = emoji_name.strip().split('\n')[0].split()[0]
        logger.info(f"_show_emoji传入参数{len(emoji_name)}: {emoji_name}")
        
        try:
            available_emojis = self._get_available_emojis()
            if emoji_name in available_emojis:
                # 通过MessageSignals发送表情包
                if self.message_signals:
                    emoji_path = os.path.join(self.config.assets.assets_path, emoji_name)
                    self.message_signals.emoji_path.emit(emoji_path)
                logger.info(f"发送表情包: {emoji_name}")
                return f"✓ 发送表情包: {emoji_name}"
            else:
                return f"✗ 表情包不存在"
        except Exception as e:
            logger.error(f"发送表情包时出错: {e}")
            return f"✗ 表情包发送失败"

    async def _play_audio(self, audio_name: str) -> str:
        """播放音效"""
        # 清理输入参数
        audio_name = audio_name.strip().split('\n')[0].split()[0]
        logger.info(f"_play_audio传入参数{len(audio_name)}: {audio_name}")
        
        try:
            available_audio = self._get_available_audio()
            if audio_name in available_audio:
                # 通过MessageSignals发送音频
                if self.message_signals:
                    audio_path = os.path.join(self.config.assets.assets_path, audio_name)
                    self.message_signals.audio_path.emit(audio_path)
                logger.info(f"播放音效: {audio_name}")
                return f"✓ 播放音效: {audio_name}"
            else:
                return f"✗ 音效不存在"
        except Exception as e:
            logger.error(f"播放音效时出错: {e}")
            return f"✗ 音效播放失败"

    async def _common_chat(self, should_respond: str) -> bool|str:
        """CommonChat工具的包装函数，用于Agent调用"""
        # 解析布尔值输入
        should_respond_clean = should_respond.strip().lower()
        
        if should_respond_clean in ['true', '是', 'yes', '1']:
            # 标记CommonChat已被调用且需要回应

            return True
        
        elif should_respond_clean in ['false', '否', 'no', '0']:
            # 标记CommonChat已被调用但不需要回应

            return False
        
        else:
            return "✗ 无效的布尔值，请使用 true 或 false"

    
    def get_available_actions(self) -> dict:
        """获取可用动作信息"""
        return {
            "expressions": list(self.config.live2d.available_expression.keys()),
            "motions": dict(self.config.live2d.available_motion),
            "emojis": self._get_available_emojis(),
            "audio": self._get_available_audio()
        }

    
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



    async def agent_chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """异步流式智能体聊天对话生成器 - 执行Agent工具调用并返回流式响应"""
        try:
            # 记录当前用户输入并清理动作记录
            self.current_user_input = user_input
            self.executed_actions = []
            common_chat_triggered = False  # 标记是否已触发CommonChat响应

            # 执行Agent工具调用
            try:
                # 执行agent进行工具调用和动作执行
                async for event in self.agent_executor.astream_events(
                    {"input": user_input},
                    version="v1"
                ):
                    # 如果已经触发CommonChat响应，跳过后续事件
                    if common_chat_triggered:
                        continue
                        
                    kind = event["event"]
                    if kind == "on_chat_model_stream":
                        content = event["data"]["chunk"].content
                        if content:
                            # Empty content in the context of OpenAI means
                            # that the model is asking for a tool to be invoked.
                            # So we only print non-empty content
                            print(content, end="|")
                    elif kind == "on_tool_start":
                        print("--")
                        print(
                            f"Starting tool: {event['name']} with inputs: {event['data'].get('input')}"
                        )
                        self.executed_actions.append({
                            "type": "ToolStart",
                            "name": event['name'],
                            "input": event['data'].get('input')
                        })
                    elif kind == "on_tool_end":
                        print(f"Done tool: {event['name']}")
                        print(f"Tool output was: {event['data'].get('output')}")
                        print("--")
                        self.executed_actions.append({
                            "type": "ToolEnd",
                            "name": event['name'],
                            "output": event['data'].get('output')
                        })
                        
                        # 检查是否是CommonChat工具且返回True
                        if (event['name'] == "CommonChat" and 
                            (event['data'].get('output') == True or event['data'].get('output') == "true")):
                            
                            common_chat_triggered = True  # 设置标记，防止重复处理
                            
                            # 构建包含执行动作的上下文
                            logger.info(f"选择调用CommonChat，已执行动作: {self.executed_actions}")
                            
                            # 过滤executed_actions，只保留实际执行的动作
                            filtered_actions = []
                            for action in self.executed_actions:
                                if action["type"] == "ToolEnd" and action["name"] != "CommonChat":
                                    if action.get("output", "").startswith("✓"):
                                        filtered_actions.append({
                                            "name": action["name"],
                                            "result": action["output"]
                                        })
                            
                            context_input = f"用户请求: {user_input}\n已执行的动作: {filtered_actions}\n请对此做出自然的回应。"

                            # 创建临时消息进行流式生成
                            temp_messages = self.short_term_memory.messages.copy()
                            temp_messages.append(HumanMessage(content=context_input))
                            
                            # 使用包含动作描述的消息进行流式对话
                            async for chunk in self.llm.astream(temp_messages):
                                if isinstance(chunk, AIMessageChunk):
                                    if chunk.content:
                                        if self.stream_chat_callback:
                                            await self._safe_call_callback(chunk.content)
                                        yield str(chunk.content)
                            
                            # 处理完毕，直接返回
                            return

            except Exception as e:
                error_msg = f"Agent工具执行出错: {str(e)}"
                logger.error(error_msg)
                yield error_msg
                
        except Exception as e:
            error_msg = f"智能体对话处理失败: {str(e)}"
            logger.error(error_msg)
            yield error_msg

    async def common_chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """异步流式聊天对话生成器"""
        try:
            # 添加到短期记忆
            self.short_term_memory.add_user_message(HumanMessage(content=user_input))

            async for chunk in self.llm.astream(self.short_term_memory.messages):
                if isinstance(chunk, AIMessageChunk):
                    if chunk.content:
                        if self.stream_chat_callback:
                            await self._safe_call_callback(chunk.content)
                        yield str(chunk.content)
                
        except Exception as e:
            error_msg = f"对话处理失败: {str(e)}"
            logging.error(error_msg)
            yield error_msg

    async def _safe_call_callback(self, content: str):
        """安全调用回调函数，自动检测是否为异步函数"""
        try:
            if self.stream_chat_callback:
                if inspect.iscoroutinefunction(self.stream_chat_callback):
                    # 如果是异步函数，使用await调用
                    await self.stream_chat_callback(content)
                else:
                    # 如果是同步函数，直接调用
                    self.stream_chat_callback(content)
        except Exception as e:
            logger.error(f"调用stream_chat_callback时出错: {e}")

    def sync_agent_chat(self, user_input: str):
        loop = asyncio.get_event_loop()
        a_iter = self.agent_chat(user_input)
        s_iter = stream.list(a_iter)  # 异步转同步
        return loop.run_until_complete(s_iter)

    def sync_common_chat(self, user_input: str):
        loop = asyncio.get_event_loop()
        a_iter = self.common_chat(user_input)
        s_iter = stream.list(a_iter)  # 异步转同步
        return loop.run_until_complete(s_iter)

    # ============ 系统状态查询 ============
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
        }

