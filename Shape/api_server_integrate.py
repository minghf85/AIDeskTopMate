import os
import threading
import json
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, asdict
from fastapi import FastAPI, HTTPException
from fastapi import Body
from pydantic import BaseModel
import uvicorn
from Shape import api_models
import OpenGL.GL as gl
import numpy as np
from PIL import Image
from PyQt6.QtCore import QTimerEvent, Qt, QTimer, QTime, pyqtSignal, QObject, QMutex, QThread
from PyQt6.QtGui import QMouseEvent, QCursor, QWheelEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication
import win32gui
import win32con
import win32api

import live2d.v3 as live2d

# API Models
class ModelInfo(BaseModel):
    name: str
    path: str
    scale: float = 1.0
    position: tuple[int, int] = (0, 0)

class MotionRequest(BaseModel):
    group: str
    index: int = -1  # -1 for random
    priority: int = 3

class ExpressionRequest(BaseModel):
    expression_id: Optional[str] = None  # None for random

class ParameterRequest(BaseModel):
    parameter_id: str
    value: float
    weight: float = 1.0

class ParameterAddRequest(BaseModel):
    parameter_id: str
    value: float

class ParameterSaveRequest(BaseModel):
    parameter_id: str
    value: float
    weight: float = 1.0

class TransformRequest(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    scale: Optional[float] = None
    rotation: Optional[float] = None

class HitTestRequest(BaseModel):
    x: float
    y: float
    top_only: bool = False

class RotationRequest(BaseModel):
    degrees: float

class AreaHitRequest(BaseModel):
    area_name: str
    x: float
    y: float

class DragRequest(BaseModel):
    x: float
    y: float

class PartOpacityRequest(BaseModel):
    part_index: int
    opacity: float

class PartColorRequest(BaseModel):
    part_index: int
    r: float
    g: float
    b: float
    a: float

class DrawableColorRequest(BaseModel):
    drawable_index: int
    r: float
    g: float
    b: float
    a: float

class WindowConfig(BaseModel):
    width: Optional[int] = None
    height: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None
    always_on_top: Optional[bool] = None
    transparent: Optional[bool] = None

class ExtraMotionRequest(BaseModel):
    group: str
    index: int
    motion_json_path: str

# Data Classes
@dataclass
class Live2DState:
    model_path: str = ""
    model_scale: float = 1.0
    eye_tracking_enabled: bool = True
    tracking_strength: float = 1.0
    window_x: int = 0
    window_y: int = 0
    parameters: Dict[str, float] = None
    available_motions: Dict[str, int] = None
    available_expressions: List[str] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
        if self.available_motions is None:
            self.available_motions = {}
        if self.available_expressions is None:
            self.available_expressions = []

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
    def __init__(self, signals: Live2DSignals) -> None:
        super().__init__()
        self.signals = signals
        self.state = Live2DState()
        self.mutex = QMutex()
        
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
        self.screen_width = screen.width()
        self.screen_height = screen.height()
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
                self.model.StartRandomMotion(group, priority)
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
            self.model.SetParameterValueById(parameter_id, value, weight)
            self.state.parameters[parameter_id] = value
            self._emit_state_update()
        except Exception as e:
            print(f"Parameter error: {e}")

    def add_parameter_slot(self, parameter_id: str, value: float):
        """添加参数值槽函数"""
        if not self.model:
            return
        try:
            self.model.AddParameterValueById(parameter_id, value)
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
                "parameter_ids": self.model.GetParameterIds(),
                "part_ids": self.model.GetPartIds(),
                "drawable_ids": self.model.GetDrawableIds(),
                "canvas_size": self.model.GetCanvasSize(),
                "canvas_size_pixel": self.model.GetCanvasSizePixel(),
                "pixels_per_unit": self.model.GetPixelsPerUnit(),
                "mvp_matrix": self.model.GetMvp(),
                "motion_finished": self.model.IsMotionFinished()
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
            self.model.Update(1.0/60.0)
            self.model.Draw()

    def updateEyeTracking(self):
        if not self.model or not self.state.eye_tracking_enabled:
            return
        try:
            global_mouse_pos = QCursor.pos()
            look_x = (global_mouse_pos.x() / self.screen_width) * 2.0 - 1.0
            look_y = -((global_mouse_pos.y() / self.screen_height) * 2.0 - 1.0)
            look_x = max(-1.0, min(1.0, look_x)) * self.state.tracking_strength
            look_y = max(-1.0, min(1.0, look_y)) * self.state.tracking_strength
            self.model.SetParameterValueById("ParamAngleX", look_x * 30)
            self.model.SetParameterValueById("ParamAngleY", look_y * 30)
            self.model.SetParameterValueById("ParamEyeBallX", look_x)
            self.model.SetParameterValueById("ParamEyeBallY", look_y)
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
            self.start_motion_slot("TapBody", -1)
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

class Live2DController:
    """Live2D控制器，管理窗口和API服务"""
    def __init__(self, host="127.0.0.1", port=8000):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Live2D Controller API", version="1.0.0")
        self.signals = Live2DSignals()
        self.window: Optional[TransparentLive2dWindow] = None
        self.current_state = Live2DState()
        
        # 连接状态更新信号
        self.signals.state_updated.connect(self._update_state)
        
        self._setup_routes()

    def _update_state(self, state_dict: dict):
        """更新当前状态"""
        for key, value in state_dict.items():
            if hasattr(self.current_state, key):
                setattr(self.current_state, key, value)

    def _setup_routes(self):
        """设置API路由"""
        
        @self.app.get("/")
        async def root():
            return {"message": "Live2D Controller API", "version": "1.0.0"}

        @self.app.get("/status")
        async def get_status():
            """获取当前状态"""
            return {
                "status": "running" if self.window and self.window.isVisible() else "stopped",
                "state": asdict(self.current_state)
            }

        # 模型相关API
        @self.app.post("/model/load")
        async def load_model(model_info: ModelInfo):
            """加载模型"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            if not os.path.exists(model_info.path):
                raise HTTPException(status_code=404, detail=f"Model file not found: {model_info.path}")
            
            self.signals.model_load_requested.emit(model_info.path)
            if model_info.scale != 1.0:
                self.signals.scale_requested.emit(model_info.scale)
            if model_info.position != (0, 0):
                self.signals.position_requested.emit(model_info.position[0], model_info.position[1])
            
            return {"message": f"Loading model: {model_info.name}", "path": model_info.path}

        @self.app.get("/model/info")
        async def get_model_info():
            """获取模型信息"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            return self.window.model_info

        @self.app.get("/models/list")
        async def list_models():
            """列出可用的模型文件"""
            models = []
            for root, dirs, files in os.walk('.'):
                for file in files:
                    if file.endswith('.model3.json') or file.endswith('.model.json'):
                        full_path = os.path.join(root, file)
                        models.append({
                            "name": os.path.splitext(file)[0],
                            "path": full_path.replace('\\', '/'),
                            "directory": root.replace('\\', '/')
                        })
            return {"models": models}

        # 动作相关API
        @self.app.post("/motion/play")
        async def play_motion(motion: MotionRequest):
            """播放动作"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.motion_requested.emit(motion.group, motion.index, motion.priority)
            return {"message": f"Playing motion: {motion.group}", "index": motion.index, "priority": motion.priority}

        @self.app.post("/motion/load-extra")
        async def load_extra_motion(extra_motion: ExtraMotionRequest):
            """加载额外动作"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            if not os.path.exists(extra_motion.motion_json_path):
                raise HTTPException(status_code=404, detail=f"Motion file not found: {extra_motion.motion_json_path}")
            
            self.signals.extra_motion_load_requested.emit(extra_motion.group, extra_motion.index, extra_motion.motion_json_path)
            return {"message": f"Loading extra motion: {extra_motion.group}[{extra_motion.index}]", "path": extra_motion.motion_json_path}

        @self.app.post("/motion/stop-all")
        async def stop_all_motions():
            """停止所有动作"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.motions_stop_requested.emit()
            return {"message": "All motions stopped"}

        @self.app.get("/motion/is-finished")
        async def is_motion_finished():
            """检查动作是否完成"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            
            try:
                finished = self.window.model.IsMotionFinished()
                return {"finished": finished}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error checking motion status: {str(e)}")

        # 表情相关API
        @self.app.post("/expression/set")
        async def set_expression(expression: ExpressionRequest):
            """设置表情"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            expr_id = expression.expression_id or ""
            self.signals.expression_requested.emit(expr_id)
            return {"message": f"Setting expression: {expr_id or 'random'}"}

        @self.app.post("/expression/add")
        async def add_expression(expression_id: str):
            """添加表情"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.expression_add_requested.emit(expression_id)
            return {"message": f"Adding expression: {expression_id}"}

        @self.app.delete("/expression/remove")
        async def remove_expression(expression_id: str):
            """移除表情"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.expression_remove_requested.emit(expression_id)
            return {"message": f"Removing expression: {expression_id}"}

        @self.app.post("/expression/reset")
        async def reset_expressions():
            """重置所有表情"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.expressions_reset_requested.emit()
            return {"message": "Expressions reset"}

        # 参数相关API
        @self.app.post("/parameter/set")
        async def set_parameter(param: ParameterRequest):
            """设置参数"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameter_requested.emit(param.parameter_id, param.value, param.weight)
            return {"message": f"Setting parameter: {param.parameter_id} = {param.value}", "weight": param.weight}

        @self.app.post("/parameter/add")
        async def add_parameter(param: ParameterAddRequest):
            """添加参数值"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameter_add_requested.emit(param.parameter_id, param.value)
            return {"message": f"Adding to parameter: {param.parameter_id} += {param.value}"}

        @self.app.post("/parameter/set-and-save")
        async def set_and_save_parameter(param: ParameterSaveRequest):
            """设置并保存参数"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameter_save_requested.emit(param.parameter_id, param.value, param.weight)
            return {"message": f"Setting and saving parameter: {param.parameter_id} = {param.value}", "weight": param.weight}

        @self.app.post("/parameter/add-and-save")
        async def add_and_save_parameter(param: ParameterAddRequest):
            """添加并保存参数值"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameter_add_save_requested.emit(param.parameter_id, param.value)
            return {"message": f"Adding and saving parameter: {param.parameter_id} += {param.value}"}

        @self.app.get("/parameter/info/{parameter_id}")
        async def get_parameter_info(parameter_id: str):
            """获取参数信息"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            
            info = self.window.get_parameter_info(parameter_id)
            if not info:
                raise HTTPException(status_code=404, detail=f"Parameter not found: {parameter_id}")
            
            return info

        @self.app.get("/parameters/list")
        async def list_parameters():
            """获取所有参数ID"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            
            try:
                param_ids = self.window.model.GetParameterIds()
                return {"parameter_ids": param_ids}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error getting parameters: {str(e)}")

        @self.app.post("/parameters/load")
        async def load_parameters():
            """加载参数"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameters_load_requested.emit()
            return {"message": "Parameters loaded"}

        @self.app.post("/parameters/save")
        async def save_parameters():
            """保存参数"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameters_save_requested.emit()
            return {"message": "Parameters saved"}

        @self.app.post("/parameters/reset")
        async def reset_parameters():
            """重置所有参数"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.parameters_reset_requested.emit()
            return {"message": "All parameters reset"}

        # 变换相关API
        @self.app.post("/transform/set")
        async def set_transform(transform: TransformRequest):
            """设置变换"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            changes = []
            if transform.scale is not None:
                if not (0.2 <= transform.scale <= 2.0):
                    raise HTTPException(status_code=400, detail="Scale must be between 0.2 and 2.0")
                self.signals.scale_requested.emit(transform.scale)
                changes.append(f"scale: {transform.scale}")
            
            if transform.x is not None and transform.y is not None:
                self.signals.offset_requested.emit(transform.x, transform.y)
                changes.append(f"offset: ({transform.x}, {transform.y})")
            
            if transform.rotation is not None:
                self.signals.rotation_requested.emit(transform.rotation)
                changes.append(f"rotation: {transform.rotation}°")
            
            return {"message": f"Transform updated: {', '.join(changes)}"}

        @self.app.post("/scale/set")
        async def set_scale(scale: float):
            """设置缩放"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            if not (0.2 <= scale <= 2.0):
                raise HTTPException(status_code=400, detail="Scale must be between 0.2 and 2.0")
            
            self.signals.scale_requested.emit(scale)
            return {"message": f"Setting scale: {scale}"}

        @self.app.post("/position/set")
        async def set_position(x: int, y: int):
            """设置窗口位置"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.position_requested.emit(x, y)
            return {"message": f"Setting position: ({x}, {y})"}

        @self.app.post("/offset/set")
        async def set_offset(
            x: float = Body(...),  # 显式声明从请求体获取
            y: float = Body(...)
        ):
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            self.signals.offset_requested.emit(x, y)
            return {"message": f"Setting offset: ({x}, {y})"}
        @self.app.post("/rotation/set")
        async def set_rotation(request: RotationRequest):  # 接收 JSON 对象
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            self.signals.rotation_requested.emit(request.degrees)
            return {"message": f"Setting rotation: {request.degrees}°"}

        # 碰撞检测相关API
        @self.app.post("/hit-test/parts")
        async def hit_test_parts(hit_test: HitTestRequest):
            """部件碰撞检测"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.hit_test_requested.emit(hit_test.x, hit_test.y, hit_test.top_only)
            # 等待结果
            import time
            time.sleep(0.01)  # 短暂等待信号处理
            return {"hit_parts": self.window.last_hit_test_result}

        @self.app.post("/hit-test/area")
        async def hit_test_area(area_hit: AreaHitRequest):
            """区域碰撞检测"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.area_hit_requested.emit(area_hit.area_name, area_hit.x, area_hit.y)
            # 等待结果
            import time
            time.sleep(0.01)  # 短暂等待信号处理
            return {"area_name": area_hit.area_name, "hit": self.window.last_area_hit_result}

        @self.app.post("/drag")
        async def drag_model(drag: DragRequest):
            """拖拽模型"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.drag_requested.emit(drag.x, drag.y)
            return {"message": f"Dragging to: ({drag.x}, {drag.y})"}

        # 部件和可绘制对象相关API
        @self.app.get("/parts/list")
        async def list_parts():
            """获取所有部件ID"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            
            try:
                part_ids = self.window.model.GetPartIds()
                return {"part_ids": part_ids}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error getting parts: {str(e)}")

        @self.app.post("/part/opacity")
        async def set_part_opacity(opacity_req: PartOpacityRequest):
            """设置部件透明度"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            if not (0.0 <= opacity_req.opacity <= 1.0):
                raise HTTPException(status_code=400, detail="Opacity must be between 0.0 and 1.0")
            
            self.signals.part_opacity_requested.emit(opacity_req.part_index, opacity_req.opacity)
            return {"message": f"Setting part {opacity_req.part_index} opacity: {opacity_req.opacity}"}

        @self.app.post("/part/screen-color")
        async def set_part_screen_color(color_req: PartColorRequest):
            """设置部件屏幕颜色"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.part_screen_color_requested.emit(
                color_req.part_index, color_req.r, color_req.g, color_req.b, color_req.a
            )
            return {"message": f"Setting part {color_req.part_index} screen color: RGBA({color_req.r}, {color_req.g}, {color_req.b}, {color_req.a})"}

        @self.app.post("/part/multiply-color")
        async def set_part_multiply_color(color_req: PartColorRequest):
            """设置部件乘法颜色"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.part_multiply_color_requested.emit(
                color_req.part_index, color_req.r, color_req.g, color_req.b, color_req.a
            )
            return {"message": f"Setting part {color_req.part_index} multiply color: RGBA({color_req.r}, {color_req.g}, {color_req.b}, {color_req.a})"}

        @self.app.get("/drawables/list")
        async def list_drawables():
            """获取所有可绘制对象ID"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            
            try:
                drawable_ids = self.window.model.GetDrawableIds()
                return {"drawable_ids": drawable_ids}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error getting drawables: {str(e)}")

        @self.app.post("/drawable/screen-color")
        async def set_drawable_screen_color(color_req: DrawableColorRequest):
            """设置可绘制对象屏幕颜色"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.drawable_screen_color_requested.emit(
                color_req.drawable_index, color_req.r, color_req.g, color_req.b, color_req.a
            )
            return {"message": f"Setting drawable {color_req.drawable_index} screen color: RGBA({color_req.r}, {color_req.g}, {color_req.b}, {color_req.a})"}

        @self.app.post("/drawable/multiply-color")
        async def set_drawable_multiply_color(color_req: DrawableColorRequest):
            """设置可绘制对象乘法颜色"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.drawable_multiply_color_requested.emit(
                color_req.drawable_index, color_req.r, color_req.g, color_req.b, color_req.a
            )
            return {"message": f"Setting drawable {color_req.drawable_index} multiply color: RGBA({color_req.r}, {color_req.g}, {color_req.b}, {color_req.a})"}

        # 姿势相关API
        @self.app.post("/pose/reset")
        async def reset_pose():
            """重置姿势"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.pose_reset_requested.emit()
            return {"message": "Pose reset"}

        # 眼部追踪API
        @self.app.post("/eye-tracking/toggle")
        async def toggle_eye_tracking(enabled: bool):
            """切换眼部追踪"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            self.signals.eye_tracking_requested.emit(enabled)
            return {"message": f"Eye tracking: {'enabled' if enabled else 'disabled'}"}

        # 窗口配置API
        @self.app.post("/window/configure")
        async def configure_window(config: WindowConfig):
            """配置窗口"""
            if not self.window:
                raise HTTPException(status_code=400, detail="Window not initialized")
            
            config_dict = config.dict(exclude_none=True)
            self.signals.window_config_requested.emit(config_dict)
            return {"message": "Window configured", "config": config_dict}

        # 画布信息API
        @self.app.get("/canvas/info")
        async def get_canvas_info():
            """获取画布信息"""
            if not self.window or not self.window.model:
                raise HTTPException(status_code=400, detail="No model loaded")
            
            try:
                canvas_size = self.window.model.GetCanvasSize()
                canvas_size_pixel = self.window.model.GetCanvasSizePixel()
                pixels_per_unit = self.window.model.GetPixelsPerUnit()
                mvp_matrix = self.window.model.GetMvp()
                
                return {
                    "canvas_size": canvas_size,
                    "canvas_size_pixel": canvas_size_pixel,
                    "pixels_per_unit": pixels_per_unit,
                    "mvp_matrix": mvp_matrix
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error getting canvas info: {str(e)}")
            
        # 口型同步


    def start_window(self, qt_app: QApplication):
        """启动窗口"""
        self.window = TransparentLive2dWindow(self.signals)
        self.window.show()
        return self.window

    def start_api_server(self):
        """启动API服务器"""
        def run_server():
            uvicorn.run(self.app, host=self.host, port=self.port)
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        print(f"API Server started on http://{self.host}:{self.port}")
        return server_thread

    def start(self, qt_app: QApplication):
        """启动完整系统"""
        window = self.start_window(qt_app)
        self.start_api_server()
        return window

# 使用示例
if __name__ == "__main__":
    import sys
    
    # 创建Qt应用
    app = QApplication(sys.argv)
    
    # 创建控制器
    controller = Live2DController(host="127.0.0.1", port=8000)
    
    # 启动系统
    window = controller.start(app)
    
    print("Live2D Controller started!")
    print("API Documentation: http://127.0.0.1:8000/docs")
    print("Press Ctrl+C to stop the server")
    
    # 运行Qt应用
    sys.exit(app.exec())