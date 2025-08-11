# Brain模块数据流通系统使用指南

## 概述

Brain模块是整个系统的核心，负责统筹管理所有功能模块之间的数据流通。它采用消息队列机制，支持异步处理，确保各个模块之间的高效通信。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Brain (大脑)                          │
├─────────────────────────────────────────────────────────────┤
│  消息队列系统 │ 事件处理器 │ 模块管理器 │ 便捷API接口        │
└─────────────────────────────────────────────────────────────┘
           │                    │                    │
    ┌──────▼──────┐    ┌───────▼───────┐    ┌──────▼──────┐
    │   Agent     │    │   MessageBox  │    │  Live2D     │
    │  (智能体)    │    │  (消息显示)    │    │  (身体)      │
    └─────────────┘    └───────────────┘    └─────────────┘
           │                    │                    │
    ┌──────▼──────┐    ┌───────▼───────┐    ┌──────▼──────┐
    │    ASR      │    │     TTS       │    │   Actions   │
    │  (语音识别)  │    │  (语音合成)    │    │  (动作系统)  │
    └─────────────┘    └───────────────┘    └─────────────┘
```

## 核心功能

### 1. 消息类型

系统支持以下消息类型：

- `TEXT`: 文本消息（用户输入、AI回复等）
- `COMMAND`: 命令消息（显示图片、播放动画等）
- `EVENT`: 事件消息（系统事件、用户交互等）
- `EMOTION`: 情感消息（情感状态变化）
- `SYSTEM`: 系统消息（状态报告、错误信息等）

### 2. 消息处理流程

1. **消息发送**: 通过`send_message()`方法将消息放入队列
2. **消息处理**: 后台线程从队列中取出消息并分发给对应处理器
3. **响应生成**: 处理器处理消息并可能生成响应消息
4. **结果反馈**: 响应消息放入响应队列供其他模块使用

## 使用方法

### 基本使用

```python
from Head.Brain.brain import Brain
from Message.message import MessageType

# 创建大脑实例
brain = Brain()

# 处理用户输入
brain.process_user_input("你好，请介绍一下你自己")

# 显示图片
brain.show_image("avatar.png")

# 显示GIF
brain.show_gif("animation.gif")

# 让AI说话
brain.say("这是AI的回复", show_in_ui=True, speak_aloud=True)
```

### 高级使用

```python
# 发送自定义消息
message = brain.send_message(
    MessageType.COMMAND, 
    {"type": "show_image", "data": "image.png"}, 
    sender="user"
)

# 注册自定义消息处理器
def custom_handler(message):
    print(f"处理自定义消息: {message.content}")
    return None

brain.register_message_handler(MessageType.CUSTOM, custom_handler)

# 执行命令
brain.execute_command("clear_display", None)

# 设置情感状态
brain.set_emotion("happy", intensity=0.8)

# 获取系统状态
status = brain.get_status()
print(f"系统运行状态: {status}")
```

## 便捷API

### 文本和语音

- `say(text, show_in_ui=True, speak_aloud=True)`: 让AI说话
- `process_user_input(user_input, sender="user")`: 处理用户输入

### 视觉显示

- `show_image(image_path)`: 显示图片
- `show_gif(gif_path)`: 显示GIF动画
- `clear_display()`: 清除显示内容

### 系统控制

- `execute_command(command_type, data, sender="system")`: 执行命令
- `set_emotion(emotion, intensity=1.0)`: 设置情感状态
- `get_status()`: 获取系统状态
- `sleep()`: 让系统进入休眠状态

## 消息处理器扩展

你可以注册自定义的消息处理器来扩展系统功能：

```python
def my_custom_handler(message):
    """自定义消息处理器"""
    print(f"收到自定义消息: {message.content}")
    
    # 处理逻辑
    if message.content == "special_command":
        # 执行特殊操作
        pass
    
    # 返回响应消息（可选）
    return Message(MessageType.SYSTEM, "处理完成", "custom_handler", message.sender)

# 注册处理器
brain.register_message_handler(MessageType.CUSTOM, my_custom_handler)
```

## 测试和调试

### 运行测试脚本

```bash
# 基本功能测试
python test_brain_communication.py

# 消息流转测试
python test_brain_communication.py flow
```

### 调试技巧

1. **查看系统状态**:
   ```python
   status = brain.get_status()
   print(status)
   ```

2. **监控消息队列**:
   ```python
   print(f"待处理消息: {brain.message_queue.qsize()}")
   print(f"响应消息: {brain.response_queue.qsize()}")
   ```

3. **启用详细日志**:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

## 最佳实践

1. **消息设计**: 保持消息内容简洁明确，使用结构化数据
2. **错误处理**: 在自定义处理器中添加适当的异常处理
3. **性能优化**: 避免在消息处理器中执行耗时操作
4. **资源管理**: 及时清理不需要的资源，调用`sleep()`方法
5. **模块解耦**: 通过消息系统而不是直接调用来实现模块间通信

## 常见问题

### Q: 消息处理器抛出异常怎么办？
A: 系统会捕获异常并打印错误信息，不会影响其他消息的处理。

### Q: 如何确保消息按顺序处理？
A: 系统使用单线程处理消息，保证了处理顺序。

### Q: 可以同时发送多个消息吗？
A: 可以，消息会被放入队列中按顺序处理。

### Q: 如何停止系统？
A: 调用`brain.sleep()`方法或按Ctrl+C。

## 扩展开发

如果你需要添加新的模块或功能：

1. 定义新的消息类型（如果需要）
2. 实现对应的消息处理器
3. 在Brain类中注册处理器
4. 添加便捷API方法（可选）
5. 编写测试用例

这样的设计确保了系统的可扩展性和维护性。