#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Agent与Brain集成的功能
"""

import sys
import os
from dotmap import DotMap
import toml
from loguru import logger

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Head.Brain.agent import AIFE
from Body.tlw import Live2DSignals
from Message.MessageBox import MessageBox, MessageSignals

def test_agent_integration():
    """测试Agent集成功能"""
    logger.info("开始测试Agent集成功能...")
    
    # 加载配置
    config = DotMap(toml.load("config.toml"))
    
    # 创建模拟信号和组件
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
        message_signals=message_signals  # 传递MessageSignals对象
    )
    
    # 测试不同的输入
    test_cases = [
        "你好！",
        "做一个开心的表情",
        "做一个idle动作",
        "发送一个表情包",
        "播放一个音效",
        "搜索一下AI的发展历史",
        "做个动作然后跟我聊天"
    ]
    
    print("\n=== 测试Agent功能 ===")
    for i, test_input in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {test_input}")
        print("-" * 50)
        
        try:
            # 测试agent_chat（流式智能体）
            print("使用agent_chat（智能体模式）:")
            response_parts = []
            for chunk in agent.agent_chat(test_input):
                response_parts.append(chunk)
                print(chunk, end='', flush=True)
            print(f"\n完整响应: {''.join(response_parts)}")
            
            # 显示执行的动作
            if agent.executed_actions:
                print(f"执行的动作: {agent.executed_actions}")
            
        except Exception as e:
            logger.error(f"测试失败: {e}")
        
        print("\n" + "="*70)
    
    print("\n测试完成！")
    
    # 保持窗口打开以查看效果
    print("按Ctrl+C退出...")
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("\n程序退出")

if __name__ == "__main__":
    test_agent_integration()
