import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, asdict, field
from enum import Enum


class InteractionMode(Enum):
    """交互模式枚举"""
    VOICE = "voice"
    TEXT = "text"


class InterruptMode(Enum):
    """打断模式枚举"""
    NO_INTERRUPT = 0  # 不打断
    IMMEDIATE_INTERRUPT = 1  # 听到声音立即打断
    WAIT_END_INTERRUPT = 2  # 等待说话结束后打断


class AgentMode(Enum):
    """AI模式枚举"""
    AGENT = "agent"  # 智能体模式
    SIMPLE_CHAT = "simple_chat"  # 简单聊天模式


@dataclass
class PerformanceMetrics:
    """性能指标统计"""
    speech_detect_time: Optional[float] = None  # 检测到说话的时间
    transcription_complete_time: Optional[float] = None  # 转录完成时间
    aife_response_time: Optional[float] = None  # AI响应时间
    audio_start_time: Optional[float] = None  # 音频开始播放时间
    received_first_chunk_time: Optional[float] = None  # 收到第一个文本块时间
    received_all_chunks_time: Optional[float] = None  # 收到所有文本块时间
    
    # 延迟统计
    transcription_delay: Optional[float] = None  # 语音转录延迟
    aife_delay: Optional[float] = None  # AI处理延迟
    tts_delay: Optional[float] = None  # TTS开始播放延迟
    total_response_delay: Optional[float] = None  # 总响应延迟
    
    def calculate_delays(self):
        """计算各种延迟"""
        try:
            if self.speech_detect_time and self.transcription_complete_time:
                self.transcription_delay = self.transcription_complete_time - self.speech_detect_time
            
            if self.aife_response_time and self.transcription_complete_time:
                self.aife_delay = self.aife_response_time - self.transcription_complete_time
            
            if self.audio_start_time and self.aife_response_time:
                self.tts_delay = self.audio_start_time - self.aife_response_time
            
            if self.audio_start_time and self.transcription_complete_time:
                self.total_response_delay = self.audio_start_time - self.transcription_complete_time
        except Exception:
            pass  # 计算失败时忽略


@dataclass
class ComponentStatus:
    """组件状态信息"""
    # ASR (ear) 状态
    ear_running: bool = False
    ear_connected: bool = False
    ear_enabled: bool = True
    is_hearing: bool = False  # 是否正在听到声音
    
    # TTS (mouth) 状态
    mouth_enabled: bool = True
    is_speaking: bool = False  # 是否正在说话
    is_playing: bool = False  # TTS是否正在播放
    
    # Agent 状态
    agent_initialized: bool = False
    agent_mode: AgentMode = AgentMode.AGENT
    
    # Body (Live2D) 状态
    body_initialized: bool = False
    current_expression: Optional[str] = None
    current_motion: Optional[str] = None
    
    # Brain 状态
    brain_awake: bool = False
    interrupt_mode: InterruptMode = InterruptMode.NO_INTERRUPT
    interaction_mode: InteractionMode = InteractionMode.VOICE
    sync_subtitle: bool = False


