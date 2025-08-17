"""
使用langchain简化实现的AI Agent
这是一个简化版本，专注于核心功能
"""

from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_core.messages import SystemMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain.callbacks.base import BaseCallbackHandler
from Body.tlw import Live2DSignals
from dotmap import DotMap
import toml
import random
import os
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ActionLogger(BaseCallbackHandler):
    def __init__(self, agent_instance):
        self.agent = agent_instance
    
    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized['name']
        print(f"\n[工具调用开始]")
        print(f"工具名称: {tool_name}")
        print(f"输入参数: {input_str}")
        
        # 记录动作到agent实例
        if tool_name == "SetExpression":
            expression = input_str.strip().split('\n')[0].split()[0]
            self.agent.executed_actions.append(f"设置表情为{expression}")
        elif tool_name == "StartMotion":
            motion = input_str.strip().split('\n')[0].split()[0]
            if '_' in motion:
                group = motion.split('_')[0]
                self.agent.executed_actions.append(f"执行{group}动作")
        elif tool_name == "SendEmoji":
            emoji = input_str.strip().split('\n')[0].split()[0]
            self.agent.executed_actions.append(f"发送表情包{emoji}")
        elif tool_name == "PlayAudio":
            audio = input_str.strip().split('\n')[0].split()[0]
            self.agent.executed_actions.append(f"播放音效{audio}")
        elif tool_name == "WebSearch":
            query = input_str.strip().split('\n')[0]
            self.agent.executed_actions.append(f"搜索{query}")

    def on_tool_end(self, output, **kwargs):
        print(f"[工具调用结束] 输出: {output}")

