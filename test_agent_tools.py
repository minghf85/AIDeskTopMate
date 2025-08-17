#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Agent的工具调用功能（不阻塞版本）
"""

import sys
import os
from dotmap import DotMap
import toml
from loguru import logger

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_agent_tools():
    """测试Agent工具调用功能"""
    logger.info("开始测试Agent工具调用功能...")
    
    # 加载配置
    config = DotMap(toml.load("config.toml"))
    
    # 创建模拟信号和组件
    from Body.tlw import Live2DSignals
    from Message.MessageBox import MessageBox, MessageSignals
    from Head.Brain.agent import AIFE
    
    live2d_signals = Live2DSignals()
    message_signals = MessageSignals()
    
    # 创建消息框（用于测试）
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    message_box = MessageBox(message_signals)
    message_box.show()
    
    # 创建Agent实例
    agent = AIFE(
        agent_config=config.agent,
        stream_chat_callback=lambda text: print(f"流式输出: {text}"),
        live2d_signals=live2d_signals,
        message_signals=message_signals
    )
    
    # 测试不同的工具调用
    test_cases = [
        {
            "name": "测试表情设置",
            "input": "做一个开心的表情",
            "description": "应该调用SetExpression工具"
        },
        {
            "name": "测试动作执行", 
            "input": "做一个idle动作",
            "description": "应该调用StartMotion工具"
        },
        {
            "name": "测试表情包发送",
            "input": "发送一个表情包",
            "description": "应该调用SendEmoji工具，通过信号发送到MessageBox"
        },
        {
            "name": "测试音效播放",
            "input": "播放一个音效",
            "description": "应该调用PlayAudio工具，通过信号发送到MessageBox"
        },
        {
            "name": "测试网络搜索",
            "input": "搜索一下人工智能",
            "description": "应该调用WebSearch工具"
        }
    ]
    
    print("\n=== 测试Agent工具调用功能 ===")
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {test_case['name']}")
        print(f"描述: {test_case['description']}")
        print(f"输入: {test_case['input']}")
        print("-" * 60)
        
        try:
            # 测试agent_chat（流式智能体）
            print("Agent响应:")
            response_parts = []
            for chunk in agent.agent_chat(test_case['input']):
                response_parts.append(chunk)
                print(chunk, end='', flush=True)
            
            full_response = ''.join(response_parts)
            print(f"\n完整响应: {full_response}")
            
            # 显示执行的动作
            if agent.executed_actions:
                print(f"执行的动作: {agent.executed_actions}")
            else:
                print("没有执行特定动作")
            
        except Exception as e:
            logger.error(f"测试失败: {e}")
        
        print("\n" + "="*70)
        
        # 等待用户确认继续
        if i < len(test_cases):
            input("按Enter键继续下一个测试...")
    
    print("\n所有测试完成！")
    print("消息框将保持打开状态以查看表情包和音效播放效果...")
    print("按Ctrl+C退出...")
    
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("\n程序退出")

if __name__ == "__main__":
    test_agent_tools()
