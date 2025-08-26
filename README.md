# AIDeskTopMate

本项目基于AIFE重构，旨在打造一个模块化，高度自定义的ai桌面伴侣，本地化也是我的追求。

```bash
AIDeskTopMate/
```

## 主要功能
[x] 实时对话：TTS、STT、LLM
[ ] 主动对话
[ ] 个体状态变化：情感、心理、环境、肉体、饥饿等
[ ] 行为
    - [ ] 细粒度：移动、旋转、缩放
    - [x] 粗粒度：对话、播放声音、网络搜索、发送图片表情包、做动作表情
[ ] 记忆：
    - [ ] 短期记忆：对话记录
    - [ ] 长期记忆：个人信息、偏好、习惯等

## 运行说明
### 1. 安装依赖
```bash
pip install -r requirements.txt
pip install -r requirements4stt.txt
pip install -r requirements4tts.txt
```

为了同步口型，需要将此项目下的`text_to_stream.py`替换掉**realtimeTTS**项目的`text_to_stream.py`,默认路径为`你的环境路径\Lib\site-packages\RealtimeTTS\text_to_stream.py`
还需要安装 mpv并且添加到环境变量
可以参考这篇文章[mpv安装](https://blog.csdn.net/weixin_44578029/article/details/130568037)
还需要安装 ffmpeg并且添加到环境变量
可以参考这篇文章[ffmpeg安装](https://blog.csdn.net/m0_47449768/article/details/130102406)
如果你需要使用GPT-Sovits的tts，需要将api_v3.py放到GPT-Sovits项目根目录下，并使用GPT-Sovits的环境运行api_v3.py，默认使用GPT_SoVITS/configs/tts_infer.yaml的配置，详细问题可以提issue

### 2. 运行项目
```bash
python main.py
```
### 3. 配置项目
  - 编辑 `config.toml` 文件，根据需要修改项目配置。
  - 确保配置文件中的路径和参数设置正确，特别是与Live2D模型和语音文件的路径。
  - 配置文件中包含了详细的注释，帮助你理解每个参数的作用。

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



