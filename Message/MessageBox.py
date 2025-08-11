from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import re
import threading
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QMovie
load_dotenv()


# 透明消息显示窗口
class MessageBox(QWidget):
    def __init__(self):
        super().__init__()
        # 设置窗口标志：无边框、置顶、工具窗口（不在任务栏显示）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                          Qt.WindowType.WindowStaysOnTopHint | 
                          Qt.WindowType.Tool)
        # 设置窗口透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 创建主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # 创建内容标签（支持文本、图像、gif）
        self.content_label = QLabel()
        self.content_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_label.setWordWrap(True)  # 自动换行
        # 样式将通过update_background_style方法设置
        layout.addWidget(self.content_label)
        
        # 设置初始大小和位置
        self.resize(600, 150)
        self.move_to_default_position()
        
        # 用于窗口拖动
        self.dragging = False
        self.drag_position = None
        
        # 用于流式文本显示
        self.current_text = ""
        self.stream_timer = QTimer()
        self.stream_timer.timeout.connect(self.update_stream_display)
        self.stream_queue = []
        self.stream_index = 0
        
        # LLM流式输出相关
        self.llm_stream_active = False
        self.llm_content_buffer = ""
        
        # 当前显示的媒体类型
        self.current_media_type = "text"  # text, image, gif
        self.current_movie = None
        
        # 背景透明度设置 (0.0-1.0)
        self.background_opacity = 0.5
        self.update_background_style()

    def update_background_style(self):
        """更新背景样式"""
        opacity_int = int(self.background_opacity * 255)
        self.content_label.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-size: 18pt;
                background-color: rgba(0, 0, 0, {self.background_opacity});
                border-radius: 15px;
                padding: 15px;
                min-height: 50px;
            }}
        """)
    
    def set_background_opacity(self, opacity):
        """设置背景透明度 (0.0-1.0)"""
        self.background_opacity = max(0.0, min(1.0, opacity))
        self.update_background_style()

    def move_to_default_position(self):
        """移动到默认位置（屏幕右上角）"""
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 50, 50)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            event.accept()

    def show_text(self, text, stream=False):
        """显示文本内容"""
        self.stop_current_media()
        self.current_media_type = "text"
        
        if stream:
            self.start_stream_text(text)
        else:
            self.current_text = text
            display_text = re.sub(r'\s+', ' ', text.strip())
            self.content_label.setText(display_text)
            self.adjust_window_size()
    
    def show_image(self, image_path):
        """显示图像"""
        self.stop_current_media()
        self.current_media_type = "image"
        
        try:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # 获取原始图像尺寸
                original_size = pixmap.size()
                # 设置最大显示尺寸
                max_width = 600
                max_height = 400
                
                # 如果图像太大，按比例缩放
                if original_size.width() > max_width or original_size.height() > max_height:
                    scaled_pixmap = pixmap.scaled(max_width, max_height, 
                                                 Qt.AspectRatioMode.KeepAspectRatio, 
                                                 Qt.TransformationMode.SmoothTransformation)
                else:
                    scaled_pixmap = pixmap
                
                self.content_label.setPixmap(scaled_pixmap)
                self.content_label.setText("")  # 清除文本
                # 调整标签大小以适应图像
                self.content_label.setFixedSize(scaled_pixmap.size())
                self.adjust_window_size()
            else:
                self.show_text(f"无法加载图像: {image_path}")
        except Exception as e:
            self.show_text(f"图像加载错误: {str(e)}")
    
    def show_gif(self, gif_path):
        """显示GIF动画"""
        self.stop_current_media()
        self.current_media_type = "gif"
        
        try:
            self.current_movie = QMovie(gif_path)
            if self.current_movie.isValid():
                # 启动电影以获取正确的尺寸信息
                self.current_movie.start()
                self.current_movie.stop()
                
                # 获取GIF原始尺寸
                original_size = self.current_movie.scaledSize()
                
                # 如果获取的尺寸无效，使用默认尺寸
                if original_size.width() <= 0 or original_size.height() <= 0:
                    original_size = self.current_movie.frameRect().size()
                    if original_size.width() <= 0 or original_size.height() <= 0:
                        # 使用默认尺寸
                        original_size.setWidth(300)
                        original_size.setHeight(200)
                
                # 设置最大显示尺寸
                max_width = 600
                max_height = 400
                
                # 如果GIF太大，按比例缩放
                if original_size.width() > max_width or original_size.height() > max_height:
                    scaled_size = original_size.scaled(max_width, max_height, 
                                                      Qt.AspectRatioMode.KeepAspectRatio)
                    self.current_movie.setScaledSize(scaled_size)
                    final_size = scaled_size
                else:
                    final_size = original_size
                
                # 确保尺寸为正数
                if final_size.width() <= 0:
                    final_size.setWidth(300)
                if final_size.height() <= 0:
                    final_size.setHeight(200)
                
                self.content_label.setMovie(self.current_movie)
                self.content_label.setText("")  # 清除文本
                # 调整标签大小以适应GIF
                self.content_label.setFixedSize(final_size)
                self.current_movie.start()
                self.adjust_window_size()
            else:
                self.show_text(f"无法加载GIF: {gif_path}")
        except Exception as e:
            self.show_text(f"GIF加载错误: {str(e)}")
    
    def start_stream_text(self, text):
        """开始流式文本显示"""
        self.stream_queue = list(text)
        self.stream_index = 0
        self.current_text = ""
        self.content_label.setText("")
        self.stream_timer.start(50)  # 每50ms显示一个字符
    
    def update_text(self, text):
        """更新文本内容（用于流式显示）"""
        if text:
            # 累积文本
            self.current_text += text
            # 移除多余的空白字符
            display_text = re.sub(r'\s+', ' ', self.current_text.strip())
            self.content_label.setText(display_text)
            # 调整窗口大小以适应文本
            self.adjustSize()
    
    def update_stream_display(self):
        """更新流式显示"""
        if self.stream_index < len(self.stream_queue):
            self.current_text += self.stream_queue[self.stream_index]
            display_text = re.sub(r'\s+', ' ', self.current_text.strip())
            self.content_label.setText(display_text)
            self.stream_index += 1
            self.adjust_window_size()
        else:
            self.stream_timer.stop()
    
    def stop_current_media(self):
        """停止当前媒体播放"""
        if self.current_movie:
            self.current_movie.stop()
            self.current_movie = None
        self.stream_timer.stop()
        self.content_label.clear()
        # 重置标签大小限制
        self.content_label.setMinimumSize(0, 0)
        self.content_label.setMaximumSize(16777215, 16777215)
    
    def adjust_window_size(self):
        """调整窗口大小以适应内容"""
        # 清除之前的尺寸限制
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        
        if self.current_media_type == "text":
            # 文本模式：恢复标签的自动调整
            self.content_label.setMinimumSize(0, 0)
            self.content_label.setMaximumSize(16777215, 16777215)
            # 动态调整大小
            self.adjustSize()
            # 设置合理的最小尺寸
            min_width = max(400, self.sizeHint().width())
            min_height = max(100, self.sizeHint().height())
            self.setMinimumSize(min_width, min_height)
            self.resize(min_width, min_height)
        else:  # 图像或GIF
            # 媒体模式：根据内容标签大小调整窗口
            content_size = self.content_label.size()
            # 添加布局边距
            margin = 20  # 10px * 2 (左右边距)
            window_width = content_size.width() + margin
            window_height = content_size.height() + margin
            self.setFixedSize(window_width, window_height)
                
    def clear_content(self):
        """清除当前内容"""
        self.stop_current_media()
        self.current_text = ""
        self.content_label.clear()
        self.adjustSize()
    
    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件 - 清除内容"""
        self.clear_content()
        event.accept()


