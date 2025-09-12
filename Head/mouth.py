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
import hashlib  # 添加这行
import string  # 添加这行
import re  # 添加这行
import random  # 添加这行
from datetime import datetime
from requests.auth import CONTENT_TYPE_FORM_URLENCODED
from dotmap import DotMap
import toml
from dotenv import load_dotenv
from RealtimeTTS import TextToAudioStream
from Head.gsv_stream import GSVStream
from utils.log_manager import LogManager
load_dotenv()

azure_api_key = os.environ.get("AZURE_SPEECH_KEY")
azure_region = os.environ.get("AZURE_SPEECH_REGION")

# 读取toml的live2d配置
config = DotMap(toml.load("config.toml"))
config_json = toml.load("config.toml")



class TTS_GSV():
    """GPT-SoVITS TTS 引擎实现"""
    
    def __init__(self, on_character=None, on_audio_stream_start=None, 
                 on_text_stream_stop=None, on_text_stream_start=None, on_audio_stream_stop=None):
        # Initialize logging
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('mouth')
        
        self.on_character = on_character
        self.on_audio_stream_start = on_audio_stream_start
        self.on_audio_stream_stop = on_audio_stream_stop
        self.on_text_stream_stop = on_text_stream_stop
        self.on_text_stream_start = on_text_stream_start
        
        self.base_url = config.tts.base_url
        self.settings = config.tts.settings
        self.is_playing = False
        self.current_response = None
        
        # 创建流对象，模拟 TTS_realtime 的 stream 属性
        self.stream = GSVStream(
            on_audio_stream_start=self.on_audio_stream_start,
            on_audio_stream_stop=self.on_audio_stream_stop,
            on_character=self.on_character,
            on_text_stream_start=self.on_text_stream_start,
            on_text_stream_stop=self.on_text_stream_stop
        )
        

class TTS_realtime():
    def __init__(self, on_character=None, on_audio_stream_start=None, on_text_stream_stop=None, on_text_stream_start=None, on_audio_stream_stop=None):
        # Initialize logging
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('mouth')
        
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
            self.engine.set_voice("EvelynMultilingualNeural")
            self.engine.set_voice_parameters(pitch=22)
        if config.tts.settings.voice_name == "Alpha":
            self.engine.set_voice("EvelynMultilingualNeural")#JaneNeural、
            self.engine.set_voice_parameters(pitch=10)
        else:
            self.engine.set_voice(config.tts.settings.voice_name)

        self.stream = TextToAudioStream(
            self.engine,
            on_audio_stream_start=self.on_audio_stream_start if self.on_audio_stream_start else lambda x: None,
            on_audio_stream_stop=self.on_audio_stream_stop if self.on_audio_stream_stop else lambda x: None,
            on_character=self.on_character if self.on_character else lambda x: None,
            on_text_stream_stop=self.on_text_stream_stop if self.on_text_stream_stop else lambda x: None,
            on_text_stream_start=self.on_text_stream_start if self.on_text_stream_start else lambda x: None
            )
    

# if __name__ == "__main__":
#     tts = TTS_realtime()

