import threading
from queue import Queue
from collections import deque
import pyaudio as pa
import time
import wave
import requests
import io
import os
import numpy as np  # 添加这行
from datetime import datetime
from requests.auth import CONTENT_TYPE_FORM_URLENCODED
from dotmap import DotMap
import toml
import streamlit as st
from dotenv import load_dotenv
from RealtimeTTS import TextToAudioStream
import loguru
import logging

logger = loguru.logger
load_dotenv()

azure_api_key = os.environ.get("AZURE_SPEECH_KEY")
azure_region = os.environ.get("AZURE_SPEECH_REGION")

# 读取toml的live2d配置
config = DotMap(toml.load("config.toml"))


class TTS_GSV():
    """后面再写"""
    pass

class TTS_realtime():
    def __init__(self, on_word=None, on_character=None, on_audio_stream_start=None, on_text_stream_stop=None, on_text_stream_start=None, on_audio_stream_stop=None):
        super().__init__()
        self.on_word = on_word
        self.on_character = on_character
        self.on_audio_stream_start = on_audio_stream_start
        self.on_audio_stream_stop = on_audio_stream_stop
        self.on_text_stream_stop = on_text_stream_stop
        self.on_text_stream_start = on_text_stream_start


        if config.tts.settings.engine == "azure":
            from RealtimeTTS import AzureEngine
            self.engine = AzureEngine(azure_api_key, azure_region)
        elif config.tts.settings.engine == "edge":
            from RealtimeTTS import EdgeEngine
            self.engine = EdgeEngine()
        elif config.tts.settings.engine == "kokoro":
            from RealtimeTTS import KokoroEngine
            self.engine = KokoroEngine()
        else:
            raise ValueError("未知的 TTS 引擎")
        if config.tts.settings.voice_name == "Neuro":
            self.engine.set_voice("AshleyNeural")
            self.engine.set_voice_parameters(pitch=25)
        else:
            self.engine.set_voice(config.tts.settings.voice_name)

        self.stream = TextToAudioStream(
            self.engine,
            
            on_audio_stream_start=self.on_audio_stream_start if self.on_audio_stream_start else lambda x: None,
            on_audio_stream_stop=self.on_audio_stream_stop if self.on_audio_stream_stop else lambda x: None,
            on_word=self.on_word if self.on_word else lambda x: None,
            on_character=self.on_character if self.on_character else lambda x: None,
            on_text_stream_stop=self.on_text_stream_stop if self.on_text_stream_stop else lambda x: None,
            on_text_stream_start=self.on_text_stream_start if self.on_text_stream_start else lambda x: None
            )
        self.latency = 0

    def speak(self, stream):
        """将文本添加到音频流中"""
        self.stream.feed(stream)

    def speak_text(self, text):
        """将文本添加到音频流中"""
        self.stream.feed(text)
    

# if __name__ == "__main__":
#     tts = TTS_realtime()

