# ASR (自动语音识别) 类使用说明

## 概述

`ear.py` 中的 `ASR` 类是一个基于 FunASR 和 ModelScope 的自动语音识别实现，支持：

- 实时语音转文字
- 说话人验证
- 情感和事件检测
- 多语言支持
- VAD (语音活动检测)

## 特性

### 核心功能
- **语音转文字**: 使用 SenseVoiceSmall 模型进行高质量的语音识别
- **说话人验证**: 基于注册的说话人音频进行身份验证
- **语音活动检测**: 自动检测语音的开始和结束
- **情感识别**: 识别语音中的情感状态（快乐、悲伤、愤怒等）
- **事件检测**: 检测特殊事件（掌声、笑声、咳嗽等）

### 技术特点
- 支持 CUDA GPU 加速
- 流式音频处理
- 可配置的参数
- 完善的错误处理和日志记录

## 安装依赖

```bash
pip install funasr modelscope soundfile numpy loguru dotmap toml
```
modelscope
loguru
numpy
toml
dotmap
```

## 配置文件

在`config.toml`中配置ASR相关参数：

```toml
[asr]
engine = "Sensevoice"

[asr.settings]
speaker = "speaker/久倾standard.wav"  # 注册说话人音频文件路径
lang = "en"  # 识别语言：zh(中文), en(英文), ja(日文), ko(韩文)
```

## 使用方法

### 基本使用

```python
from Head.ear import ASR
import time

# 创建ASR实例
asr = ASR()

# 启动ASR线程
asr.start()

# 添加音频数据（numpy数组格式，float32，16kHz采样率）
audio_data = ...  # 你的音频数据
asr.add_audio(audio_data)

# 检查并获取识别结果
while asr.has_result():
    result = asr.get_result()
    if result:
        print(f"识别文本: {result['text']}")
        print(f"说话人: {result['speaker']}")
        print(f"置信度: {result['confidence']}")
        print(f"时间戳: {result['timestamp']}")

# 停止ASR线程
asr.stop()
```

### 麦克风实时录音

```python
from Head.microphone import MicrophoneRecorder
import time

# 创建麦克风录音器（会自动创建ASR实例）
recorder = MicrophoneRecorder()

try:
    # 开始录音
    recorder.start_recording()
    print("开始录音... 请说话")
    
    # 监听识别结果
    while True:
        if recorder.has_asr_result():
            result = recorder.get_asr_result()
            if result and result['text'].strip():
                print(f"识别结果: {result['text']}")
                print(f"说话人: {result['speaker']}")
        
        time.sleep(0.1)
        
except KeyboardInterrupt:
    print("停止录音")
finally:
    recorder.cleanup()
```

### 简单录音（指定时长）

```python
from Head.microphone import SimpleMicrophoneRecorder

# 创建简单录音器
recorder = SimpleMicrophoneRecorder()

try:
    # 录音10秒并自动处理
    recorder.record_and_process(duration=10)
finally:
    recorder.cleanup()
```

### 音频数据格式

ASR类支持多种音频数据格式：

1. **numpy数组** (推荐):
   - 数据类型: `np.float32`
   - 采样率: 16kHz
   - 声道: 单声道
   - 数值范围: [-1.0, 1.0]

2. **字节数据**:
   - 格式: 16位PCM
   - 采样率: 16kHz
   - 会自动转换为float32格式

### 说话人验证

1. 准备说话人注册音频文件（WAV格式，16kHz）
2. 在配置文件中设置音频文件路径
3. ASR会自动加载并进行说话人验证
4. 识别结果中包含说话人信息

## API参考

### ASR类方法

#### `__init__()`
初始化ASR实例，加载模型和配置。

#### `start()`
启动ASR工作线程。

#### `stop()`
停止ASR工作线程。

#### `add_audio(audio_data)`
添加音频数据到处理队列。

**参数:**
- `audio_data`: 音频数据，支持numpy数组或字节数据

#### `get_result()`
获取一个识别结果。

**返回:**
- 识别结果字典或None（如果没有结果）

#### `has_result()`
检查是否有待获取的识别结果。

**返回:**
- bool: True表示有结果，False表示没有结果

### MicrophoneRecorder类方法

#### `__init__(asr_instance=None)`
初始化麦克风录音器。

**参数:**
- `asr_instance`: ASR实例，如果为None则自动创建

#### `start_recording()`
开始麦克风录音。

#### `stop_recording()`
停止麦克风录音。

#### `get_asr_result()`
获取ASR识别结果。

**返回:**
- 识别结果字典或None

#### `has_asr_result()`
检查是否有ASR识别结果。

**返回:**
- bool: True表示有结果，False表示没有结果

#### `get_default_input_device()`
获取默认音频输入设备信息。

#### `cleanup()`
清理所有资源（录音器、ASR、PyAudio）。

### SimpleMicrophoneRecorder类方法

#### `__init__(asr_instance=None)`
初始化简单麦克风录音器。

#### `record_and_process(duration=None)`
录音并处理音频数据。

**参数:**
- `duration`: 录音时长（秒），如果为None则持续录音

#### `cleanup()`
清理资源。

### 识别结果格式

```python
{
    'text': '识别的文本内容',
    'speaker': '说话人名称或unknown',
    'confidence': 0.95,  # 置信度分数
    'timestamp': 1234567890.123  # Unix时间戳
}
```

## 示例代码

参考 `asr_example.py` 文件查看完整的使用示例。

## 注意事项

1. **GPU支持**: 如果系统支持CUDA，模型会自动使用GPU加速
2. **内存管理**: 长时间运行时注意音频队列的内存使用
3. **线程安全**: ASR类是线程安全的，可以在多线程环境中使用
4. **模型下载**: 首次运行时会自动下载所需的模型文件
5. **音频格式**: 确保输入音频为16kHz采样率以获得最佳识别效果
6. **麦克风权限**: 确保应用程序有访问麦克风的权限
7. **音频设备**: 确保系统有可用的音频输入设备
8. **PyAudio依赖**: 麦克风功能需要PyAudio库，确保正确安装

## 故障排除

### 常见问题

1. **模型加载失败**
   - 检查网络连接
   - 确保有足够的磁盘空间
   - 检查CUDA环境（如果使用GPU）

2. **识别结果为空**
   - 检查音频数据格式
   - 确认音频中包含语音内容
   - 检查VAD阈值设置

3. **说话人验证失败**
   - 确认说话人音频文件存在
   - 检查音频文件格式和质量
   - 调整说话人验证阈值

4. **麦克风无法录音**
   - 检查麦克风是否正确连接
   - 确认系统音频设备设置
   - 检查应用程序麦克风权限
   - 尝试重新插拔麦克风设备

5. **PyAudio安装失败**
   - Windows: `pip install pyaudio`
   - 如果失败，尝试: `pip install pipwin && pipwin install pyaudio`
   - Linux: `sudo apt-get install portaudio19-dev && pip install pyaudio`
   - macOS: `brew install portaudio && pip install pyaudio`

6. **音频质量差**
   - 检查麦克风质量和位置
   - 减少环境噪音
   - 调整麦克风增益设置
   - 确保说话距离适中

7. **录音延迟或卡顿**
   - 检查系统CPU和内存使用率
   - 调整音频块大小参数
   - 关闭其他占用音频设备的程序
   - 尝试使用不同的音频设备

## 性能优化

- 使用GPU加速（推荐NVIDIA GPU）
- 适当调整音频块大小
- 合理设置队列大小
- 定期清理缓存数据