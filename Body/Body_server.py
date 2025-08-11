import sys
import signal
from PyQt6.QtWidgets import QApplication
from live2dcontroller import Live2DController
from dotmap import DotMap
import toml
# 读取toml的live2d配置
config = DotMap(toml.load("config.toml"))

def signal_handler(signum, frame):
    """处理Ctrl+C信号"""
    print("\nReceived Ctrl+C, shutting down...")
    app.quit()
    sys.exit(0)

# 使用示例
if __name__ == "__main__":
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 创建Qt应用
    app = QApplication(sys.argv)
    
    # 创建控制器
    controller = Live2DController(host=config.live2d.host, port=config.live2d.port)

    # 启动系统
    window = controller.start(app)
    if config.live2d.model_path:
        controller.window._load_model(config.live2d.model_path)

    print("Live2D Controller started!")
    print("API Documentation: http://127.0.0.1:8000/docs")
    print("Press Ctrl+C to stop the server")
    
    # 运行Qt应用
    sys.exit(app.exec())