from typing import Dict, Any, List, Optional, Callable, Generator, Union, Tuple, AsyncGenerator
import logging
import json
from utils.log_manager import LogManager
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
from .mem import MemoryManager
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
    """AI Virtual Companion Agent"""

    def __init__(self, agent_config=config.agent, stream_chat_callback=None, live2d_signals=None, message_signals=None):
        # Initialize logging
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('agent')
        
        # Basic components
        self.config = agent_config
        self.llm = self._initialize_llm(self.config.llm.platform, self.config.llm.llm_config)
        self.user = self.config.user
        self.stream_chat_callback = stream_chat_callback
        # 初始化记忆管理器
        self.memory_manager = MemoryManager()
        # 保持向后兼容性
        self.short_term_memory = self.memory_manager.short_term_memory
        self.short_term_memory.clear()
        self.persona = str(self.config.persona)
        self.short_term_memory.add_message(SystemMessage(content=self.persona))
        
        # Signal connections
        self.live2d_signals = live2d_signals or live2dsignal
        self.message_signals = message_signals  # Receives MessageSignals object
        
        # Record executed actions
        self.executed_actions = []
        self.current_user_input = ""
        
        # Initialize tools
        self.tools = self._create_tools()
        
        # Create agent
        self.agent = self._create_multi_action_agent()
        
        # Create agent executor
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=1,  # Reduce iterations since multi-action execution is used
            return_intermediate_steps=True,  # Return intermediate steps for debugging
        )
    
    class MultiActionOutputParser:
        """Custom multi-action output parser to ensure ShouldRespond tool is executed last"""
        
        def __init__(self, tools_list):
            self.tool_names = [tool.name.lower() for tool in tools_list]
        
        def parse(self, text: str) -> List[AgentAction] | AgentFinish:
            """Parse LLM output into multiple actions"""
            
            # Check for final answer marker
            if "FINAL ANSWER:" in text.upper():
                return AgentFinish(
                    return_values={"output": text.split(":")[-1].strip()},
                    log=text
                )
            
            actions = []
            should_respond_action = None
            
            # Match actions using regex
            action_pattern = r'Action:\s*(\w+)\s*Action Input:\s*([^\n]+)'
            matches = re.findall(action_pattern, text, re.IGNORECASE)
            
            # Collect all actions, placing ShouldRespond last
            for tool_name, tool_input in matches:
                tool_name_lower = tool_name.lower()
                if tool_name_lower == 'shouldrespond':
                    # Save ShouldRespond action to add later
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
            
            # Add ShouldRespond action last if it exists
            if should_respond_action:
                actions.append(should_respond_action)
            else:
                # Automatically add a default ShouldRespond action if not present
                actions.append(AgentAction(
                    tool="ShouldRespond",
                    tool_input="true",
                    log="Automatically added ShouldRespond: Default response required"
                ))
            
            return actions if actions else [
                AgentAction(
                    tool="ShouldRespond",
                    tool_input="true",
                    log="Only executing ShouldRespond step"
                )
            ]
    
    def _create_tools(self):
        """Create tool list"""
        tools = []
        
        # Expression setting tool
        if "set_expression" in self.config.actions.enabled:
            tools.append(Tool(
                name="SetExpression",
                func=lambda x: asyncio.run(self._set_expression(x)),
                description=f"Set Live2D expression. Format: expression. Available expressions: {', '.join(self.config.live2d.available_expression.keys())}"
            ))
        
        # Motion start tool
        if "start_motion" in self.config.actions.enabled:
            motion_desc = []
            for group, motions in self.config.live2d.available_motion.items():
                for i, desc in enumerate(motions):
                    motion_desc.append(f"{group}_{i}: {desc}")
            
            tools.append(Tool(
                name="StartMotion",
                func=lambda x: asyncio.run(self._start_motion(x)),
                description=f"Start Live2D motion. Format: group_index. Available motions: {'; '.join(motion_desc)}"
            ))
        
        # Web search tool
        if "web_search" in self.config.actions.enabled:
            wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
            tools.append(Tool(
                name="WebSearch",
                func=wikipedia.run,
                description="Search Wikipedia for information"
            ))

        # Emoji display tool
        if "show_emoji" in self.config.actions.enabled:
            emoji_list = self._get_available_emojis()
            tools.append(Tool(
                name="ShowEmoji",
                func=lambda x: asyncio.run(self._show_emoji(x)),
                description=f"Display emoji. Available emojis: {', '.join(emoji_list)}"
            ))
        
        # Audio playback tool
        if "play_audio" in self.config.actions.enabled:
            audio_list = self._get_available_audio()
            tools.append(Tool(
                name="PlayAudio",
                func=lambda x: asyncio.run(self._play_audio(x)),
                description=f"Play audio. Available audio: {', '.join(audio_list)}"
            ))
        

        tools.append(Tool(
            name="ShouldRespond",
            func=lambda x: asyncio.run(self._should_respond(x)),
            description="Tool to determine whether to respond to the user. Input true to respond, false otherwise. Format: true or false"
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
        """Set Live2D expression"""
        # Clean input, keep only the first line or word
        expression = expression.strip().split('\n')[0].split()[0]
        
        try:
            if expression in self.config.live2d.available_expression:
                # Randomly select an expression ID
                expression_id = random.choice(
                    self.config.live2d.available_expression[expression]
                )
                # Send signal to Live2D
                if self.live2d_signals:
                    self.live2d_signals.expression_requested.emit(expression_id)
                self.logger.info(f"Set expression: {expression} (ID: {expression_id})")
                return f"✓ Expression set: {expression}"
            else:
                available = list(self.config.live2d.available_expression.keys())
                return f"✗ Invalid expression: {expression}"
        except Exception as e:
            self.logger.error(f"Error setting expression: {e}")
            return f"✗ Failed to set expression"
    
    async def _start_motion(self, motion_input: str) -> str:
        """Start Live2D motion"""
        # Clean input
        motion_input = motion_input.strip().split('\n')[0].split()[0]
        self.logger.info(f"_start_motion input parameter {len(motion_input)}: {motion_input}")
        
        try:
            # Parse input format: group_index
            if '_' not in motion_input:
                return "✗ Invalid motion format"
            
            index_str = motion_input[-1]# 取最后一位的数字
            group = motion_input[:-2]
            index = int(index_str)
            
            # Validate motion group
            if group not in self.config.live2d.available_motion:
                return f"✗ Invalid motion group"
            
            # Validate index
            motions = self.config.live2d.available_motion[group]
            if index >= len(motions):
                return f"✗ Motion index out of range"
            
            # Send signal to Live2D
            if self.live2d_signals:
                self.live2d_signals.motion_requested.emit(group, index, 3)
            
            motion_desc = motions[index]
            self.logger.info(f"Start motion: {group}_{index} - {motion_desc}")
            return f"✓ Motion executed: {group}_{index}"
            
        except ValueError:
            return f"✗ Invalid motion format"
        except Exception as e:
            self.logger.error(f"Error starting motion: {e}")
            return f"✗ Failed to execute motion"
    
    async def _show_emoji(self, emoji_name: str) -> str:
        """Send emoji"""
        # Clean input
        emoji_name = emoji_name.strip().split('\n')[0].split()[0]
        self.logger.info(f"_show_emoji input parameter {len(emoji_name)}: {emoji_name}")
        
        try:
            available_emojis = self._get_available_emojis()
            if emoji_name in available_emojis:
                # Send emoji via MessageSignals
                if self.message_signals:
                    emoji_path = os.path.join(self.config.assets.assets_path, emoji_name)
                    self.message_signals.emoji_path.emit(emoji_path)
                self.logger.info(f"Send emoji: {emoji_name}")
                return f"✓ Emoji sent: {emoji_name}"
            else:
                return f"✗ Emoji not found"
        except Exception as e:
            self.logger.error(f"Error sending emoji: {e}")
            return f"✗ Failed to send emoji"

    async def _play_audio(self, audio_name: str) -> str:
        """Play audio"""
        # Clean input
        audio_name = audio_name.strip().split('\n')[0].split()[0]
        self.logger.info(f"_play_audio input parameter {len(audio_name)}: {audio_name}")
        
        try:
            available_audio = self._get_available_audio()
            if audio_name in available_audio:
                # Send audio via MessageSignals
                if self.message_signals:
                    audio_path = os.path.join(self.config.assets.assets_path, audio_name)
                    self.message_signals.audio_path.emit(audio_path)
                self.logger.info(f"Play audio: {audio_name}")
                return f"✓ Audio played: {audio_name}"
            else:
                return f"✗ Audio not found"
        except Exception as e:
            self.logger.error(f"Error playing audio: {e}")
            return f"✗ Failed to play audio"

    async def _should_respond(self, should_respond: str) -> str:
        """Wrapper function for ShouldRespond tool, used by Agent"""
        # Parse boolean input
        should_respond_clean = should_respond.strip().lower()
        
        if should_respond_clean in ['true', 'yes', '1']:
            # Mark ShouldRespond as called and response required
            return "✓ Response required"
        
        elif should_respond_clean in ['false', 'no', '0']:
            # Mark ShouldRespond as called but no response required
            return "✓ No response required"
        
        else:
            return "✗ Invalid boolean value, please use true or false"

    
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
                self.logger.error(f"llm连接失败，请检查配置或代理")
                return None
        except:
            self.logger.error(f"llm连接失败，请检查配置或代理")
            return None

    async def agent_chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """Asynchronous streaming agent chat generator - Executes multi-action Agent and returns streaming responses"""
        try:
            # Record current user input and clear action records
            self.current_user_input = user_input
            self.executed_actions = []
            common_chat_result = None  # Record result of ShouldRespond
            
            # Execute multi-action Agent
            try:
                # Directly use agent_executor's ainvoke method to execute multi-actions
                result = await self.agent_executor.ainvoke({"input": user_input})
                
                # Display execution results
                self.logger.info("📋 Multi-action execution details:")
                if 'intermediate_steps' in result:
                    for action, observation in result['intermediate_steps']:
                        self.logger.info(f"➤ {action.tool}:")
                        self.logger.info(f"  Input: {action.tool_input}")
                        self.logger.info(f"  Result: {observation}")
                        
                        # Record executed actions
                        self.executed_actions.append({
                            "type": "ToolEnd",
                            "name": action.tool,
                            "input": action.tool_input,
                            "output": observation
                        })
                        
                        # Check if it is the ShouldRespond tool
                        if action.tool == "ShouldRespond":
                            if "✓ Response required" in observation:
                                common_chat_result = True
                            elif "✓ No response required" in observation:
                                common_chat_result = False
                
                # Check if ShouldRespond was executed
                if common_chat_result is None:
                    # If ShouldRespond was not executed, log a warning and default to requiring a response
                    self.logger.warning("Agent did not execute ShouldRespond tool, defaulting to response required")
                    common_chat_result = True
                
                # If ShouldRespond returns True, execute language response
                if common_chat_result:
                    # Construct context with executed actions
                    self.logger.info(f"ShouldRespond result is True, executed actions: {self.executed_actions}")
                    
                    # Filter executed_actions, keeping only actually executed actions
                    filtered_actions = []
                    for action in self.executed_actions:
                        if action["name"] != "ShouldRespond":
                            if action.get("output", "").startswith("✓"):
                                filtered_actions.append({
                                    "name": action["name"],
                                    "result": action["output"]
                                })
                    
                    context_input = f"{self.user}: {user_input}\nYou have done these: {filtered_actions}\nRespond naturally"

                    # Create temporary messages for streaming generation
                    temp_messages = self.short_term_memory.messages.copy()
                    temp_messages.append(HumanMessage(content=context_input))
                    
                    # Use messages with action descriptions for streaming conversation
                    async for chunk in self.llm.astream(temp_messages):
                        if isinstance(chunk, AIMessageChunk):
                            if chunk.content and isinstance(chunk.content, str):
                                if self.stream_chat_callback:
                                    await self._safe_call_callback(chunk.content)
                                yield str(chunk.content)

            except Exception as e:
                error_msg = f"Error executing Agent tools: {str(e)}"
                self.logger.error(error_msg)
                yield error_msg
                
        except Exception as e:
            error_msg = f"Agent chat processing failed: {str(e)}"
            self.logger.error(error_msg)
            yield error_msg

    async def common_chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """Asynchronous streaming chat generator"""
        try:
            # 搜索相关记忆作为上下文
            memory_context = self.memory_manager.get_memory_context(user_input)
            
            # 添加用户消息到记忆系统
            self.memory_manager.add_message(HumanMessage(content=user_input))
            
            # 获取对话历史
            messages = self.memory_manager.get_recent_messages(10)
            
            # 如果有记忆上下文，在最新消息前插入上下文
            if memory_context.strip():
                context_msg = SystemMessage(content=f"相关记忆上下文:\n{memory_context}")
                messages = [context_msg] + messages

            full_response = ""
            async for chunk in self.llm.astream(messages):
                if isinstance(chunk, AIMessageChunk):
                    if chunk.content and isinstance(chunk.content, str):
                        full_response += chunk.content
                        if self.stream_chat_callback:
                            await self._safe_call_callback(chunk.content)
                        yield str(chunk.content)
            
            # 计算回复重要性并添加到记忆系统
            if full_response:
                importance = self._calculate_response_importance(user_input, full_response)
                self.memory_manager.add_message(AIMessage(content=full_response), importance)
                
        except Exception as e:
            error_msg = f"Chat processing failed: {str(e)}"
            self.logger.error(error_msg)
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
            self.logger.error(f"调用stream_chat_callback时出错: {e}")

    # ============ 系统状态查询 ============
    
    def _calculate_response_importance(self, user_input: str, response: str) -> float:
        """计算回复的重要性分数"""
        # 简单的重要性计算逻辑
        importance = 0.5  # 基础重要性
        
        # 根据用户输入长度调整
        if len(user_input) > 50:
            importance += 0.1
            
        # 根据回复长度调整
        if len(response) > 100:
            importance += 0.1
            
        # 检查是否包含重要关键词
        important_keywords = ['记住', '重要', '提醒', '不要忘记', '记录']
        for keyword in important_keywords:
            if keyword in user_input or keyword in response:
                importance += 0.2
                break
                
        return min(importance, 1.0)
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            "memory_stats": self.memory_manager.get_memory_stats() if hasattr(self, 'memory_manager') else {}
        }