class SimpleLangChainAgent:
    """使用LangChain实现的简化AI Agent"""
    
    def __init__(self, config_path="config.toml"):
        # 加载配置
        self.config = DotMap(toml.load(config_path))
        
        # 初始化Live2D信号
        self.signal = Live2DSignals()
        
        # 初始化LLM
        self.llm = self._initialize_llm()
        
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
            callbacks=[ActionLogger(self)],
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=5
        )
        
        # 初始化聊天历史
        self.chat_history = ChatMessageHistory()
        self.chat_history.add_message(SystemMessage(content=self.config.agent.persona))
        
    def _initialize_llm(self):
        """初始化语言模型"""
        platform = self.config.agent.llm.platform
        llm_config = dict(self.config.agent.llm.llm_config)
        
        if platform == "openai":
            return ChatOpenAI(**llm_config)
        elif platform == "ollama":
            return ChatOllama(**llm_config)
        elif platform == "anthropic":
            return ChatAnthropic(**llm_config)
        else:
            raise ValueError(f"不支持的平台: {platform}")
    
    def _create_tools(self):
        """创建工具列表"""
        tools = []
        
        # 表情设置工具
        if "set_expression" in self.config.agent.actions.enabled:
            tools.append(Tool(
                name="SetExpression",
                func=self._set_expression,
                description=f"设置Live2D表情。可用表情: {', '.join(self.config.live2d.available_expression.keys())}"
            ))
        
        # 动作开始工具
        if "start_motion" in self.config.agent.actions.enabled:
            motion_desc = []
            for group, motions in self.config.live2d.available_motion.items():
                for i, desc in enumerate(motions):
                    motion_desc.append(f"{group}_{i}: {desc}")
            
            tools.append(Tool(
                name="StartMotion",
                func=self._start_motion,
                description=f"开始Live2D动作。格式: group_index。可用动作: {'; '.join(motion_desc)}"
            ))
        
        # 网页搜索工具
        if "web_search" in self.config.agent.actions.enabled:
            wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
            tools.append(Tool(
                name="WebSearch",
                func=wikipedia.run,
                description="搜索Wikipedia获取信息"
            ))
        
        # 表情包发送工具
        if "send_emoji" in self.config.agent.actions.enabled:
            emoji_list = self._get_available_emojis()
            tools.append(Tool(
                name="SendEmoji",
                func=self._send_emoji,
                description=f"发送表情包。可用表情包: {', '.join(emoji_list)}"
            ))
        
        # 音频播放工具
        if "play_audio" in self.config.agent.actions.enabled:
            audio_list = self._get_available_audio()
            tools.append(Tool(
                name="PlayAudio",
                func=self._play_audio,
                description=f"播放音效。可用音效: {', '.join(audio_list)}"
            ))
        
        # 通用聊天工具（可选执行）
        if "common_chat" in self.config.agent.actions.enabled:
            tools.append(Tool(
                name="CommonChat",
                func=self._common_chat,
                description="可选的聊天回复工具，用于与用户自然对话"
            ))
        
        return tools
    
    def _create_agent(self):
        """创建ReAct agent"""
        # 准备工具信息
        tool_names = [tool.name for tool in self.tools]
        tool_descriptions = "\n".join([f"{tool.name}: {tool.description}" for tool in self.tools])
        
        # 创建prompt模板
        prompt_template = """你是一个AI live2D数字人。你的人设是{persona}
请根据{user}请求执行相应的动作。专注于执行动作，不要多余的描述。

你可以使用的工具:
{tools}

请严格按照以下格式执行:
Action: 工具名称，必须是[{tool_names}]中的一个
Action Input: 工具的输入参数（只能是一个简单的单词或短语）

执行规则:
1. 根据用户需求选择合适的动作
2. 每个Action Input只能是简单参数，不包含多行文本
3. 可以选择是否使用CommonChat进行最终回复
4. 专注于动作执行，避免冗余描述

用户输入: {input}
{agent_scratchpad}"""
        
        prompt = PromptTemplate.from_template(prompt_template)
        
        # 创建agent
        return create_react_agent(
            self.llm,
            self.tools,
            prompt.partial(
                persona=self.config.agent.persona,
                user=self.config.agent.user,
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
    
    def _set_expression(self, expression: str) -> str:
        """设置Live2D表情"""
        # 清理输入参数，只保留第一行或第一个单词
        expression = expression.strip().split('\n')[0].split()[0]
        print(f"\n+++++++_set_expression传入参数{len(expression)}: {expression}+++++++\n")
        
        try:
            if expression in self.config.live2d.available_expression:
                # 随机选择一个表情ID
                expression_id = random.choice(
                    self.config.live2d.available_expression[expression]
                )
                # 发送信号（如果在实际环境中）
                self.signal.expression_requested.emit(expression_id)
                logger.info(f"设置表情: {expression} (ID: {expression_id})")
                return f"✓ 设置表情: {expression}"
            else:
                available = list(self.config.live2d.available_expression.keys())
                return f"✗ 无效表情: {expression}"
        except Exception as e:
            logger.error(f"设置表情时出错: {e}")
            return f"✗ 表情设置失败"
    
    def _start_motion(self, motion_input: str) -> str:
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
            
            # 发送信号（如果在实际环境中）
            self.signal.motion_requested.emit(group, index, 3)
            
            motion_desc = motions[index]
            logger.info(f"开始动作: {group}_{index} - {motion_desc}")
            return f"✓ 执行动作: {group}_{index}"
            
        except ValueError:
            return f"✗ 动作格式错误"
        except Exception as e:
            logger.error(f"开始动作时出错: {e}")
            return f"✗ 动作执行失败"
    
    def _send_emoji(self, emoji_name: str) -> str:
        """发送表情包"""
        # 清理输入参数
        emoji_name = emoji_name.strip().split('\n')[0].split()[0]
        logger.info(f"_send_emoji传入参数{len(emoji_name)}: {emoji_name}")
        
        try:
            available_emojis = self._get_available_emojis()
            if emoji_name in available_emojis:
                logger.info(f"发送表情包: {emoji_name}")
                return f"✓ 发送表情包: {emoji_name}"
            else:
                return f"✗ 表情包不存在"
        except Exception as e:
            logger.error(f"发送表情包时出错: {e}")
            return f"✗ 表情包发送失败"
    
    def _play_audio(self, audio_name: str) -> str:
        """播放音效"""
        # 清理输入参数
        audio_name = audio_name.strip().split('\n')[0].split()[0]
        logger.info(f"_play_audio传入参数{len(audio_name)}: {audio_name}")
        
        try:
            available_audio = self._get_available_audio()
            if audio_name in available_audio:
                logger.info(f"播放音效: {audio_name}")
                return f"✓ 播放音效: {audio_name}"
            else:
                return f"✗ 音效不存在"
        except Exception as e:
            logger.error(f"播放音效时出错: {e}")
            return f"✗ 音效播放失败"
    
    def _common_chat(self, input_text: str) -> str:
        """通用聊天回复"""
        logger.info(f"_common_chat传入参数{len(input_text)}: {input_text}")
        try:
            # 构建自然语言描述
            actions_desc = ""
            if self.executed_actions:
                actions_desc = f"刚才我{', '.join(self.executed_actions)}，"
            
            # 构建回复输入
            chat_input = f"{actions_desc}现在回应用户的请求：{self.current_user_input}"
            
            logger.info(f"通用聊天输入: {chat_input}")
            return f"好的！{actions_desc}现在我来回应你的请求～"
        except Exception as e:
            logger.error(f"通用聊天时出错: {e}")
            return f"✗ 聊天回复失败"
    
    def chat(self, user_input: str) -> str:
        """主要的聊天接口"""
        try:
            # 记录当前用户输入并清理动作记录
            self.current_user_input = user_input
            self.executed_actions = []
            
            # 执行agent
            result = self.agent_executor.invoke({"input": user_input})
            
            # 添加到聊天历史
            from langchain_core.messages import HumanMessage, AIMessage
            self.chat_history.add_message(HumanMessage(content=user_input))
            self.chat_history.add_message(AIMessage(content=result['output']))
            
            return result['output']
            
        except Exception as e:
            logger.error(f"处理聊天时出错: {e}")
            return f"抱歉，处理您的请求时出现错误: {str(e)}"
    
    def get_available_actions(self) -> dict:
        """获取可用动作信息"""
        return {
            "expressions": list(self.config.live2d.available_expression.keys()),
            "motions": dict(self.config.live2d.available_motion),
            "emojis": self._get_available_emojis(),
            "audio": self._get_available_audio()
        }


def main():
    """测试函数"""
    # 创建agent实例
    agent = SimpleLangChainAgent()
    
    print("=== 简化版LangChain Agent测试 ===\n")
    
    # 显示可用动作
    actions = agent.get_available_actions()
    print("可用的表情:", actions['expressions'])
    print("可用的动作组:", list(actions['motions'].keys()))
    print("可用的表情包:", actions['emojis'])
    print("可用的音效:", actions['audio'])
    print("\n" + "="*50 + "\n")
    
    # 测试用例
    test_cases = [
        "请给我一个微笑",
        # "做个开心的动作然后聊天",
        # "发个表情包，播放音效，然后和我聊天",
        # "你知道Python吗？",
        # "表现出害羞的样子"
    ]
    
    for i, test_input in enumerate(test_cases, 1):
        print(f"=== 测试 {i}: {test_input} ===")
        try:
            response = agent.chat(test_input)
            print(f"回复: {response}")
        except Exception as e:
            print(f"错误: {e}")
        print("\n" + "-"*50 + "\n")


if __name__ == "__main__":
    main()
