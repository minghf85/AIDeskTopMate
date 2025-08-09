from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel
from dataclasses import dataclass, asdict
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