import os
from dataclasses import dataclass, asdict
from Body.api_models import Live2DState
from typing import Dict, Any, Optional, Union
import OpenGL.GL as gl
from PyQt6.QtCore import QTimerEvent, Qt, QTimer, QTime, pyqtSignal, QObject, QMutex, QThread
from PyQt6.QtGui import QMouseEvent, QCursor, QWheelEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication
from Head.mouth import TTS_GSV, TTS_realtime
from Message.MessageBox import MessageBox, MessageSignals
import win32gui
import win32con
import win32api
import live2d.v3 as live2d
from dotmap import DotMap
import toml
# 读取toml的live2d配置
config = DotMap(toml.load("config.toml"))
FPS = config.live2d.FPS
lipSyncN = config.live2d.lipSyncN
class Live2DSignals(QObject):
    """信号类，用于线程间通信"""
    model_load_requested = pyqtSignal(str)
    motion_requested = pyqtSignal(str, int, int)  # group, index, priority
    expression_requested = pyqtSignal(str)
    parameter_requested = pyqtSignal(str, float, float)  # id, value, weight
    parameter_add_requested = pyqtSignal(str, float)
    parameter_save_requested = pyqtSignal(str, float, float)
    parameter_add_save_requested = pyqtSignal(str, float)
    scale_requested = pyqtSignal(float)
    position_requested = pyqtSignal(int, int)
    offset_requested = pyqtSignal(float, float)
    rotation_requested = pyqtSignal(float)
    eye_tracking_requested = pyqtSignal(bool)
    window_config_requested = pyqtSignal(dict)
    hit_test_requested = pyqtSignal(float, float, bool)
    area_hit_requested = pyqtSignal(str, float, float)
    drag_requested = pyqtSignal(float, float)
    part_opacity_requested = pyqtSignal(int, float)
    part_screen_color_requested = pyqtSignal(int, float, float, float, float)
    part_multiply_color_requested = pyqtSignal(int, float, float, float, float)
    drawable_screen_color_requested = pyqtSignal(int, float, float, float, float)
    drawable_multiply_color_requested = pyqtSignal(int, float, float, float, float)
    expression_add_requested = pyqtSignal(str)
    expression_remove_requested = pyqtSignal(str)
    extra_motion_load_requested = pyqtSignal(str, int, str)
    parameters_load_requested = pyqtSignal()
    parameters_save_requested = pyqtSignal()
    motions_stop_requested = pyqtSignal()
    parameters_reset_requested = pyqtSignal()
    pose_reset_requested = pyqtSignal()
    expressions_reset_requested = pyqtSignal()
    state_updated = pyqtSignal(dict)
    # 返回信号
    hit_test_result = pyqtSignal(list)
    area_hit_result = pyqtSignal(bool)
    parameter_info_result = pyqtSignal(dict)
    model_info_result = pyqtSignal(dict)