@dataclass
class InteractionState:
    """交互状态信息"""
    current_user_input: Optional[str] = None
    last_text: str = ""  # 最后一次识别的文本
    current_response: str = ""  # 当前累积的AI响应
    last_response: str = ""  # 最后一次完整的AI响应
    pending_transcription: Optional[str] = None  # 等待处理的转录文本
    
    # 时间相关
    last_interaction_time: Optional[float] = None  # 最后一次用户输入时间
    last_response_time: Optional[float] = None  # 最后一次agent响应完成时间
    is_free: bool = False  # 是否空闲
    free_threshold: float = 40.0  # 空闲判断阈值(秒)
    
    # 打断相关
    interrupted: bool = False
    received_first_chunk: bool = False
    
    # 自主行为相关
    is_autonomous: bool = False  # 是否处于自主行为模式
    
    def update_interaction_time(self):
        """更新最后交互时间 - 当用户发送输入时调用"""
        self.last_interaction_time = time.time()
        self.is_free = False
    
    def update_response_time(self):
        """更新最后响应时间 - 当agent响应完成时调用"""
        self.last_response_time = time.time()
        self.is_free = False
    
    def check_free_status(self) -> bool:
        """检查是否处于空闲状态 - 基于最后一次agent响应时间判断
        
        只有当空闲时间达到阈值且当前不是空闲状态时，才会将is_free设为true
        这确保了is_free只在满足条件时变为true，而不会重复设置
        
        在自主行为期间，不会重新设置is_free为true，避免重复触发
        注意：is_hearing和is_speaking状态检查需要在FeelState层面进行
        """
        if self.last_response_time is None:
            # 如果从未有过响应，不算作空闲
            return self.is_free
        
        # 如果正在执行自主行为，不重新设置is_free为true
        if self.is_autonomous:
            return self.is_free
        
        time_since_last_response = time.time() - self.last_response_time
        
        # 只有当空闲时间达到阈值且当前不是空闲状态时，才设为true
        if time_since_last_response > self.free_threshold and not self.is_free:
            self.is_free = True
        
        return self.is_free
    
    def mark_free_triggered(self):
        """标记空闲状态已被触发 - 在agent处理后立即调用
        
        这会立即将is_free设为false，确保handle_free_time不会重复触发
        同时设置is_autonomous为true，表示正在执行自主行为
        """
        self.is_free = False
        self.is_autonomous = True
        # 注意：不在这里更新last_response_time，应该在响应完成时更新
    
    def mark_autonomous_completed(self):
        """标记自主行为完成 - 在自主行为响应完成时调用
        
        重置is_autonomous状态，允许下次空闲检查
        """
        self.is_autonomous = False


@dataclass
class EnvironmentState:
    """环境状态信息"""
    # 系统配置
    config_loaded: bool = False
    log_level: str = "INFO"
    
    # 网络状态
    asr_server_connected: bool = False
    tts_server_connected: bool = False
    llm_connected: bool = False
    
    # 资源状态
    audio_device_available: bool = True
    model_loaded: bool = False
    
    # 错误状态
    error_count: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    
    def add_error(self, error_msg: str):
        """添加错误记录"""
        self.error_count += 1
        self.last_error = error_msg
        self.last_error_time = time.time()


