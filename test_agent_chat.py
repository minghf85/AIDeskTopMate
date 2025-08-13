#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试 agent_chat 功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Head.Brain.agent import AIFE

def test_agent_chat():
    """测试智能体聊天功能"""
    
    def stream_callback(content):
        """流式回调函数"""
        print(f"[Stream] {content}", end="", flush=True)
    
    # 创建智能体实例
    aife = AIFE(stream_chat_callback=stream_callback)
    
    print("AI虚拟伙伴智能体已启动！")
    print("可以尝试以下命令：")
    print("- 请设置一个开心的表情")
    print("- 请做一个挥手的动作") 
    print("- 你能跳舞吗？")
    print("- 输入 'quit' 退出")
    print("-" * 50)
    
    while True:
        try:
            user_input = input("\n用户: ").strip()
            
            if user_input.lower() in ['quit', 'exit', '退出']:
                print("再见！")
                break
                
            if not user_input:
                continue
                
            print("AI: ", end="")
            
            # 使用智能体聊天
            response_parts = []
            for chunk in aife.agent_chat(user_input):
                print(chunk, end="", flush=True)
                response_parts.append(chunk)
            
            print()  # 换行
            
        except KeyboardInterrupt:
            print("\n程序被用户中断")
            break
        except Exception as e:
            print(f"\n错误: {str(e)}")

if __name__ == "__main__":
    test_agent_chat()
