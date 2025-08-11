#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于PyAudio的实时ASR测试
使用麦克风实时录音并进行语音识别
"""

import pyaudio
import numpy as np
import threading
import queue
import time
import signal
import sys
from ear import ASR
from loguru import logger

class RealTimeASR:
    """实时ASR测试类"""
    
    def __init__(self, 
                 sample_rate=16000,
                 chunk_size=1024,
                 channels=1,
                 device="cuda:0"):
        """
        初始化实时ASR
        
        Args:
            sample_rate: 采样率
            chunk_size: 音频块大小
            channels: 声道数
            device: ASR计算设备
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.format = pyaudio.paInt16
        
        # 初始化ASR
        self.asr = ASR(
            sample_rate=sample_rate,
            device=device
        )
        
        # 音频队列
        self.audio_queue = queue.Queue()
        self.result_queue = queue.Queue()
        
        # 控制标志
        self.is_recording = False
        self.is_processing = False
        
        # PyAudio实例
        self.pa = None
        self.stream = None
        
        # 线程
        self.record_thread = None
        self.process_thread = None
        
        logger.info("实时ASR初始化完成")
    
    def list_audio_devices(self):
        """列出可用的音频设备"""
        pa = pyaudio.PyAudio()
        logger.info("=== 可用音频设备 ===")
        
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            logger.info(f"设备 {i}: {info['name']}")
            logger.info(f"  - 最大输入声道: {info['maxInputChannels']}")
            logger.info(f"  - 最大输出声道: {info['maxOutputChannels']}")
            logger.info(f"  - 默认采样率: {info['defaultSampleRate']}")
            logger.info("---")
        
        pa.terminate()
    
    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        if status:
            logger.warning(f"音频流状态: {status}")
        
        # 将音频数据放入队列
        audio_data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32767.0
        
        if not self.audio_queue.full():
            self.audio_queue.put(audio_data)
        else:
            logger.warning("音频队列已满，丢弃数据")
        
        return (None, pyaudio.paContinue)
    
    def start_recording(self, input_device_index=None):
        """开始录音"""
        try:
            self.pa = pyaudio.PyAudio()
            
            # 获取默认输入设备
            if input_device_index is None:
                input_device_index = self.pa.get_default_input_device_info()['index']
            
            # 确保设备索引是整数
            if isinstance(input_device_index, (str, float)):
                input_device_index = int(input_device_index)
            
            logger.info(f"使用音频设备: {input_device_index}")
            
            # 创建音频流
            self.stream = self.pa.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=input_device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=self.audio_callback
            )
            
            self.is_recording = True
            self.stream.start_stream()
            
            logger.info("开始录音...")
            
        except Exception as e:
            logger.error(f"启动录音失败: {e}")
            self.cleanup()
    
    def start_processing(self, enable_sv=True, language="auto"):
        """开始处理音频"""
        self.is_processing = True
        
        def process_audio():
            logger.info("开始音频处理线程...")
            
            while self.is_processing:
                try:
                    # 从队列获取音频数据
                    audio_chunk = self.audio_queue.get(timeout=1.0)
                    
                    # 处理音频
                    result = self.asr.process_audio_chunk(
                        audio_chunk, 
                        enable_sv=enable_sv, 
                        language=language
                    )
                    
                    if result:
                        # 将结果放入结果队列
                        self.result_queue.put(result)
                        
                        # 实时显示结果
                        timestamp = time.strftime("%H:%M:%S", time.localtime(result['timestamp']))
                        logger.info(f"[{timestamp}] [{result['speaker']}] {result['text']}")
                        
                        # 检查是否包含有意义内容
                        if self.asr.contains_meaningful_content(result['text']):
                            print(f"\n🎤 [{result['speaker']}]: {result['text']}")
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"音频处理错误: {e}")
        
        self.process_thread = threading.Thread(target=process_audio, daemon=True)
        self.process_thread.start()
    
    def stop_recording(self):
        """停止录音"""
        self.is_recording = False
        self.is_processing = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        
        if self.pa:
            self.pa.terminate()
        
        logger.info("录音已停止")
    
    def cleanup(self):
        """清理资源"""
        self.stop_recording()
        
        # 重置ASR状态
        if self.asr:
            self.asr.reset()
        
        logger.info("资源清理完成")
    
    def get_results(self):
        """获取识别结果"""
        results = []
        while not self.result_queue.empty():
            try:
                result = self.result_queue.get_nowait()
                results.append(result)
            except queue.Empty:
                break
        return results
    
    def run_interactive_test(self, duration=None, input_device=None):
        """
        运行交互式测试
        
        Args:
            duration: 录音时长(秒)，None为无限期
            input_device: 输入设备索引
        """
        print("=== 实时ASR测试 ===")
        print("按 Ctrl+C 停止录音")
        print("说话内容将实时显示...")
        print()
        
        # 设置信号处理
        def signal_handler(sig, frame):
            print("\n\n正在停止录音...")
            self.cleanup()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            # 开始录音
            self.start_recording(input_device)
            
            # 开始处理
            self.start_processing()
            
            # 等待指定时间或用户中断
            if duration:
                time.sleep(duration)
                print(f"\n录音时间 {duration} 秒结束")
            else:
                # 保持运行直到用户中断
                while self.is_recording:
                    time.sleep(0.1)
            
        except KeyboardInterrupt:
            print("\n用户中断录音")
        except Exception as e:
            logger.error(f"测试运行错误: {e}")
        finally:
            self.cleanup()
            
            # 显示统计信息
            results = self.get_results()
            print(f"\n=== 测试完成 ===")
            print(f"共识别到 {len(results)} 条语音")
            
            if results:
                print("\n识别结果汇总:")
                for i, result in enumerate(results, 1):
                    timestamp = time.strftime("%H:%M:%S", time.localtime(result['timestamp']))
                    print(f"{i}. [{timestamp}] [{result['speaker']}] {result['text']}")