@dataclass
class FeelState:
    """数字人的完整状态信息统计类 - 实时统计各种状态信息"""
    
    # 子状态组件
    component_status: ComponentStatus = field(default_factory=ComponentStatus)
    interaction_state: InteractionState = field(default_factory=InteractionState)
    environment_state: EnvironmentState = field(default_factory=EnvironmentState)
    performance_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    
    # 统计信息
    total_interactions: int = 0
    total_speech_time: float = 0.0
    total_response_time: float = 0.0
    startup_time: Optional[float] = field(default_factory=time.time)
    
    # 动态属性(为了向后兼容)
    @property
    def current_user_input(self) -> Optional[str]:
        return self.interaction_state.current_user_input
    
    @current_user_input.setter
    def current_user_input(self, value: Optional[str]):
        self.interaction_state.current_user_input = value
        if value:
            self.total_interactions += 1
    
    @property
    def is_free(self) -> bool:
        """返回当前的空闲状态
        
        注意：这里直接返回is_free的值，而不是调用check_free_status()
        check_free_status()应该由定时器或其他机制定期调用来更新状态
        """
        return self.interaction_state.is_free
    
    @property
    def is_hearing(self) -> bool:
        return self.component_status.is_hearing
    
    @property
    def is_speaking(self) -> bool:
        return self.component_status.is_speaking
    
    @property
    def is_playing(self) -> bool:
        return self.component_status.is_playing
    
    @property
    def last_interaction_time(self) -> Optional[float]:
        return self.interaction_state.last_interaction_time
    
    @property
    def last_response(self) -> str:
        return self.interaction_state.last_response
    
    @last_response.setter
    def last_response(self, value: str):
        self.interaction_state.last_response = value
    
    def mark_free_triggered(self):
        """标记空闲状态已被触发 - 在agent处理后立即调用"""
        self.interaction_state.mark_free_triggered()
    
    def mark_autonomous_completed(self):
        """标记自主行为完成"""
        self.interaction_state.mark_autonomous_completed()
    
    def check_free_status(self) -> bool:
        """检查是否处于空闲状态 - 代理方法
        
        首先调用InteractionState的check_free_status，然后检查所有非空闲状态
        在任何忙碌状态下都强制设为非空闲状态
        """
        # 先调用基础的空闲状态检查
        is_free = self.interaction_state.check_free_status()
        
        # 检查所有非空闲状态
        is_busy = (
            self.component_status.is_hearing or 
            self.component_status.is_speaking or
            bool(self.interaction_state.current_user_input) or
            bool(self.interaction_state.current_response) or
            bool(self.interaction_state.pending_transcription) or
            self.interaction_state.is_autonomous
        )
        
        if is_busy:
            self.interaction_state.is_free = False
            return False
        
        return is_free
    
    def update_interaction_time(self):
        """更新最后交互时间 - 当用户发送输入时调用"""
        self.interaction_state.update_interaction_time()
    
    # ============= 状态更新方法 =============
    
    def update_component_status(self, component: str, **kwargs):
        """更新组件状态，并在TTS播放结束时重置空闲计时起点"""
        # 检查is_playing变化（mouth组件）
        if component == "mouth" and "is_playing" in kwargs:
            old_is_playing = self.component_status.is_playing
            new_is_playing = kwargs["is_playing"]
            if old_is_playing and not new_is_playing:
                # TTS播放刚刚结束，重置last_response_time为空闲计时起点
                self.interaction_state.last_response_time = time.time()
        # 正常更新组件状态
        if component == "ear":
            for key, value in kwargs.items():
                if hasattr(self.component_status, key):
                    setattr(self.component_status, key, value)
        elif component == "mouth":
            for key, value in kwargs.items():
                if hasattr(self.component_status, key):
                    setattr(self.component_status, key, value)
        elif component == "agent":
            for key, value in kwargs.items():
                if hasattr(self.component_status, key):
                    setattr(self.component_status, key, value)
        elif component == "body":
            for key, value in kwargs.items():
                if hasattr(self.component_status, key):
                    setattr(self.component_status, key, value)
        elif component == "brain":
            for key, value in kwargs.items():
                if hasattr(self.component_status, key): 
                    setattr(self.component_status, key, value)
    
    def update_interaction_state(self, **kwargs):
        """更新交互状态"""
        for key, value in kwargs.items():
            if hasattr(self.interaction_state, key):
                setattr(self.interaction_state, key, value)
    
    def update_environment_state(self, **kwargs):
        """更新环境状态"""
        for key, value in kwargs.items():
            if hasattr(self.environment_state, key):
                setattr(self.environment_state, key, value)
    
    def update_performance_metrics(self, **kwargs):
        """更新性能指标"""
        for key, value in kwargs.items():
            if hasattr(self.performance_metrics, key):
                setattr(self.performance_metrics, key, value)
        # 自动计算延迟
        self.performance_metrics.calculate_delays()
    
    # ============= 便捷状态检查方法 =============
    
    def is_system_ready(self) -> bool:
        """检查系统是否就绪"""
        return (self.component_status.brain_awake and 
                self.component_status.ear_running and 
                self.component_status.agent_initialized)
    
    def is_in_conversation(self) -> bool:
        """检查是否正在对话中"""
        return (self.component_status.is_hearing or 
                self.component_status.is_speaking or 
                self.component_status.is_playing)
    
    def can_accept_input(self) -> bool:
        """检查是否可以接受输入"""
        if self.component_status.interaction_mode == InteractionMode.VOICE:
            return (self.component_status.ear_enabled and 
                    self.component_status.ear_running)
        else:  # TEXT mode
            return not self.component_status.is_speaking
    
    def get_uptime(self) -> float:
        """获取运行时间(秒)"""
        if self.startup_time:
            return time.time() - self.startup_time
        return 0.0
    
    def get_idle_time(self) -> float:
        """获取空闲时间(秒) - 从最后一次响应完成到现在的时间
        
        数字人的空闲时间定义：
        - 起点：数字人完成最后一次响应的时间(last_response_time)
        - 终点：当前时间
        - 返回值：只有在真正空闲时才返回计算出的时间差，忙碌时返回0
        
        忙碌状态包括：
        - 正在听音(is_hearing)或说话(is_speaking)  
        - 有用户输入待处理(current_user_input)
        - 正在生成响应(current_response)
        - 有转录待处理(pending_transcription)
        - 处于自主行为模式(is_autonomous)
        
        注意：忙碌时返回0，但不重置last_response_time，保持时间基准点
        """
        # 检查所有非空闲状态
        is_busy = (
            self.component_status.is_hearing or 
            self.component_status.is_speaking or
            bool(self.interaction_state.current_user_input) or
            bool(self.interaction_state.current_response) or
            bool(self.interaction_state.pending_transcription) or
            self.interaction_state.is_autonomous
        )
        
        if is_busy:
            # 忙碌时返回0，但不重置last_response_time
            return 0.0
        
        # 只有在真正空闲时才计算从last_response_time开始的时间
        if self.interaction_state.last_response_time:
            return time.time() - self.interaction_state.last_response_time
        
        # 如果从未有过响应，返回系统运行时间
        return self.get_uptime()
    
    def get_error_rate(self) -> float:
        """获取错误率"""
        if self.total_interactions == 0:
            return 0.0
        return self.environment_state.error_count / self.total_interactions
    
    # ============= 状态报告方法 =============
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            "system_ready": self.is_system_ready(),
            "in_conversation": self.is_in_conversation(),
            "can_accept_input": self.can_accept_input(),
            "is_free": self.is_free,
            "uptime": self.get_uptime(),
            "idle_time": self.get_idle_time(),
            "total_interactions": self.total_interactions,
            "error_rate": self.get_error_rate(),
            "component_status": asdict(self.component_status),
            "interaction_state": asdict(self.interaction_state),
            "environment_state": asdict(self.environment_state),
            "performance_metrics": asdict(self.performance_metrics)
        }
    
    def get_component_summary(self) -> Dict[str, str]:
        """获取组件状态摘要"""
        return {
            "brain": "🧠 awake" if self.component_status.brain_awake else "😴 sleeping",
            "ear": ("👂 listening" if self.component_status.is_hearing 
                   else "👂 ready" if self.component_status.ear_enabled 
                   else "🔇 muted"),
            "mouth": ("🗣️ speaking" if self.component_status.is_speaking 
                     else "🔇 muted" if not self.component_status.mouth_enabled 
                     else "🤐 quiet"),
            "agent": ("🤖 agent mode" if self.component_status.agent_mode == AgentMode.AGENT 
                     else "💬 chat mode"),
            "body": ("💃 active" if self.component_status.body_initialized 
                    else "🧍 static"),
            "interaction": ("🗣️ voice" if self.component_status.interaction_mode == InteractionMode.VOICE 
                           else "⌨️ text")
        }
    
    def get_performance_summary(self) -> Dict[str, Optional[float]]:
        """获取性能摘要"""
        metrics = self.performance_metrics
        return {
            "transcription_delay_ms": metrics.transcription_delay * 1000 if metrics.transcription_delay else None,
            "ai_processing_delay_ms": metrics.aife_delay * 1000 if metrics.aife_delay else None,
            "tts_start_delay_ms": metrics.tts_delay * 1000 if metrics.tts_delay else None,
            "total_response_delay_ms": metrics.total_response_delay * 1000 if metrics.total_response_delay else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def __str__(self) -> str:
        """状态字符串表示"""
        components = self.get_component_summary()
        status_line = " | ".join([f"{k}: {v}" for k, v in components.items()])
        
        uptime_str = f"⏱️ {self.get_uptime():.1f}s"
        interactions_str = f"💬 {self.total_interactions}"
        
        if self.is_free:
            idle_str = f"😴 idle {self.get_idle_time():.1f}s"
        else:
            idle_str = "🔥 active"
        
        return f"FeelState: {status_line} | {uptime_str} | {interactions_str} | {idle_str}"


                