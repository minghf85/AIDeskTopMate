# AIDeskTopMate

本项目基于AIFE重构，旨在打造一个模块化，高度自定义的ai桌面伴侣，本地化也是我的追求。

```bash
TransparentLive2dWindow4pyqt6/
├── .gitignore
├── .vscode/
│   └── launch.json
├── Assets/
│   ├── assets.py
│   ├── audio.py
│   └── emoji.py
├── Body/
│   ├── AC.py
│   ├── __init__.py
│   ├── api_models.py
│   ├── live2dcontroller.py
│   ├── shape_server.py
│   ├── shape_simple_client.py
│   └── tlw.py
├── Brain/
│   ├── action.py
│   └── agent.py
├── Message/
│   ├── __init__.py
│   └── message.py
├── Note.md
├── README.md
├── Voice/
│   ├── hear.py
│   └── speech.py
├── api_test.py
├── config.toml
├── logger.py
├── main.py
├── output.wav
├── requirements.txt
├── static/
│   ├── favicon.ico
│   └── tts.js
└── tts_server.py
```

## 主要功能
[ ] 角色设定、世界观设定等
[ ] 实时对话：TTS、STT、LLM
[ ] 主动对话
[ ] 个体状态变化：情感、心理、环境、肉体、饥饿等
[ ] 行为
    - [ ] 细粒度：移动、旋转、缩放、透明度、颜色等
    - [ ] 粗粒度：对话、播放音乐音效、打开应用、搜索网页、发送表情包、记忆、回忆、视觉读取图片视频等等
[ ] 记忆：
    - [ ] 短期记忆：对话记录
    - [ ] 长期记忆：个人信息、偏好、习惯等

## 模块说明

### Brain 模块

#### action.py
实现了动作系统的基础架构，包括：
- `Action` 抽象基类：所有具体动作的父类
- `ActionRegistry` 类：管理和注册所有可用动作
- 示例动作实现：`DialogAction`、`EmotionAction` 等

#### agent.py
实现了智能体系统的基础架构，包括：
- `Agent` 抽象基类：所有具体智能体的父类
- `LangchainAgent` 类：基于Langchain框架的智能体实现
- `RuleBasedAgent` 类：基于规则的简单智能体实现

#### llmstudio.py
实现了与语言模型交互的功能，包括：
- `LLMStudio` 类：管理和使用不同的语言模型
- `PromptTemplate` 类：生成格式化的提示
- `Memory` 抽象基类和 `SimpleMemory` 实现：存储和检索对话历史
- `ModelFactory` 类：创建不同类型的语言模型

### Assets 模块

#### assets.py
实现了资源管理系统，包括：
- `Assets` 类：单例模式的资源管理器
- 支持图片、音频、模型、配置文件等多种格式
- 自动创建资源目录结构
- 提供资源索引、搜索、缓存管理功能
- 支持资源的添加、删除和导出

#### audio.py
实现了音频管理系统，包括：
- `Audio` 类：基于pyaudio的音频管理器
- `AudioTrack` 类：音频轨道表示
- `AudioState` 枚举：音频状态管理
- 支持WAV音频格式播放
- 提供音量控制（主音量和单轨道音量）
- 音频状态管理（播放、暂停、停止）

#### emoji.py
实现了表情包管理系统，包括：
- `Emoji` 类：表情包管理器
- `EmojiItem` 类：单个表情项
- `EmojiCollection` 类：表情集合
- `EmojiType` 枚举：表情类型（情感、动作、物品、符号、自定义）
- 表情搜索、收藏、使用统计功能
- 支持表情集合的导入导出

### Message 模块

#### message.py
实现了消息系统的基础架构，包括：
- `Message` 基类：所有消息类型的父类
- 具体消息类型：`TextMessage`、`CommandMessage`、`EventMessage`、`EmotionMessage`
- `MessageBus` 类：消息总线，用于在系统各组件之间传递消息

## 配置说明

项目使用 `config.toml` 文件进行配置，主要包括以下部分：

- 通用配置：项目名称、日志级别等
- 智能体配置：名称、类型、个性等
- LLM配置：默认模型、温度、最大令牌数等
- 记忆配置：类型、最大令牌数等
- 语音配置：语音识别和合成的设置
- 动作配置：启用的动作列表及各动作的具体配置
- UI配置：Live2D模型和窗口的设置

## 依赖说明

主要依赖包括：

- live2d-py：Live2D模型渲染
- pyqt6：GUI框架
- langchain：大型语言模型应用框架
- openai：OpenAI API接口
- chroma-db：向量数据库，用于存储和检索记忆
- llama-cpp-python：本地LLM模型支持
- gpt4all：本地LLM模型支持


现在有stt，tts，llm，我想要串通起来，为了做到低延迟、打断、交流顺畅等等，我应该怎么管理，stt、tts部分需要哪些功能
目前我对于stt部分是设置一个断句的参数，两个完整句子的时间间隔，识别到一个完整句子直接发送给llm；llm流式输出，通过标点符号进行句子分段，