class TransparentLive2dWindow(QOpenGLWidget):
    """
    独立的透明Live2D窗口，通过信号接收外部控制指令
    """
    def __init__(
    self, 
    signals: Live2DSignals, 
    mouth: Optional[Union[TTS_GSV, TTS_realtime]] = None
) -> None:
        super().__init__()
        self.signals = signals
        self.state = Live2DState()
        self.mutex = QMutex()
        self.SetAndAdd =SetAndAddController()
        
        # 创建MessageSignals并初始化MessageBox
        self.msgbox_signals = MessageSignals()
        self.msgbox = MessageBox(self.msgbox_signals)
        
        #self.wavHandler = WavHandler()
        self.mouth = mouth
        # 用于存储API查询结果
        self.last_hit_test_result = []
        self.last_area_hit_result = False
        self.parameter_info = {}
        self.model_info = {}
        
        self._init_window()
        self._init_model()
        self._init_eye_tracking()
        self._init_drag()
        self._connect_signals()

    def _init_window(self):
        screen = QGuiApplication.primaryScreen().geometry()
        self.screen_width = int(screen.width()/3.5) # 设置窗口宽度为屏幕宽度的3.5分之一，防止全屏问题
        self.screen_height = screen.height() # 设置窗口高度为屏幕高度
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(self.screen_width, self.screen_height)
        self.systemScale = QGuiApplication.primaryScreen().devicePixelRatio()

    def _init_model(self):
        self.model: live2d.Model | None = None
        self.model_renderer_created = False

    def _init_eye_tracking(self):
        self.eye_tracking_timer = QTimer()
        self.eye_tracking_timer.timeout.connect(self.updateEyeTracking)
        self.eye_tracking_timer.start(16)

    def _init_drag(self):
        self.dragging_window = False
        self.last_mouse_pos = None

    def _connect_signals(self):
        """连接外部控制信号"""
        self.signals.model_load_requested.connect(self.load_model_slot)
        self.signals.motion_requested.connect(self.start_motion_slot)
        self.signals.expression_requested.connect(self.set_expression_slot)
        self.signals.parameter_requested.connect(self.set_parameter_slot)
        self.signals.parameter_add_requested.connect(self.add_parameter_slot)
        self.signals.parameter_save_requested.connect(self.set_and_save_parameter_slot)
        self.signals.parameter_add_save_requested.connect(self.add_and_save_parameter_slot)
        self.signals.scale_requested.connect(self.set_scale_slot)
        self.signals.position_requested.connect(self.set_position_slot)
        self.signals.offset_requested.connect(self.set_offset_slot)
        self.signals.rotation_requested.connect(self.set_rotation_slot)
        self.signals.eye_tracking_requested.connect(self.set_eye_tracking_slot)
        self.signals.window_config_requested.connect(self.configure_window_slot)
        self.signals.hit_test_requested.connect(self.hit_test_slot)
        self.signals.area_hit_requested.connect(self.area_hit_slot)
        self.signals.drag_requested.connect(self.drag_slot)
        self.signals.part_opacity_requested.connect(self.set_part_opacity_slot)
        self.signals.part_screen_color_requested.connect(self.set_part_screen_color_slot)
        self.signals.part_multiply_color_requested.connect(self.set_part_multiply_color_slot)
        self.signals.drawable_screen_color_requested.connect(self.set_drawable_screen_color_slot)
        self.signals.drawable_multiply_color_requested.connect(self.set_drawable_multiply_color_slot)
        self.signals.expression_add_requested.connect(self.add_expression_slot)
        self.signals.expression_remove_requested.connect(self.remove_expression_slot)
        self.signals.extra_motion_load_requested.connect(self.load_extra_motion_slot)
        self.signals.parameters_load_requested.connect(self.load_parameters_slot)
        self.signals.parameters_save_requested.connect(self.save_parameters_slot)
        self.signals.motions_stop_requested.connect(self.stop_all_motions_slot)
        self.signals.parameters_reset_requested.connect(self.reset_parameters_slot)
        self.signals.pose_reset_requested.connect(self.reset_pose_slot)
        self.signals.expressions_reset_requested.connect(self.reset_expressions_slot)

    # 原有的槽函数...
    def load_model_slot(self, model_path: str):
        """加载模型槽函数"""
        self.mutex.lock()
        try:
            self._load_model(model_path)
            self.state.model_path = model_path
            self._update_model_info()
            self._emit_state_update()
        finally:
            self.mutex.unlock()

    def start_motion_slot(self, group: str, index: int, priority: int = 3):
        """播放动作槽函数"""
        if not self.model:
            return
        try:
            if index == -1:
                self.model.StartRandomMotion()
            else:
                self.model.StartMotion(group, index, priority)
        except Exception as e:
            print(f"Motion error: {e}")

    def set_expression_slot(self, expression_id: str):
        """设置表情槽函数"""
        if not self.model:
            return
        try:
            if expression_id:
                self.model.SetExpression(expression_id)
            else:
                self.model.SetRandomExpression()
        except Exception as e:
            print(f"Expression error: {e}")

    # 新增的槽函数
    def set_parameter_slot(self, parameter_id: str, value: float, weight: float = 1.0):
        """设置参数槽函数"""
        if not self.model:
            return
        try:
            self.SetAndAdd.set_id = parameter_id
            self.SetAndAdd.set_value = value
            self.SetAndAdd.set_weight = weight
            self.SetAndAdd.isrunning = True
            self.state.parameters[parameter_id] = value
            self._emit_state_update()
        except Exception as e:
            print(f"Parameter error: {e}")

    def add_parameter_slot(self, parameter_id: str, value: float):
        """添加参数值槽函数"""
        if not self.model:
            return
        try:
            self.SetAndAdd.add_id = parameter_id
            self.SetAndAdd.add_value = value
            self.SetAndAdd.isrunning = True
            current_value = self.state.parameters.get(parameter_id, 0.0)
            self.state.parameters[parameter_id] = current_value + value
            self._emit_state_update()
        except Exception as e:
            print(f"Add parameter error: {e}")

    def set_and_save_parameter_slot(self, parameter_id: str, value: float, weight: float = 1.0):
        """设置并保存参数槽函数"""
        if not self.model:
            return
        try:
            self.model.SetAndSaveParameterValueById(parameter_id, value, weight)
            self.state.parameters[parameter_id] = value
            self._emit_state_update()
        except Exception as e:
            print(f"Set and save parameter error: {e}")

    def add_and_save_parameter_slot(self, parameter_id: str, value: float):
        """添加并保存参数值槽函数"""
        if not self.model:
            return
        try:
            self.model.AddAndSaveParameterValueById(parameter_id, value)
            current_value = self.state.parameters.get(parameter_id, 0.0)
            self.state.parameters[parameter_id] = current_value + value
            self._emit_state_update()
        except Exception as e:
            print(f"Add and save parameter error: {e}")

    def set_scale_slot(self, scale: float):
        """设置缩放槽函数"""
        if not self.model:
            return
        self.state.model_scale = max(0.2, min(2.0, scale))
        self.model.SetScale(self.state.model_scale)
        self._emit_state_update()

    def set_position_slot(self, x: int, y: int):
        """设置位置槽函数"""
        self.move(x, y)
        self.state.window_x = x
        self.state.window_y = y
        self._emit_state_update()

    def set_offset_slot(self, x: float, y: float):
        """设置偏移槽函数"""
        if not self.model:
            return
        try:
            self.model.SetOffset(x, y)
        except Exception as e:
            print(f"Set offset error: {e}")

    def set_rotation_slot(self, degrees: float):
        """设置旋转槽函数"""
        if not self.model:
            return
        try:
            self.model.Rotate(degrees)
        except Exception as e:
            print(f"Set rotation error: {e}")

    def set_eye_tracking_slot(self, enabled: bool):
        """设置眼部追踪槽函数"""
        self.state.eye_tracking_enabled = enabled
        self._emit_state_update()

    def configure_window_slot(self, config: dict):
        """配置窗口槽函数"""
        if config.get("width") and config.get("height"):
            self.resize(config["width"], config["height"])
        if config.get("x") is not None and config.get("y") is not None:
            self.move(config["x"], config["y"])

    def hit_test_slot(self, x: float, y: float, top_only: bool = False):
        """碰撞检测槽函数"""
        if not self.model:
            self.last_hit_test_result = []
            self.signals.hit_test_result.emit([])
            return
        try:
            result = self.model.HitPart(x, y, top_only)
            self.last_hit_test_result = result or []
            self.signals.hit_test_result.emit(self.last_hit_test_result)
        except Exception as e:
            print(f"Hit test error: {e}")
            self.last_hit_test_result = []
            self.signals.hit_test_result.emit([])

    def area_hit_slot(self, area_name: str, x: float, y: float):
        """区域碰撞检测槽函数"""
        if not self.model:
            self.last_area_hit_result = False
            self.signals.area_hit_result.emit(False)
            return
        try:
            result = self.model.IsAreaHit(area_name, x, y)
            self.last_area_hit_result = result
            self.signals.area_hit_result.emit(result)
        except Exception as e:
            print(f"Area hit test error: {e}")
            self.last_area_hit_result = False
            self.signals.area_hit_result.emit(False)

    def drag_slot(self, x: float, y: float):
        """拖拽槽函数"""
        if not self.model:
            return
        try:
            self.model.Drag(x, y)
        except Exception as e:
            print(f"Drag error: {e}")

    def set_part_opacity_slot(self, part_index: int, opacity: float):
        """设置部件透明度槽函数"""
        if not self.model:
            return
        try:
            self.model.SetPartOpacity(part_index, opacity)
        except Exception as e:
            print(f"Set part opacity error: {e}")

    def set_part_screen_color_slot(self, part_index: int, r: float, g: float, b: float, a: float):
        """设置部件屏幕颜色槽函数"""
        if not self.model:
            return
        try:
            self.model.SetPartScreenColor(part_index, r, g, b, a)
        except Exception as e:
            print(f"Set part screen color error: {e}")

    def set_part_multiply_color_slot(self, part_index: int, r: float, g: float, b: float, a: float):
        """设置部件乘法颜色槽函数"""
        if not self.model:
            return
        try:
            self.model.SetPartMultiplyColor(part_index, r, g, b, a)
        except Exception as e:
            print(f"Set part multiply color error: {e}")

    def set_drawable_screen_color_slot(self, drawable_index: int, r: float, g: float, b: float, a: float):
        """设置可绘制对象屏幕颜色槽函数"""
        if not self.model:
            return
        try:
            self.model.SetDrawableScreenColor(drawable_index, r, g, b, a)
        except Exception as e:
            print(f"Set drawable screen color error: {e}")

    def set_drawable_multiply_color_slot(self, drawable_index: int, r: float, g: float, b: float, a: float):
        """设置可绘制对象乘法颜色槽函数"""
        if not self.model:
            return
        try:
            self.model.SetDrawableMultiplyColor(drawable_index, r, g, b, a)
        except Exception as e:
            print(f"Set drawable multiply color error: {e}")

    def add_expression_slot(self, expression_id: str):
        """添加表情槽函数"""
        if not self.model:
            return
        try:
            self.model.AddExpression(expression_id)
            self._update_model_info()
        except Exception as e:
            print(f"Add expression error: {e}")

    def remove_expression_slot(self, expression_id: str):
        """移除表情槽函数"""
        if not self.model:
            return
        try:
            self.model.RemoveExpression(expression_id)
            self._update_model_info()
        except Exception as e:
            print(f"Remove expression error: {e}")

    def load_extra_motion_slot(self, group: str, index: int, motion_json_path: str):
        """加载额外动作槽函数"""
        if not self.model:
            return
        try:
            self.model.LoadExtraMotion(group, index, motion_json_path)
            self._update_model_info()
        except Exception as e:
            print(f"Load extra motion error: {e}")

    def load_parameters_slot(self):
        """加载参数槽函数"""
        if not self.model:
            return
        try:
            self.model.LoadParameters()
        except Exception as e:
            print(f"Load parameters error: {e}")

    def save_parameters_slot(self):
        """保存参数槽函数"""
        if not self.model:
            return
        try:
            self.model.SaveParameters()
        except Exception as e:
            print(f"Save parameters error: {e}")

    def stop_all_motions_slot(self):
        """停止所有动作槽函数"""
        if not self.model:
            return
        try:
            self.model.StopAllMotions()
        except Exception as e:
            print(f"Stop all motions error: {e}")

    def reset_parameters_slot(self):
        """重置所有参数槽函数"""
        if not self.model:
            return
        try:
            self.model.ResetAllParameters()
            self.state.parameters.clear()
            self._emit_state_update()
        except Exception as e:
            print(f"Reset parameters error: {e}")

    def reset_pose_slot(self):
        """重置姿势槽函数"""
        if not self.model:
            return
        try:
            self.model.ResetPose()
        except Exception as e:
            print(f"Reset pose error: {e}")

    def reset_expressions_slot(self):
        """重置表情槽函数"""
        if not self.model:
            return
        try:
            self.model.ResetExpressions()
        except Exception as e:
            print(f"Reset expressions error: {e}")

    def _update_model_info(self):
        """更新模型信息"""
        if not self.model:
            return
        
        try:
            # 获取可用动作组
            self.state.available_motions = self.model.GetMotions()
            # 获取可用表情
            self.state.available_expressions = self.model.GetExpressions()
            print(f"Available motions: {self.state.available_motions}, Available expressions: {self.state.available_expressions}")
            # 获取模型详细信息
            self.model_info = {
                "name": self.state.model_path,
                "parameter_ids": self.model.GetParameterIds(),
                "part_ids": self.model.GetPartIds(),
                "drawable_ids": self.model.GetDrawableIds(),
                "canvas_size": self.model.GetCanvasSize(),
                "canvas_size_pixel": self.model.GetCanvasSizePixel(),
                "pixels_per_unit": self.model.GetPixelsPerUnit(),
                "mvp_matrix": self.model.GetMvp(),
                "motion_finished": self.model.IsMotionFinished(),
                "expressions": self.state.available_expressions,
                "motions": self.state.available_motions
            }
            self.signals.model_info_result.emit(self.model_info)
        except Exception as e:
            print(f"Failed to get model info: {e}")

    def _emit_state_update(self):
        """发送状态更新信号"""
        state_dict = asdict(self.state)
        self.signals.state_updated.emit(state_dict)

    # 原有的其他方法保持不变...
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
        if self.state.model_path:
            self._load_model(self.state.model_path)
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
        if self.model:
            if self.model_renderer_created:
                self.model.DestroyRenderer()
            self.model = None
        
        self.model = live2d.Model()
        if not os.path.exists(model_path):
            print(f"Warning: Model file not found: {model_path}")
            for root, dirs, files in os.walk('.'):
                for file in files:
                    if file.endswith('.model3.json') or file.endswith('.model.json'):
                        model_path = os.path.join(root, file)
                        print(f"Using model file: {model_path}")
                        break
                if model_path != "Haru/Haru.model3.json":
                    break
        try:
            self.model.LoadModelJson(model_path)
            self.model.CreateRenderer()
            self.model_renderer_created = True
            self.model.SetScale(self.state.model_scale)
            print(f"Model loaded: {model_path}")
        except Exception as e:
            print(f"Failed to load model: {e}")
            self.model = None
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
            live2d.clearBuffer()
            self.model.Update(1.0/FPS)
            if self.mouth.stream.is_playing():
                self.model.SetParameterValueById("ParamMouthOpenY", self.mouth.stream.GetRms() * lipSyncN, 1)
            if self.SetAndAdd.isrunning:
                if self.SetAndAdd.set_id:
                    self.model.SetParameterValueById(self.SetAndAdd.set_id, self.SetAndAdd.set_value, self.SetAndAdd.set_weight)
                if self.SetAndAdd.add_id:
                    self.model.AddParameterValueById(self.SetAndAdd.add_id, self.SetAndAdd.add_value)
                self.SetAndAdd.stop()
            self.model.Draw()

    def updateEyeTracking(self):
        if not self.model or not self.state.eye_tracking_enabled:
            return
        try:
            # 获取全局鼠标位置
            global_mouse_pos = QCursor.pos()
            window_pos = self.mapFromGlobal(global_mouse_pos)
            
            # 获取窗口相对坐标
            window_x = window_pos.x()
            window_y = window_pos.y()

            # 应用 Drag 更新
            self.model.Drag(window_x, window_y)
            self.model.UpdateDrag(1.0/FPS)  # 使用与 paintGL 相同的时间步长
        except Exception as e:
            print(f"Eye tracking error: {e}")
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
            delta = event.angleDelta().y()
            scale_factor = 1.1 if delta > 0 else 0.9
            new_scale = self.state.model_scale * scale_factor
            self.set_scale_slot(new_scale)
        except Exception as e:
            print(f"Wheel event error: {e}")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = int(event.position().x()), int(event.position().y())
            try:
                if part_ids := self.model.HitPart(x, y):
                    print(f"Clicked parts: {part_ids}")
                if self.model.IsAreaHit("Head", x, y):
                    self.set_expression_slot("")  # Random expression
                    print("Clicked Head - Random Expression")
                elif self.model.IsAreaHit("Body", x, y):
                    self.start_motion_slot("TapBody", -1)  # Random motion
                    print("Clicked Body - Random Motion")
            except Exception as e:
                print(f"Hit test error: {e}")
        elif event.button() == Qt.MouseButton.RightButton:
            self.dragging_window = True
            self.last_mouse_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.dragging_window = False
            self.last_mouse_pos = None

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
            self.start_motion_slot("", -1)
        elif event.key() == Qt.Key.Key_R:
            self.set_scale_slot(1.0)
        elif event.key() == Qt.Key.Key_T:
            self.set_eye_tracking_slot(not self.state.eye_tracking_enabled)

    def closeEvent(self, event):
        try:
            if self.model:
                if self.model_renderer_created:
                    self.model.DestroyRenderer()
                self.model = None
            live2d.glRelease()
            live2d.dispose()
        except Exception as e:
            print(f"清理资源时出错: {e}")
        super().closeEvent(event)

    def get_current_state(self) -> dict:
        """获取当前状态"""
        return asdict(self.state)

    def get_parameter_info(self, parameter_id: str) -> dict:
        """获取参数信息"""
        if not self.model:
            return {}
        try:
            param_ids = self.model.GetParameterIds()
            if parameter_id not in param_ids:
                return {}
            
            index = param_ids.index(parameter_id)
            return {
                "id": parameter_id,
                "index": index,
                "current_value": self.model.GetParameterValue(index),
                "default_value": self.model.GetParameterDefaultValue(index),
                "minimum_value": self.model.GetParameterMinimumValue(index),
                "maximum_value": self.model.GetParameterMaximumValue(index)
            }
        except Exception as e:
            print(f"Get parameter info error: {e}")
            return {}
        

class SetAndAddController:
    """用于设置和添加参数的类"""
    def __init__(self):
        self.set_id = ""
        self.set_value = 0.0
        self.set_weight = 1.0
        self.add_id = ""
        self.add_value = 0.0
        self.isrunning = False
    
    def start(self):
        self.isrunning = True
        self.set_id = ""
        self.set_value = 0.0
        self.set_weight = 1.0
        self.add_id = ""
        self.add_value = 0.0
    
    def stop(self):
        self.isrunning = False
        self.set_id = ""
        self.set_value = 0.0
        self.set_weight = 1.0
        self.add_id = ""
        self.add_value = 0.0
