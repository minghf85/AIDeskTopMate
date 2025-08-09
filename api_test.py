import asyncio
import websockets
import aiohttp
import os
import time
from pathlib import Path

CHUNK_SIZE = 1024 * 16  # 16KB chunks
BASE_URL = 'http://127.0.0.1:8000'
WS_URL = 'ws://127.0.0.1:8000'

async def send_audio_via_websocket(file_path: str, chunk_size: int = 4096):
    """通过WebSocket发送音频文件数据（优化版）
    
    Args:
        file_path: 音频文件路径
        chunk_size: 每次发送的数据块大小（默认4KB）
    """
    uri = 'ws://127.0.0.1:8000/lipsync/stream'
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            
            # 使用二进制模式读取文件
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                        
                    # 发送数据块
                    await websocket.send(chunk)
                    print(f"Sent {len(chunk)} bytes")
                    
                    # 获取服务器确认（可选）
                    try:
                        ack = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        print(f"Server ACK: {ack}")
                    except asyncio.TimeoutError:
                        print("No server response")
                    
                    # 更真实的流式延迟（根据采样率计算）
                    await asyncio.sleep(chunk_size / 44100 / 2)  # 假设44.1kHz采样率
            
            # 发送结束标记
            await websocket.send(b"END_OF_STREAM")
            print("All audio data sent")
            
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"Connection closed: code={e.code}, reason={e.reason}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {str(e)}")
    finally:
        print("Connection terminated")

async def test_lipsync_file(file_path: str):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f'{BASE_URL}/lipsync/file?file={file_path}',  # 通过URL查询参数传递
        ) as response:
            result = await response.json()
            print(f"Response: {result}")

async def test_lipsync_interrupt():
    """测试中断接口"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{BASE_URL}/lipsync/interrupt') as response:
                result = await response.json()
                print(f"Interrupt response: {result}")
                return result
    except Exception as e:
        print(f"中断请求失败: {str(e)}")
        return None

async def run_all_tests(audio_file: str):
    """运行所有测试"""
    # print("1. 测试WebSocket流式传输...")
    # await send_audio_via_websocket(audio_file)
    
    print("\n2. 测试文件上传...")
    await test_lipsync_file(audio_file)
    
    # 使用异步等待代替time.sleep
    print("\n等待10秒后发送中断...")
    await asyncio.sleep(10)
    
    print("\n3. 测试中断功能...")
    await test_lipsync_interrupt()

# 使用示例
async def main():
    await run_all_tests("output.wav")

if __name__ == "__main__":
    asyncio.run(main())