# 透明字幕窗口（保持原有功能）
class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__()
        # 设置窗口标志：无边框、置顶、工具窗口（不在任务栏显示）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                          Qt.WindowType.WindowStaysOnTopHint | 
                          Qt.WindowType.Tool)
        # 设置窗口透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 创建主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # 创建字幕标签
        self.subtitle_label = QLabel()
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)  # 自动换行
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 24pt;
                background-color: rgba(0, 0, 0, 0.5);
                border-radius: 10px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.subtitle_label)
        
        # 设置初始大小和位置
        self.resize(800, 100)
        self.move_to_default_position()
        
        # 用于窗口拖动
        self.dragging = False
        self.drag_position = None
        
        # 用于累积文本
        self.current_text = ""

    def move_to_default_position(self):
        """移动到默认位置（屏幕底部居中）"""
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2,
                 screen.height() - self.height() - 50)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            event.accept()

    def update_text(self, text):
        """更新字幕文本"""
        if text:
            # 累积文本
            self.current_text += text
            # 移除多余的空白字符
            display_text = re.sub(r'\s+', ' ', self.current_text.strip())
            self.subtitle_label.setText(display_text)
            # 调整窗口大小以适应文本
            self.adjustSize()
            # 确保窗口不会太窄
            if self.width() < 800:
                self.setFixedWidth(800)
                
    def clear_text(self):
        """清除当前文本"""
        self.current_text = ""
        self.subtitle_label.setText("")
        self.adjustSize()
    
    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件"""
        self.clear_text()
        event.accept()

if __name__ == "__main__":
    import sys
    llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.8,
    timeout=None,
    max_retries=2,
    api_key=os.getenv("OPENAI_API_KEY"),  # if you prefer to pass api key in directly instaed of using env vars
    base_url=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
    # organization="...",
    # other params...
)
    app = QApplication(sys.argv)
    
    # 创建消息框实例
    message_box = MessageBox()
    message_box.show()
    
    for chunk in llm.stream([HumanMessage("你好，请介绍一下你自己，并且详细说明你的功能和特点。")]):
        if chunk.content:
            # 清除之前的内容并显示累积的文本
            message_box.update_text(chunk.content)
            # 处理Qt事件循环以更新UI
            app.processEvents()
    
    sys.exit(app.exec())