def test_audio_devices():
    """测试音频设备"""
    asr_test = RealTimeASR()
    asr_test.list_audio_devices()

def test_microphone_quality():
    """测试麦克风质量"""
    print("=== 麦克风质量测试 ===")
    
    # 简单的音频录制测试
    pa = pyaudio.PyAudio()
    
    try:
        # 录制5秒音频
        duration = 5
        sample_rate = 16000
        chunk_size = 1024
        
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            frames_per_buffer=chunk_size
        )
        
        print(f"录制 {duration} 秒音频，请说话...")
        
        frames = []
        for _ in range(0, int(sample_rate / chunk_size * duration)):
            data = stream.read(chunk_size)
            frames.append(data)
        
        print("录制完成")
        
        # 分析音频质量
        audio_data = np.frombuffer(b''.join(frames), dtype=np.int16)
        
        # 计算音频统计信息
        max_amplitude = np.max(np.abs(audio_data))
        rms = np.sqrt(np.mean(audio_data**2))
        
        print(f"最大振幅: {max_amplitude}")
        print(f"RMS: {rms:.2f}")
        
        if max_amplitude < 1000:
            print("⚠️  音频信号较弱，请检查麦克风音量")
        elif max_amplitude > 30000:
            print("⚠️  音频信号过强，可能出现失真")
        else:
            print("✅ 音频信号质量良好")
        
        stream.stop_stream()
        stream.close()
        
    except Exception as e:
        logger.error(f"麦克风测试失败: {e}")
    finally:
        pa.terminate()

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="实时ASR测试程序")
    parser.add_argument('--list-devices', action='store_true', help='列出音频设备')
    parser.add_argument('--test-mic', action='store_true', help='测试麦克风质量')
    parser.add_argument('--device', type=int, help='指定音频输入设备索引')
    parser.add_argument('--duration', type=int, help='录音时长(秒)')
    parser.add_argument('--asr-device', default='cuda:0', help='ASR计算设备')
    parser.add_argument('--language', default='auto', help='识别语言')
    parser.add_argument('--no-sv', action='store_true', help='禁用说话人验证')
    
    args = parser.parse_args()
    
    if args.list_devices:
        test_audio_devices()
        return
    
    if args.test_mic:
        test_microphone_quality()
        return
    
    # 创建实时ASR实例
    try:
        asr_test = RealTimeASR(device=args.asr_device)
        
        # 运行交互式测试
        asr_test.run_interactive_test(
            duration=args.duration,
            input_device=args.device
        )
        
    except Exception as e:
        logger.error(f"程序运行失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()