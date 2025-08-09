import asyncio
import websockets
import wave
import numpy as np
from io import BytesIO
import time

def generate_wav_header(sample_rate=32000, sample_width=2, channels=1):
    """生成WAV文件头"""
    with BytesIO() as wav_buf:
        with wave.open(wav_buf, 'wb') as vfout:
            vfout.setnchannels(channels)
            vfout.setsampwidth(sample_width)
            vfout.setframerate(sample_rate)
            vfout.writeframes(b'')  # 空数据只为生成头
        wav_buf.seek(0)
        return wav_buf.read()

async def simulate_gpt_sovits_stream(wav_file_path, server_uri="ws://localhost:8000/lipsync/stream"):
    # 打开WAV文件并获取参数
    with wave.open(wav_file_path, 'rb') as wav_file:
        params = {
            'channels': wav_file.getnchannels(),
            'sample_width': wav_file.getsampwidth(),
            'frame_rate': wav_file.getframerate(),
            'n_frames': wav_file.getnframes()
        }
        
        print(f"音频参数: {params}")
        
        # 计算每个chunk的帧数 (约0.3秒音频)
        chunk_frames = int(params['frame_rate'] * 0.3)
        chunk_size = chunk_frames * params['sample_width'] * params['channels']
        
        async with websockets.connect(server_uri) as websocket:
            print("已连接到WebSocket服务器")
            
            # 发送WAV头
            header = generate_wav_header(
                sample_rate=params['frame_rate'],
                sample_width=params['sample_width'],
                channels=params['channels']
            )
            await websocket.send(header)
            print(f"已发送WAV头 ({len(header)} 字节)")
            
            # 流式发送音频数据
            total_sent = 0
            start_time = time.time()
            
            while True:
                frames = wav_file.readframes(chunk_frames)
                if not frames:
                    print("音频发送完成")
                    break
                
                await websocket.send(frames)
                total_sent += len(frames)
                
                # 计算实时速率
                elapsed = time.time() - start_time
                print(f"已发送: {total_sent/1024:.1f}KB, "
                      f"速率: {total_sent/elapsed/1024:.1f}KB/s, "
                      f"时长: {total_sent/(params['sample_width']*params['channels']*params['frame_rate']):.2f}s")
                
                # 精确控制发送间隔 (模拟实时流)
                sent_duration = len(frames) / (params['frame_rate'] * params['sample_width'] * params['channels'])
                await asyncio.sleep(sent_duration * 0.95)  # 稍快于实时以保持流畅
            
            # 发送结束标记
            await websocket.send(b'END')
            print("传输完成")

if __name__ == "__main__":
    wav_path = "output.wav"
    asyncio.get_event_loop().run_until_complete(
        simulate_gpt_sovits_stream(wav_path)
    )