import os

import OpenGL.GL as gl
import numpy as np
from PIL import Image
from PyQt6.QtCore import QTimerEvent, Qt, QTimer, QTime
from PyQt6.QtGui import QMouseEvent, QCursor, QWheelEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication
import win32gui
import win32con
import win32api

import live2d.v3 as live2d
# import live2d.v2 as live2d

def callback():
    print("motion end")



class TransparentLive2dWindow(QOpenGLWidget):
    """
    结构化的透明Live2D窗口，便于扩展和维护。
    """
    def __init__(self) -> None:
        super().__init__()
        self._init_window()
        self._init_model()
        self._init_eye_tracking()
        self._init_drag()

    def _init_window(self):
        screen = QGuiApplication.primaryScreen().geometry()
        self.screen_width = screen.width()
        self.screen_height = screen.height()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(self.screen_width, self.screen_height)
        self.systemScale = QGuiApplication.primaryScreen().devicePixelRatio()

    def _init_model(self):
        self.model: live2d.LAppModel | None = None
        self.model_scale = 1.0
        self.tracking_strength = 1.0

    def _init_eye_tracking(self):
        self.eye_tracking_enabled = True
        self.eye_tracking_timer = QTimer()
        self.eye_tracking_timer.timeout.connect(self.updateEyeTracking)
        self.eye_tracking_timer.start(16)

    def _init_drag(self):
        self.dragging_window = False
        self.last_mouse_pos = None

    def showEvent(self, event):
        super().showEvent(event)
        self.make_window_transparent()

    def make_window_transparent(self):
        try:
            hwnd = int(self.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            style = style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style = ex_style | win32con.WS_EX_LAYERED
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                 win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            print("窗口透明效果已应用")
        except Exception as e:
            print(f"应用透明效果失败: {e}")

    def initializeGL(self) -> None:
        live2d.init()
        live2d.glInit()
        self._setup_opengl()
        self._load_model()
        self.startTimer(int(1000 / 120))

    def _setup_opengl(self):
        try:
            while gl.glGetError() != gl.GL_NO_ERROR:
                pass
            gl.glViewport(0, 0, self.screen_width, self.screen_height)
            gl.glMatrixMode(gl.GL_PROJECTION)
            gl.glLoadIdentity()
            gl.glOrtho(0, self.screen_width, self.screen_height, 0, -1, 1)
            gl.glMatrixMode(gl.GL_MODELVIEW)
            gl.glLoadIdentity()
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glDisable(gl.GL_LIGHTING)
            print("高质量OpenGL设置已启用")
        except Exception as e:
            print(f"设置OpenGL时出错: {e}")

    def _load_model(self, model_path="Haru/Haru.model3.json"):
        self.model = live2d.LAppModel()
        if not os.path.exists(model_path):
            print(f"Warning: Model file not found: {model_path}")
            for root, dirs, files in os.walk('.'):
                for file in files:
                    if file.endswith('.model3.json') or file.endswith('.model.json'):
                        model_path = os.path.join(root, file)
                        print(f"Using model file: {model_path}")
                        break
                if model_path != ("Haru/Haru.model3.json" if live2d.LIVE2D_VERSION == 3 else "v2/kasumi2/kasumi2.model.json"):
                    break
        try:
            self.model.LoadModelJson(model_path)
            print(f"Model loaded: {model_path}")
        except Exception as e:
            print(f"Failed to load model: {e}")
            return
        self.model.Resize(self.screen_width, self.screen_height)

    def resizeGL(self, w: int, h: int) -> None:
        if self.model:
            self.model.Resize(w, h)

    def paintGL(self) -> None:
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        if self.model:
            self.model.Update()
            self.model.Draw()

    def updateEyeTracking(self):
        if not self.model or not self.eye_tracking_enabled:
            return
        try:
            global_mouse_pos = QCursor.pos()
            look_x = (global_mouse_pos.x() / self.screen_width) * 2.0 - 1.0
            look_y = -((global_mouse_pos.y() / self.screen_height) * 2.0 - 1.0)
            look_x = max(-1.0, min(1.0, look_x)) * self.tracking_strength
            look_y = max(-1.0, min(1.0, look_y)) * self.tracking_strength
            self.model.SetParameterValue("ParamAngleX", look_x * 30)
            self.model.SetParameterValue("ParamAngleY", look_y * 30)
            self.model.SetParameterValue("ParamEyeBallX", look_x)
            self.model.SetParameterValue("ParamEyeBallY", look_y)
        except Exception:
            pass

    def timerEvent(self, a0: QTimerEvent | None) -> None:
        if not self.isVisible():
            return
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.model:
            return
        mouse_pos = event.position()
        mouse_x, mouse_y = int(mouse_pos.x()), int(mouse_pos.y())
        try:
            if self.model.HitTest("Body", mouse_x, mouse_y) or self.model.HitTest("Head", mouse_x, mouse_y):
                delta = event.angleDelta().y()
                scale_factor = 1.1 if delta > 0 else 0.9
                self.model_scale *= scale_factor
                self.model_scale = max(0.2, min(2.0, self.model_scale))
                self.model.SetScale(self.model_scale)
                print(f"Model scale: {self.model_scale:.2f}")
        except Exception as e:
            print(f"Wheel event error: {e}")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = int(event.position().x()), int(event.position().y())
            try:
                if part_ids := self.model.HitPart(x, y):
                    print(f"Clicked parts: {part_ids}")
                if self.model.HitTest("Head", x, y):
                    self.model.SetRandomExpression()
                    print("Clicked Head - Random Expression")
                elif self.model.HitTest("Body", x, y):
                    self.model.StartRandomMotion("TapBody", 3)
                    print("Clicked Body - Random Motion")
            except Exception as e:
                print(f"Hit test error: {e}")
        elif event.button() == Qt.MouseButton.RightButton:
            self.dragging_window = True
            self.last_mouse_pos = event.globalPosition().toPoint()
            print("开始拖拽窗口")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.dragging_window = False
            self.last_mouse_pos = None
            print("停止拖拽窗口")

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging_window and self.last_mouse_pos is not None:
            current_pos = event.globalPosition().toPoint()
            delta = current_pos - self.last_mouse_pos
            new_pos = self.pos() + delta
            self.move(new_pos)
            self.last_mouse_pos = current_pos

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Space:
            try:
                self.model.StartRandomMotion("TapBody", 3)
            except:
                pass
        elif event.key() == Qt.Key.Key_R:
            self.model_scale = 1.0
            if self.model:
                self.model.SetScale(self.model_scale)
        elif event.key() == Qt.Key.Key_T:
            self.eye_tracking_enabled = not self.eye_tracking_enabled
            print(f"Eye tracking: {'Enabled' if self.eye_tracking_enabled else 'Disabled'}")

    def closeEvent(self, event):
        try:
            if self.model:
                self.model = None
            live2d.dispose()
        except Exception as e:
            print(f"清理资源时出错: {e}")
        super().closeEvent(event)

class Live2dController:
    """使用fastapi构建一个Live2dController类，能够通过api加载更换控制live2d模型和获取相关信息，尽量把live2d.pyi中的模型的功能全部实现"""
    def __init__(self):
        self.model = None
        self.window = None

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    win = TransparentLive2dWindow()
    win.show()
    app.exec()
