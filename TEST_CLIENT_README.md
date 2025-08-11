# 多服务器测试客户端使用说明

这个测试客户端使用 Streamlit 构建，可以同时测试三个服务器：

## 服务器说明

1. **Live2D控制器** (端口 8000) - `shape_server.py`
   - 控制Live2D模型的显示、动作、表情等

2. **语音转文本服务** (端口 8001) - `stt_server.py`
   - 提供实时语音识别功能
   - 支持说话人验证

3. **文本转语音服务** (端口 8002) - `tts_server.py`
   - 提供多引擎文本转语音功能
   - 支持多种声音选择

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务器

### 1. 启动Live2D控制器
```bash
python Body/shape_server.py
```

### 2. 启动STT服务器
```bash
python Voice/stt_server.py --port 8001
```

### 3. 启动TTS服务器
```bash
python Voice/tts_server.py --port 8002
```

## 启动测试客户端

```bash
streamlit run test_client.py
```

## 功能说明

### STT测试
- 录制音频并发送到STT服务器进行识别
- 支持多语言选择（自动、中文、英文、日文、韩文）
- 可启用/禁用说话人验证
- 实时显示识别结果和说话人信息

### TTS测试
- 选择不同的TTS引擎（Edge、Azure、Kokoro等）
- 为每个引擎选择不同的声音
- 输入文本生成语音
- 提供预设文本快速测试
- 支持声音试听功能

### Live2D控制
- 加载和控制Live2D模型
- 播放动作和设置表情
- 调整模型位置、旋转、缩放
- 控制模型参数
- 配置窗口属性

## 注意事项

1. 确保所有服务器都已正确启动
2. STT服务器需要CUDA支持以获得最佳性能
3. TTS服务器可能需要配置API密钥（Azure引擎）
4. 音频录制功能需要麦克风权限
5. 某些功能可能需要特定的模型文件

## 故障排除

- 如果服务器显示离线，请检查对应端口是否被占用
- 音频录制问题请检查浏览器麦克风权限
- WebSocket连接失败请检查防火墙设置
- 模型加载失败请检查模型文件路径