from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Generator, Union, Tuple, AsyncGenerator
from utils.log_manager import LogManager
from datetime import datetime
from dotmap import DotMap
from Body.tlw import Live2DSignals
from Head.Brain.feel import FeelState
import toml
import os
import random
import asyncio
import inspect
import win32gui
import win32process
import psutil
config = DotMap(toml.load("config.toml"))
user = config.agent.user
# Import langchain related components
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, SystemMessage
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_community.chat_message_histories import ChatMessageHistory
from .mem import MemoryManager
from langchain.agents import AgentExecutor, Tool
from langchain.schema import AgentAction, AgentFinish
from langchain.agents.agent import RunnableMultiActionAgent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_core.messages import BaseMessage
import re


live2dsignal = Live2DSignals()

class Identity(Enum):  # Information identifier
    User = user  # Used to identify user input information
    Brain = "your brain"  # Used to identify information given by digital human's own brain
    Body = "your live2d body"  # Used to identify information given by digital human's body
    System = "system"  # Used to identify information given by system environment, i.e., narrator

DEFAULT_IDENTITY_DEFINITIONS = {
    Identity.User: "who is interacting with you.",
    Identity.Brain: "who tells you what you've done and guides you on how to respond",
    Identity.Body: "who can set expressions and start motions following your brain's instructions.",
    Identity.System: "who provide the system environment information.",
}

