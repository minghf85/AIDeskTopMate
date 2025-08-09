import os
import threading
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, asdict
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Body
import uvicorn
from tlw import TransparentLive2dWindow, Live2DSignals, Live2DState
from api_models import (ModelInfo, MotionRequest, ExpressionRequest, ParameterRequest, 
                        ParameterAddRequest, ParameterSaveRequest, TransformRequest, 
                        HitTestRequest, RotationRequest, AreaHitRequest, DragRequest, 
                        ExtraMotionRequest, DrawableColorRequest, WindowConfig, 
                        PartOpacityRequest, PartColorRequest)
from PyQt6.QtWidgets import QApplication
import live2d.v3 as live2d
from live2d.v3 import StandardParams
import numpy as np
import io
import time
LipsyncN = 0.04

class Live2DController:
    """Live2D控制器，管理窗口和API服务"""
    def __init__(self, host="127.0.0.1", port=8000):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Live2D Controller API", version="1.0.0")
        self.signals = Live2DSignals()
        self.window: Optional[TransparentLive2dWindow] = None
        self.model: Optional[live2d.Model] = self.window.model if self.window else None
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
            self.model = self.window.model
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
            
        @self.app.websocket("/lipsync/stream")
        async def lipsync_stream(websocket: WebSocket):
            await websocket.accept()
            p = None
            stream = None
            
            try:
                
                
                while True:
                    # 接收音频数据
                    data = await websocket.receive_bytes()
                        
                    # 通过信号发送音频数据（原功能保留）
                    self.signals.wav_requested.emit(data)
                    
            except WebSocketDisconnect:
                print("WebSocket连接断开")
            except Exception as e:
                print(f"WebSocket音频流处理错误: {e}")
                await websocket.close(code=1011, reason=str(e))
            finally:
                # 清理资源
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                if p is not None:
                    p.terminate()
                print("音频流处理结束")
        @self.app.post("/lipsync/file")
        async def lipsync_file(file: str):
            try:
                self.signals.wav_file_requested.emit(file)
            except Exception as e:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Error processing file: {str(e)}"
                )
        @self.app.post("/lipsync/interrupt")
        async def lipsync_interrupt():
            try:
                self.signals.wav_interrupted.emit("")
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Error interrupting lipsync: {str(e)}"
                )

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

    def cleanup(self):
        """清理资源"""
        if self.window:
            self.window.close()
        if hasattr(self, 'server_thread'):
            # 停止FastAPI服务器
            import requests
            try:
                requests.get(f"http://{self.host}:{self.port}/shutdown")
            except:
                pass

    def start(self, qt_app: QApplication):
        """启动完整系统"""
        window = self.start_window(qt_app)
        self.server_thread = self.start_api_server()
        # 连接应用退出信号
        qt_app.aboutToQuit.connect(self.cleanup)
        return window