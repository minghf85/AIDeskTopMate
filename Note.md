Azure 语音服务
[ssml 文档结构和事件](https://learn.microsoft.com/zh-cn/azure/ai-services/speech-service/speech-synthesis-markup-structure)

```xml
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="string">
    <mstts:backgroundaudio src="string" volume="string" fadein="string" fadeout="string"/>
    <mstts:voiceconversion url="string"/>
    <voice name="string" effect="string">
        <audio src="string"></audio>
        <bookmark mark="string"/>
        <break strength="string" time="string" />
        <emphasis level="value"></emphasis>
        <lang xml:lang="string"></lang>
        <lexicon uri="string"/>
        <math xmlns="http://www.w3.org/1998/Math/MathML"></math>
        <mstts:audioduration value="string"/>
        <mstts:ttsembedding speakerProfileId="string"></mstts:ttsembedding>
        <mstts:express-as style="string" styledegree="value" role="string"></mstts:express-as>
        <mstts:silence type="string" value="string"/>
        <mstts:viseme type="string"/>
        <p></p>
        <phoneme alphabet="string" ph="string"></phoneme>
        <prosody pitch="value" contour="value" range="value" rate="value" volume="value"></prosody>
        <s></s>
        <say-as interpret-as="string" format="string" detail="string"></say-as>
        <sub alias="string"></sub>
    </voice>
</speak>
```

语音合成测试
[试用有声内容精简版](https://speech.microsoft.com/audiocontentcreation)


```
python Head/stt_server.py
python -m Head.Brain.brain
```

mpv安装并添加到环境变量


免费翻译：
https://appworlds.cn/translate/


[tts.settings]
text = ""
text_lang = "ja"
ref_audio_path = "H:/AIVtuber/VOICE_reference/mona-roxy/aojiao.wav"
prompt_text = "ふん、まさか負けを認めるわけじゃないですよね。"
prompt_lang = "ja"
# 生成参数
top_k = 5
top_p = 1.0
temperature = 1.0
repetition_penalty = 1.35
seed = -1  # -1表示随机种子

# 文本处理
text_split_method = "cut0"
batch_size = 5
batch_threshold = 0.75
split_bucket = false
return_fragment = false

# 语音控制
speed_factor = 1.0  # 语速调节（1.0为正常速度）

# 系统设置
streaming_mode = true  # 是否启用流式生成
parallel_infer = true   # 是否启用并行推理


CurrentBug: 语音合成中断等