class AIFE:
    """AI Virtual Companion Agent"""

    def __init__(self, agent_config=config.agent, stream_chat_callback=None, live2d_signals=None, message_signals=None):
        # Initialize logging
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('agent')
        
        # Basic components
        self.config = agent_config
        self.llm = self._initialize_llm(self.config.llm.platform, self.config.llm.llm_config)
        self.user = user
        self.stream_chat_callback = stream_chat_callback
        # Initialize memory manager, passing agent name and user information
        self.memory_manager = MemoryManager(agent_name=self.config.name, agent_user=self.user)
        # Maintain backward compatibility
        self.short_term_memory = self.memory_manager.short_term_memory
        self.short_term_memory.clear()
        
        # Format persona with identity definitions
        identity_definitions_str = "\n".join([
            f"{identity.value}: {definition}"
            for identity, definition in DEFAULT_IDENTITY_DEFINITIONS.items()
        ])
        self.persona = str(self.config.persona).format(Identity_Definitions=identity_definitions_str)
        self.short_term_memory.add_message(SystemMessage(content=self.persona))
        
        # note
        self.note_history = ChatMessageHistory()
        self.note_history.clear()
        self.note_prompt = self.config.note_prompt.format(persona=self.config.persona)
        self.note_history.add_message(SystemMessage(content=self.note_prompt))
        
        # Track processed chat history for note writing
        self.last_note_message_count = 0

        # Signal connections
        self.live2d_signals = live2d_signals or live2dsignal
        self.message_signals = message_signals  # Receives MessageSignals object
        
        # Record executed actions
        self.executed_actions = []

        
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
        """Custom multi-action output parser to ensure ShouldTalk tool is executed last"""
        
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
            should_talk_action = None
            
            # Match actions using regex
            action_pattern = r'Action:\s*(\w+)\s*Action Input:\s*([^\n]+)'
            matches = re.findall(action_pattern, text, re.IGNORECASE)
            
            # Collect all actions, placing ShouldTalk last
            for tool_name, tool_input in matches:
                tool_name_lower = tool_name.lower()
                if tool_name_lower == 'shouldtalk':
                    # Save ShouldTalk action to add later
                    should_talk_action = AgentAction(
                        tool="ShouldTalk",
                        tool_input=tool_input.strip(),
                        log=f"Action: ShouldTalk\nAction Input: {tool_input}"
                    )
                    continue
                if tool_name_lower in self.tool_names:
                    actions.append(AgentAction(
                        tool=tool_name,
                        tool_input=tool_input.strip(),
                        log=f"Action: {tool_name}\nAction Input: {tool_input}"
                    ))
            
            # Add ShouldTalk action last if it exists
            if should_talk_action:
                actions.append(should_talk_action)
            else:
                # Automatically add a default ShouldTalk action if not present
                actions.append(AgentAction(
                    tool="ShouldTalk",
                    tool_input="true",
                    log="Automatically added ShouldTalk: Default talk required"
                ))
            
            return actions if actions else [
                AgentAction(
                    tool="ShouldTalk",
                    tool_input="true",
                    log="Only executing ShouldTalk step"
                )
            ]
    
    def _create_tools(self):
        """Create tool list"""
        tools = []
        tools.append(Tool(
            name="WhatICanDo",
            func=lambda x: asyncio.run(self._whaticando(x)),
            description="Use this tool when the user asks about your capabilities or what actions you can perform. This will return a list of your enabled actions and features. Input: any value (e.g., 'yes')"
        ))
        if "whatuserdoing" in self.config.actions.enabled:
            tools.append(Tool(
                name="WhatUserDoing",
                func=lambda x: asyncio.run(self._whatuserdoing(x)),
                description="Use this tool to check what the user is currently doing by analyzing their active windows and applications. Useful when you want to understand user's current activity, when feeling ignored, or when you need context about user's state. Input: any value (e.g., 'yes')"
            ))
        if "remember" in self.config.actions.enabled:
            tools.append(Tool(
                name="Remember",
                func=lambda x: asyncio.run(self._remember_something(x)),
                description="Store important information into long-term memory when needing to remember user preferences, important facts, personal information, and other content that needs to be preserved long-term. Input format: content to remember. Example: Amon likes watching anime"
            ))
        if "recall" in self.config.actions.enabled:
            tools.append(Tool(
                name="Recall",
                func=lambda x: asyncio.run(self._recall_query(x)),
                description="Retrieve relevant information from long-term memory when needing to recall previously stored information or answer questions that require historical memory. Input format: query keywords or question. Example: 9+10=21 and this is a meme"
            ))

        if "get_current_time" in self.config.actions.enabled:
            tools.append(Tool(
                name="GetCurrentTime",
                func=lambda x: asyncio.run(self._get_current_time(x)),
                description=f"Get current time. Format: Yes"
            ))
        # Expression setting tool
        if "set_expression" in self.config.actions.enabled:
            tools.append(Tool(
                name="SetExpression",
                func=lambda x: asyncio.run(self._set_expression(x)),
                description=f"Set mate's Live2D expression. Format: expression. Available expressions: {', '.join(self.config.live2d.available_expression.keys())}"
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
                description=f"Start mate's Live2D motion. Format: group_index. Available motions: {'; '.join(motion_desc)}"
            ))
        
        # Web search tool
        if "web_search" in self.config.actions.enabled:
            try:
                tools.append(Tool(
                    name="WebSearch",
                    func=lambda x: asyncio.run(self._wikipedia_search(x)),
                    description="Useful for when you need to look up a topic on the internet to find more information. Input should be a search query."
                ))
            except Exception as e:
                self.logger.warning(f"Failed to initialize Wikipedia tool: {e}")


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
            name="ShouldTalk",
            func=lambda x: asyncio.run(self._should_talk(x)),
            description="Tool to determine whether to talk to the user (including responding to user and initiating conversation). Input true to talk, false otherwise. Format: true or false"
        ))
        
        return tools
    
    def _create_multi_action_agent(self):
        """Create multi-action Runnable chain"""
        
        # Create prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.config.decision_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad", optional=True)
        ])
        
        # Create output parser
        output_parser = self.MultiActionOutputParser(self.tools)
        
        # 格式化函数
        def format_scratchpad(intermediate_steps: List[Tuple[AgentAction, str]]) -> List[BaseMessage]:
            """Format intermediate steps"""
            if not intermediate_steps:
                return []
                
            messages = []
            results = []
            for action, observation in intermediate_steps:
                results.append(f"{action.tool}: {observation}")
                messages.append(AIMessage(content="\n".join(results)))
            return messages
        
        # Create Runnable chain
        if self.llm is None:
            raise ValueError("LLM is not initialized properly")
            
        chain = (
            RunnablePassthrough.assign(
                agent_scratchpad=lambda x: format_scratchpad(x.get("intermediate_steps", [])),
                chat_history=lambda x: x.get("chat_history", [])
            )
            | prompt.partial(
                persona=self.config.persona,
                tools="\n".join([f"{tool.name}: {tool.description}" for tool in self.tools])
            )
            | self.llm
            | (lambda x: output_parser.parse(x.content))
        )
        
        # Create RunnableMultiActionAgent
        return RunnableMultiActionAgent(
            runnable=chain,
        )
    
    def _get_available_emojis(self):
        """Get available emoji list"""
        assets_path = self.config.assets.assets_path
        if os.path.exists(assets_path):
            return [f for f in os.listdir(assets_path) 
                   if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        return []
    
    def _get_available_audio(self):
        """Get available audio list"""
        assets_path = self.config.assets.assets_path
        if os.path.exists(assets_path):
            return [f for f in os.listdir(assets_path) 
                   if f.endswith(('.mp3', '.wav', '.ogg'))]
        return []
    
    def _format_executed_actions(self, executed_actions: List[Dict]) -> str:
        """Convert executed actions to natural language descriptions"""
        if not executed_actions:
            return ""
        
        action_descriptions = []
        for action in executed_actions:
            action_name = action.get("name", "")
            # Use "result" instead of "output" as that's what we pass from filtered_actions
            action_output = action.get("result", action.get("output", ""))
            
            # Debug logging for WhatICanDo action
            if action_name == "WhatICanDo":
                self.logger.debug(f"WhatICanDo action processing - name: {action_name}, output: '{action_output}', type: {type(action_output)}")
            
            # Generate natural language descriptions based on action types
            if action_name == "SetExpression":
                if "✓ Expression set:" in action_output:
                    expression = action_output.split(":")[-1].strip()
                    body_action = self._create_context_message(Identity.Body, f"adjusted expression to {expression}")
                    action_descriptions.append(body_action)
                elif "✗" in action_output:
                    body_action = self._create_context_message(Identity.Body, "tried to adjust expression but failed")
                    action_descriptions.append(body_action)
            
            elif action_name == "StartMotion":
                if "✓ Motion executed:" in action_output:
                    motion = action_output.split(":")[-1].strip()
                    body_action = self._create_context_message(Identity.Body, f"performed {motion} motion")
                    action_descriptions.append(body_action)
                elif "✗" in action_output:
                    body_action = self._create_context_message(Identity.Body, "tried to perform motion but failed")
                    action_descriptions.append(body_action)
            
            elif action_name == "ShowEmoji":
                if "✓ Emoji sent:" in action_output:
                    emoji = action_output.split(":")[-1].strip()
                    action_descriptions.append(f"I sent {emoji} emoji")
                elif "✗" in action_output:
                    action_descriptions.append("I tried to send emoji but failed")
            
            elif action_name == "PlayAudio":
                if "✓ Audio played:" in action_output:
                    audio = action_output.split(":")[-1].strip()
                    action_descriptions.append(f"I played {audio} audio")
                elif "✗" in action_output:
                    action_descriptions.append("I tried to play audio but failed")
            
            elif action_name == "Remember":
                if "✓ I have remembered:" in action_output:
                    content = action_output.split(":")[-1].strip()
                    action_descriptions.append(f"I remembered: {content}")
                elif "✗" in action_output:
                    action_descriptions.append("I tried to remember something but failed")
            
            elif action_name == "Recall":
                if "I recalled the following information:" in action_output:
                    action_descriptions.append(action_output)
                elif "couldn't find any relevant memories" in action_output:
                    action_descriptions.append("I couldn't find relevant memories")
                elif "✗" in action_output:
                    action_descriptions.append("I tried to recall information but failed")
            
            elif action_name == "GetCurrentTime":
                if ":" in action_output:
                    time_info = action_output.strip()
                    action_descriptions.append(f"I checked the current time: {time_info}")
            
            elif action_name == "WebSearch":
                if action_output and not action_output.startswith("✗"):
                    action_descriptions.append(f"I searched for relevant information: {action_output}")
                else:
                    action_descriptions.append("I tried to search for information but failed")
            
            elif action_name == "WhatICanDo":
                # Use the actual output from the action, which should contain the capabilities list
                if action_output:
                    brain_action = self._create_context_message(Identity.Brain, f"reviewed my capabilities: {action_output}")
                    action_descriptions.append(brain_action)
                else:
                    brain_action = self._create_context_message(Identity.Brain, "reviewed my capabilities")
                    action_descriptions.append(brain_action)
            
            elif action_name == "WhatUserDoing":
                if action_output and "system:" in action_output.lower():
                    # 新格式已经包含完整的system标识信息
                    action_descriptions.append(action_output.replace("✓ ", ""))
                elif action_output and action_output.startswith("✓"):
                    system_action = self._create_context_message(Identity.System, "checked user activity")
                    action_descriptions.append(system_action)
                else:
                    system_action = self._create_context_message(Identity.System, "attempted to check user activity but failed")
                    action_descriptions.append(system_action)
        
        return ", ".join(action_descriptions) if action_descriptions else ""
    
    def _create_context_message(self, identity: Identity, content: str) -> str:
        """Create context message with identity label"""
        return f"{identity.value}: {content}"
    
    async def _whaticando(self, something: str) -> str:
        """获取自己的actions"""
        return str(self.config.actions.enabled)
    
    async def _whatuserdoing(self, something: str) -> str:
        """获取用户当前正在做什么 - 通过检查当前活动窗口"""
        try:
            # 导入必要的模块
            import win32gui
            import win32process
            import win32con
            import psutil
            from typing import List, Dict, Any
            
            # 获取前台窗口（用户当前正在使用的窗口）
            foreground_hwnd = win32gui.GetForegroundWindow()
            foreground_window = None
            
            if foreground_hwnd:
                try:
                    window_title = win32gui.GetWindowText(foreground_hwnd)
                    class_name = win32gui.GetClassName(foreground_hwnd)
                    _, pid = win32process.GetWindowThreadProcessId(foreground_hwnd)
                    
                    try:
                        process = psutil.Process(pid)
                        process_name = process.name()
                        process_exe = process.exe()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        process_name = "Unknown"
                        process_exe = "Unknown"
                    
                    if window_title.strip() and len(window_title) > 1:
                        foreground_window = {
                            'title': window_title,
                            'process': process_name,
                            'exe': process_exe
                        }
                        
                except Exception as e:
                    self.logger.warning(f"Failed to get foreground window info: {e}")
            
            # 获取其他活跃窗口
            all_windows = []
            
            def enum_windows_callback(hwnd, windows_list):
                try:
                    if win32gui.IsWindowVisible(hwnd) and win32gui.GetParent(hwnd) == 0:
                        window_title = win32gui.GetWindowText(hwnd)
                        if window_title.strip() and len(window_title) > 1:
                            _, pid = win32process.GetWindowThreadProcessId(hwnd)
                            try:
                                process = psutil.Process(pid)
                                process_name = process.name()
                                rect = win32gui.GetWindowRect(hwnd)
                                width = rect[2] - rect[0]
                                height = rect[3] - rect[1]
                                
                                # 过滤条件：排除系统窗口和太小的窗口
                                if (width > 100 and height > 50 and 
                                    hwnd != foreground_hwnd):  # 排除前台窗口，避免重复
                                    windows_list.append({
                                        'hwnd': hwnd,
                                        'title': window_title,
                                        'process': process_name,
                                        'width': width,
                                        'height': height
                                    })
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                except Exception:
                    pass
                return True
            
            try:
                win32gui.EnumWindows(enum_windows_callback, all_windows)
            except Exception as e:
                self.logger.warning(f"Failed to enumerate windows: {e}")
            
            # 过滤掉无关紧要的系统窗口
            ignored_classes = [
                'Shell_TrayWnd', 'DV2ControlHost', 'WorkerW', 'Progman',
                'Windows.UI.Core.CoreWindow', 'ApplicationFrameWindow'
            ]
            
            ignored_titles = [
                'Program Manager', 'Desktop Window Manager',
                'NVIDIA GeForce Overlay DT', 'NVIDIA GeForce Overlay'
            ]
            
            ignored_processes = [
                'dwm.exe', 'winlogon.exe', 'csrss.exe', 'smss.exe',
                'services.exe', 'lsass.exe', 'NVIDIA Overlay.exe'
            ]
            
            # 过滤窗口
            filtered_windows = []
            for window in all_windows:
                if (window['process'] not in ignored_processes and
                    window['title'] not in ignored_titles and
                    len(window['title'].strip()) > 0):
                    filtered_windows.append(window)
            
            # 限制窗口数量，按大小排序（优先显示较大的窗口）
            filtered_windows.sort(key=lambda w: w['width'] * w['height'], reverse=True)
            other_windows = filtered_windows[:5]  # 最多显示5个其他窗口
            
            # 生成更友好的描述信息
            if foreground_window:
                # 判断用户活动类型
                process_name = foreground_window['process'].lower()
                title = foreground_window['title']
                
                # 根据应用类型生成更自然的描述
                if any(app in process_name for app in ['chrome', 'firefox', 'edge', 'browser']):
                    activity_desc = f"browsing web on {title}"
                elif any(app in process_name for app in ['code', 'notepad', 'sublime', 'vim', 'atom']):
                    activity_desc = f"coding/editing in {title}"
                elif any(app in process_name for app in ['word', 'excel', 'powerpoint', 'office']):
                    activity_desc = f"working on document: {title}"
                elif any(app in process_name for app in ['game', 'steam']):
                    activity_desc = f"playing game: {title}"
                elif any(app in process_name for app in ['video', 'player', 'vlc', 'media']):
                    activity_desc = f"watching video: {title}"
                elif any(app in process_name for app in ['chat', 'discord', 'telegram', 'qq', 'wechat']):
                    activity_desc = f"chatting on {title}"
                else:
                    activity_desc = f"using {title}"
                
                # 构建其他窗口的描述
                if other_windows:
                    other_apps = []
                    for window in other_windows:
                        app_name = window['process'].replace('.exe', '')
                        other_apps.append(app_name)
                    
                    # 去重并限制数量
                    unique_apps = list(dict.fromkeys(other_apps))[:4]  # 最多4个其他应用
                    other_desc = ", ".join(unique_apps)
                    if len(filtered_windows) > 5:
                        other_desc += " and more"
                    
                    result_message = f"User is {activity_desc} and also has {other_desc} opened"
                else:
                    result_message = f"User is {activity_desc}"
            else:
                if other_windows:
                    app_names = [w['process'].replace('.exe', '') for w in other_windows[:3]]
                    result_message = f"User has {', '.join(app_names)} opened but no active foreground window"
                else:
                    result_message = "User appears to be idle or on desktop"
            
            # 使用优化的Identity.System标识信息
            system_info = self._create_context_message(Identity.System, result_message)
            self.logger.info(system_info)
            
            return f"✓ {system_info}"
            
        except Exception as e:
            error_msg = f"Failed to get user activity information: {str(e)}"
            self.logger.error(error_msg)
            return f"✗ {error_msg}"
    
    async def _wikipedia_search(self, query: str) -> str:
        """Search Wikipedia for a query"""
        query = query.strip().split('\n')[0]
        wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        wikipedia_result = wikipedia.run(query)
        return wikipedia_result

    async def _remember_something(self, something: str) -> str:
        """记住某些信息到长期记忆中"""
        something = something.strip().split('\n')[0]
        self.logger.info(f"_remember_something input parameter {len(something)}: {something}")
        
        try:
            # 使用长期记忆管理器添加记忆
            self.memory_manager.long_term_memory.add_memory_with_user(
                memory=something,
                user=self.user
            )
            self.logger.info(f"Successfully remembered: {something}")
            return f"✓ I have remembered: {something}"
        except Exception as e:
            self.logger.error(f"Memory storage failed: {e}")
            return f"✗ Memory storage failed: {str(e)}"
    
    async def _recall_query(self, query: str) -> str:
        """从长期记忆中回忆信息"""
        query = query.strip().split('\n')[0]
        self.logger.info(f"_recall_query input parameter {len(query)}: {query}")
        
        try:
            # 从长期记忆中搜索相关信息
            results = self.memory_manager.long_term_memory.recall_memory_with_user(
                query=query,
                user=self.user,
                top_k=2
            )
            
            if results:
                # 格式化搜索结果
                recalled_info = []
                for result in results:
                    memory = result["content"]  # 修复键名：从'memory'改为'content'
                    score = result.get("similarity", 0)  # 修复键名：从'score'改为'similarity'
                    time_info = result["metadata"].get("time", "Unknown time")
                    recalled_info.append(f"[{time_info}] {memory} (similarity: {score:.3f})")
                
                response = f"I recalled the following information:\n" + "\n".join(recalled_info)
                self.logger.info(f"Successfully recalled: {len(results)} records")
                return response
            else:
                self.logger.info(f"No relevant memory found: {query}")
                return f"Sorry, I couldn't find any relevant memories about '{query}'."
                
        except Exception as e:
            self.logger.error(f"Memory recall failed: {e}")
            return f"✗ Memory recall failed: {str(e)}"


    async def _get_current_time(self, *args, **kwargs) -> str:
        """Get current time - ignores all input parameters"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async def _set_expression(self, expression: str) -> str:
        """Set Live2D expression"""
        # Clean input, keep only the first line or word
        expression = expression.strip().split('\n')[0].split()[-1]
        
        try:
            if expression in self.config.live2d.available_expression:
                # Randomly select an expression ID
                expression_id = random.choice(
                    self.config.live2d.available_expression[expression]
                )
                # Send signal to Live2D
                if self.live2d_signals:
                    self.live2d_signals.expression_requested.emit(expression_id)
                body_info = self._create_context_message(Identity.Body, f"Expression set to {expression} (ID: {expression_id})")
                self.logger.info(body_info)
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
            body_info = self._create_context_message(Identity.Body, f"Motion started: {group}_{index} - {motion_desc}")
            self.logger.info(body_info)
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

    async def _should_talk(self, should_talk: str) -> str:
        """Wrapper function for ShouldTalk tool, used by Agent"""
        # Parse boolean input
        should_talk_clean = should_talk.strip().lower()
        
        if should_talk_clean in ['true', 'yes', '1']:
            # Mark ShouldTalk as called and talk required
            return "✓ Talk required"
        
        elif should_talk_clean in ['false', 'no', '0']:
            # Mark ShouldTalk as called but no talk required
            return "✓ No talk required"
        
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
        """Initialize language model"""
        if platform == "openai":
            llm =  ChatOpenAI(**llm_config)
        elif platform == "ollama":
            llm = ChatOllama(**llm_config)
        elif platform == "anthropic":
            llm = ChatAnthropic(**llm_config)
        else:
            raise ValueError(f"Unsupported platform: {platform}")
        
        # Test connection
        try:
            test_response = llm.invoke("Hello!")
            if test_response:
                return llm
            else:
                self.logger.error(f"LLM connection failed, please check configuration or proxy")
                return None
        except:
            self.logger.error(f"LLM connection failed, please check configuration or proxy")
            return None

    async def handle_free_time(self) -> AsyncGenerator[str, None]:
        if random.random() < 0.5:
            await self._write_note()
            yield "I wrote a note"
        else:
            try:
                # Get recent chat history for context
                chat_history = self.memory_manager.get_recent_messages(5)  # Get last 5 messages
                
                result = await self.agent_executor.ainvoke({
                    "input": f"System: you are ignored by {self.user} do what you want.(if you want to initiate a conversation use ShouldTalk)",
                    "chat_history": chat_history
                })
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
                        
                        # Check if it is the ShouldTalk tool
                        if action.tool == "ShouldTalk":
                            if "✓ Talk required" in observation:
                                common_chat_result = True
                            elif "✓ No talk required" in observation:
                                common_chat_result = False
                
                # Check if ShouldTalk was executed
                if common_chat_result is None:
                    # If ShouldTalk was not executed, log a warning and default to requiring a talk
                    self.logger.warning("Agent did not execute ShouldTalk tool, defaulting to talk required")
                    common_chat_result = True
                
                # If ShouldTalk returns True, execute language response
                if common_chat_result:
                    # Construct context with executed actions
                    self.logger.info(f"ShouldTalk result is True, executed actions: {self.executed_actions}")
                    
                    # Filter executed_actions, keeping only actually executed actions
                    filtered_actions = []
                    for action in self.executed_actions:
                        if action["name"] != "ShouldTalk":
                            if action.get("output", ""):
                                filtered_actions.append({
                                    "name": action["name"],
                                    "result": action["output"]
                                })
                    
                    # Use natural language to format action descriptions
                    action_description = self._format_executed_actions(filtered_actions)
                    
                    # Use Identity enum to label information sources
                    if action_description:
                        brain_info = self._create_context_message(Identity.Brain, f"Just performed these actions: {action_description}")
                        system_info = self._create_context_message(Identity.System, f"You are being ignored by {self.user}, try to initiate a conversation naturally")
                        context_input = f"{system_info}\n{brain_info}\nInitiate conversation naturally"
                    else:
                        system_info = self._create_context_message(Identity.System, f"You are being ignored by {self.user}, try to initiate a conversation naturally")
                        context_input = f"{system_info}\nInitiate conversation naturally"
                    
                    self.logger.info(f"context_input: {context_input}")
                    # Create temporary messages for streaming generation
                    self.short_term_memory.add_message(HumanMessage(content=context_input))
                    
                    # Use messages with action descriptions for streaming conversation
                    if self.llm:
                        async for chunk in self.llm.astream(self.short_term_memory.messages):
                            if isinstance(chunk, AIMessageChunk):
                                if chunk.content and isinstance(chunk.content, str):
                                    if self.stream_chat_callback:
                                        await self._safe_call_callback(chunk.content)
                                    yield str(chunk.content)
                    else:
                        yield "LLM not initialized properly"

            except Exception as e:
                error_msg = f"Error executing Agent tools: {str(e)}"
                self.logger.error(error_msg)
                yield error_msg
    async def agent_chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """Asynchronous streaming agent chat generator - Executes multi-action Agent and returns streaming responses"""
        try:
            # Clear action records
            self.executed_actions = []
            common_chat_result = None  # Record result of ShouldTalk
            # Execute multi-action Agent
            try:
                if user_input:
                    # Get recent chat history for context
                    chat_history = self.memory_manager.get_recent_messages(5)  # Get last 5 messages
                    
                    # Directly use agent_executor's ainvoke method to execute multi-actions
                    result = await self.agent_executor.ainvoke({
                        "input": user_input,
                        "chat_history": chat_history
                    })
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
                        
                        # Check if it is the ShouldTalk tool
                        if action.tool == "ShouldTalk":
                            if "✓ Talk required" in observation:
                                common_chat_result = True
                            elif "✓ No talk required" in observation:
                                common_chat_result = False
                
                # Check if ShouldTalk was executed
                if common_chat_result is None:
                    # If ShouldTalk was not executed, log a warning and default to requiring a talk
                    self.logger.warning("Agent did not execute ShouldTalk tool, defaulting to talk required")
                    common_chat_result = True
                
                # If ShouldTalk returns True, execute language response
                if common_chat_result:
                    # Construct context with executed actions
                    self.logger.info(f"ShouldTalk result is True, executed actions: {self.executed_actions}")
                    
                    # Filter executed_actions, keeping only actually executed actions
                    filtered_actions = []
                    for action in self.executed_actions:
                        if action["name"] != "ShouldTalk":
                            if action.get("output", ""):
                                filtered_actions.append({
                                    "name": action["name"],
                                    "result": action["output"]
                                })
                    
                    # Use natural language to format action descriptions
                    action_description = self._format_executed_actions(filtered_actions)
                    
                    # Use Identity enum to label information sources
                    user_input_with_identity = self._create_context_message(Identity.User, user_input)
                    if action_description:
                        brain_info = self._create_context_message(Identity.Brain, f"Just performed these actions: {action_description}")
                        context_input = f"{user_input_with_identity}\n{brain_info}\nRespond naturally"
                    else:
                        context_input = f"{user_input_with_identity}\nRespond naturally"
                    
                    self.logger.info(f"context_input: {context_input}")
                    # Create temporary messages for streaming generation
                    self.short_term_memory.add_message(HumanMessage(content=context_input))
                    
                    # Use messages with action descriptions for streaming conversation
                    if self.llm:
                        async for chunk in self.llm.astream(self.short_term_memory.messages):
                            if isinstance(chunk, AIMessageChunk):
                                if chunk.content and isinstance(chunk.content, str):
                                    if self.stream_chat_callback:
                                        await self._safe_call_callback(chunk.content)
                                    yield str(chunk.content)
                    else:
                        yield "LLM not initialized properly"

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
            # Search relevant memories as context
            memory_context = self.memory_manager.get_memory_context(user_input)
            
            # Add user message to memory system
            self.memory_manager.short_term_memory.add_message(HumanMessage(content=user_input))
            
            # Get conversation history
            messages = self.memory_manager.get_recent_messages(10)
            
            # If there is memory context, insert context before latest messages
            if memory_context.strip():
                # Use Identity to label memory source
                brain_memory_info = self._create_context_message(Identity.Brain, f"Relevant memories: {memory_context}")
                context_msg = SystemMessage(content=brain_memory_info)
                messages = [context_msg] + messages

            full_response = ""
            if self.llm:
                async for chunk in self.llm.astream(messages):
                    if isinstance(chunk, AIMessageChunk):
                        if chunk.content and isinstance(chunk.content, str):
                            full_response += chunk.content
                            if self.stream_chat_callback:
                                await self._safe_call_callback(chunk.content)
                            yield str(chunk.content)
            else:
                yield "LLM not initialized properly"
            
            # Add AI reply to memory system
            if full_response:
                self.memory_manager.short_term_memory.add_message(AIMessage(content=full_response))
                
        except Exception as e:
            error_msg = f"Chat processing failed: {str(e)}"
            self.logger.error(error_msg)
            yield error_msg

    async def _write_note(self) -> str:
        """Write diary and inner monologue to long-term memory"""
        try:
            # Get new chat histories
            new_histories = self.get_new_histories()
            
            # If no new content, skip note writing
            if new_histories in ["No new chat history since last note.", "No new conversational content."]:
                self.logger.info("No new content for note writing")
                self.note_history.add_message(HumanMessage(content=f"No new chat history, write something yourself."))
            else:
                # Add new histories to note history
                self.note_history.add_message(HumanMessage(content=f"New chat history:\n{new_histories}"))
            
            # Generate note using LLM
            if not self.llm:
                self.logger.error("LLM not initialized for note writing")
                return "✗ LLM not available for note writing"
                
            response = await self.llm.ainvoke(self.note_history.messages)
            
            if response and response.content:
                # Ensure content is string
                note_content = response.content
                if isinstance(note_content, list):
                    note_content = str(note_content)
                
                # Add note to long-term memory with special prefix and Identity
                brain_note = self._create_context_message(Identity.Brain, f"[Internal Note] {note_content}")
                self.memory_manager.long_term_memory.add_memory_with_user(
                    memory=brain_note,
                    user=self.user
                )
                
                # Add AI response to note history
                self.note_history.add_message(AIMessage(content=note_content))
                
                self.logger.info(f"Note written successfully: {note_content[:100]}...")
                return f"✓ Note written: {note_content[:50]}..."
            else:
                self.logger.error("No response from LLM for note writing")
                return "✗ Failed to generate note"
                
        except Exception as e:
            self.logger.error(f"Error writing note: {e}")
            return f"✗ Note writing failed: {str(e)}"


    def get_new_histories(self) -> str:
        """Get the latest chat histories that are not yet sent to write_note"""
        try:
            # Get all messages from short term memory
            all_messages = self.short_term_memory.messages
            
            # Get new messages since last note
            new_messages = all_messages[self.last_note_message_count:]
            
            # Format new messages as string
            if not new_messages:
                return "No new chat history since last note."
            
            formatted_history = []
            for msg in new_messages:
                if isinstance(msg, HumanMessage):
                    # Check if message already contains Identity label, if not add it
                    content = msg.content
                    if isinstance(content, str):
                        if not any(identity.value + ":" in content for identity in Identity):
                            content = self._create_context_message(Identity.User, content)
                        formatted_history.append(content)
                    else:
                        # If content is not string, convert to string
                        content_str = str(content)
                        if not any(identity.value + ":" in content_str for identity in Identity):
                            content_str = self._create_context_message(Identity.User, content_str)
                        formatted_history.append(content_str)
                elif isinstance(msg, AIMessage):
                    formatted_history.append(f"{self.config.name}: {msg.content}")
                elif isinstance(msg, SystemMessage):
                    # Skip system messages for note writing
                    continue
            
            # Update the count of processed messages
            self.last_note_message_count = len(all_messages)
            
            return "\n".join(formatted_history) if formatted_history else "No new conversational content."
            
        except Exception as e:
            self.logger.error(f"Error getting new histories: {e}")
            return "Error retrieving chat history."

    async def _safe_call_callback(self, content: str):
        """Safely call callback function, automatically detect if it's async function"""
        try:
            if self.stream_chat_callback:
                if inspect.iscoroutinefunction(self.stream_chat_callback):
                    # If it's async function, use await to call
                    await self.stream_chat_callback(content)
                else:
                    # If it's sync function, call directly
                    self.stream_chat_callback(content)
        except Exception as e:
            self.logger.error(f"Error calling stream_chat_callback: {e}")

    # ============ System Status Query ============
    
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get status summary"""
        return {
            "memory_stats": self.memory_manager.get_memory_stats() if hasattr(self, 'memory_manager') else {}
        }

