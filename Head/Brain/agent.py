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
from langchain.agents import Agent, AgentExecutor, Tool, create_react_agent, BaseMultiActionAgent
from langchain.schema import AgentAction, AgentFinish
from langchain.tools import BaseTool
from langchain_core.callbacks import BaseCallbackHandler, AsyncCallbackHandler
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.agents.agent import RunnableMultiActionAgent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_core.messages import BaseMessage
from langchain_core.agents import AgentAction as CoreAgentAction, AgentFinish as CoreAgentFinish
import re


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
        self.agent = self._create_multi_action_agent()
        
        # 创建agent executor
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=1,  # 减少迭代次数，因为使用多动作执行
            return_intermediate_steps=True,  # 返回中间步骤便于调试
        )
    
    class MultiActionOutputParser:
        """自定义多动作输出解析器，确保ShouldRespond工具最后执行"""
        
        def __init__(self, tools_list):
            self.tool_names = [tool.name.lower() for tool in tools_list]
        
        def parse(self, text: str) -> List[AgentAction] | AgentFinish:
            """解析LLM输出为多个动作"""
            
            # 检查是否包含结束标志
            if "FINAL ANSWER:" in text.upper() or "最终答案:" in text:
                return AgentFinish(
                    return_values={"output": text.split(":")[-1].strip()},
                    log=text
                )
            
            actions = []
            should_respond_action = None
            
            # 使用正则表达式匹配动作
            action_pattern = r'Action:\s*(\w+)\s*Action Input:\s*([^\n]+)'
            matches = re.findall(action_pattern, text, re.IGNORECASE)
            
            # 收集所有动作，将ShouldRespond放到最后
            for tool_name, tool_input in matches:
                tool_name_lower = tool_name.lower()
                if tool_name_lower == 'shouldrespond':
                    # 保存ShouldRespond动作，稍后添加到最后
                    should_respond_action = AgentAction(
                        tool="ShouldRespond",
                        tool_input=tool_input.strip(),
                        log=f"Action: ShouldRespond\nAction Input: {tool_input}"
                    )
                    continue
                if tool_name_lower in self.tool_names:
                    actions.append(AgentAction(
                        tool=tool_name,
                        tool_input=tool_input.strip(),
                        log=f"Action: {tool_name}\nAction Input: {tool_input}"
                    ))
            
            # 如果Agent输出了ShouldRespond，将其添加到最后
            if should_respond_action:
                actions.append(should_respond_action)
            else:
                # 如果Agent没有输出ShouldRespond，自动添加一个默认的
                actions.append(AgentAction(
                    tool="ShouldRespond",
                    tool_input="true",
                    log="自动添加的ShouldRespond: 默认需要回应"
                ))
            
            logger.info(f"计划执行的动作序列: {[a.tool for a in actions]}")
            return actions if actions else [
                AgentAction(
                    tool="ShouldRespond",
                    tool_input="true",
                    log="仅执行ShouldRespond步骤"
                )
            ]
    
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
        

        tools.append(Tool(
            name="ShouldRespond",
            func=lambda x: asyncio.run(self._should_respond(x)),
            description="是否回应用户的工具。输入true表示需要回应用户，输入false表示不需要回应。格式: true 或 false"
        ))
        
        return tools
    
    def _create_multi_action_agent(self):
        """创建多动作Runnable链"""
        
        # 创建prompt模板
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.config.decision_prompt),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad", optional=True)
        ])
        
        # 创建输出解析器
        output_parser = self.MultiActionOutputParser(self.tools)
        
        # 格式化函数
        def format_scratchpad(intermediate_steps: List[Tuple[AgentAction, str]]) -> List[BaseMessage]:
            """格式化中间步骤"""
            if not intermediate_steps:
                return []
                
            messages = []
            results = []
            for action, observation in intermediate_steps:
                results.append(f"{action.tool}: {observation}")
                messages.append(AIMessage(content="\n".join(results)))
            return messages
        
        # 创建Runnable链
        chain = (
            RunnablePassthrough.assign(
                agent_scratchpad=lambda x: format_scratchpad(x.get("intermediate_steps", []))
            )
            | prompt.partial(
                persona=self.config.persona,
                tools="\n".join([f"{tool.name}: {tool.description}" for tool in self.tools])
            )
            | self.llm
            | (lambda x: output_parser.parse(x.content))
        )
        
        # 创建RunnableMultiActionAgent
        return RunnableMultiActionAgent(
            runnable=chain,
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

    async def _should_respond(self, should_respond: str) -> str:
        """ShouldRespond工具的包装函数，用于Agent调用"""
        # 解析布尔值输入
        should_respond_clean = should_respond.strip().lower()
        
        if should_respond_clean in ['true', '是', 'yes', '1']:
            # 标记ShouldRespond已被调用且需要回应
            return "✓ 需要语言回应"
        
        elif should_respond_clean in ['false', '否', 'no', '0']:
            # 标记ShouldRespond已被调用但不需要回应
            return "✓ 不需要语言回应"
        
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
            llm =  ChatOpenAI(**llm_config)
        elif platform == "ollama":
            llm = ChatOllama(**llm_config)
        elif platform == "anthropic":
            llm = ChatAnthropic(**llm_config)
        else:
            raise ValueError(f"Unsupported platform: {platform}")
        
        # 测试连接
        try:
            test_response = llm.invoke("Hello!")
            if test_response:
                return llm
            else:
                logger.error(f"llm连接失败，请检查配置或代理")
                return None
        except:
            logger.error(f"llm连接失败，请检查配置或代理")
            return None

    async def agent_chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """异步流式智能体聊天对话生成器 - 执行多动作Agent并返回流式响应"""
        try:
            # 记录当前用户输入并清理动作记录
            self.current_user_input = user_input
            self.executed_actions = []
            common_chat_result = None  # 记录ShouldRespond的结果
            
            # 执行多动作Agent
            try:
                # 直接使用agent_executor的ainvoke方法执行多动作
                result = await self.agent_executor.ainvoke({"input": user_input})
                
                # 显示执行结果
                logger.info("📋 多动作执行详情:")
                if 'intermediate_steps' in result:
                    for action, observation in result['intermediate_steps']:
                        logger.info(f"➤ {action.tool}:")
                        logger.info(f"  输入: {action.tool_input}")
                        logger.info(f"  结果: {observation}")
                        
                        # 记录执行的动作
                        self.executed_actions.append({
                            "type": "ToolEnd",
                            "name": action.tool,
                            "input": action.tool_input,
                            "output": observation
                        })
                        
                        # 检查是否是ShouldRespond工具
                        if action.tool == "ShouldRespond":
                            if "✓ 需要语言回应" in observation:
                                common_chat_result = True
                            elif "✓ 不需要语言回应" in observation:
                                common_chat_result = False
                
                # 检查ShouldRespond是否被执行
                if common_chat_result is None:
                    # 如果没有执行ShouldRespond，记录警告并默认需要回应
                    logger.warning("Agent未执行ShouldRespond工具，默认需要语言回应")
                    common_chat_result = True
                
                # 如果ShouldRespond返回True，执行语言回应
                if common_chat_result:
                    # 构建包含执行动作的上下文
                    logger.info(f"ShouldRespond结果为True，已执行动作: {self.executed_actions}")
                    
                    # 过滤executed_actions，只保留实际执行的动作
                    filtered_actions = []
                    for action in self.executed_actions:
                        if action["name"] != "ShouldRespond":
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
                            if chunk.content and isinstance(chunk.content, str):
                                if self.stream_chat_callback:
                                    await self._safe_call_callback(chunk.content)
                                yield str(chunk.content)

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
                    if chunk.content and isinstance(chunk.content, str):
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

    # ============ 系统状态查询 ============
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
        }

