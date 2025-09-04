import sys
import time
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, 
    QGridLayout, QPushButton, QTextEdit, QScrollArea,
    QFrame, QSizePolicy, QApplication
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QPalette, QColor
from Head.Brain.feel import FeelState, InteractionMode, InterruptMode, AgentMode


class StatusUpdateThread(QThread):
    """状态更新线程"""
    status_updated = pyqtSignal(dict)
    
    def __init__(self, feel_state: FeelState):
        super().__init__()
        self.feel_state = feel_state
        self.running = True
        
    def run(self):
        while self.running:
            try:
                status = self.feel_state.get_status_summary()
                self.status_updated.emit(status)
                self.msleep(500)  # 每500ms更新一次
            except Exception as e:
                print(f"状态更新线程错误: {e}")
                self.msleep(1000)
    
    def stop(self):
        self.running = False
        self.quit()
        self.wait()


class StatusLabel(QLabel):
    """状态标签组件"""
    def __init__(self, text="", status_type="normal"):
        super().__init__(text)
        self.status_type = status_type
        self.setFont(QFont("Consolas", 9))
        self.setWordWrap(True)
        self.update_style()
    
    def update_style(self):
        if self.status_type == "good":
            self.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif self.status_type == "warning":
            self.setStyleSheet("color: #FF9800; font-weight: bold;")
        elif self.status_type == "error":
            self.setStyleSheet("color: #F44336; font-weight: bold;")
        else:
            self.setStyleSheet("color: #333333;")
    
    def set_status(self, text: str, status_type: str = "normal"):
        self.setText(text)
        self.status_type = status_type
        self.update_style()


class BrainMonitorPanel(QWidget):
    """Brain状态监控面板"""
    
    def __init__(self, feel_state: FeelState, parent=None):
        super().__init__(parent)
        self.feel_state = feel_state
        self.update_thread = None
        self.init_ui()
        self.start_monitoring()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("AI Desktop Mate - Brain Monitor")
        self.setGeometry(100, 100, 600, 800)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        # 设置样式
        self.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                font-family: 'Microsoft YaHei', Arial, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        
        # 主布局
        main_layout = QVBoxLayout()
        
        # 标题和控制按钮
        header_layout = QHBoxLayout()
        title_label = QLabel("🧠 Brain Status Monitor")
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1976D2; margin: 10px;")
        
        self.hide_btn = QPushButton("隐藏")
        self.hide_btn.clicked.connect(self.hide)
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.hide_btn)
        
        main_layout.addLayout(header_layout)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # 系统概览
        self.create_system_overview(scroll_layout)
        
        # 组件状态
        self.create_component_status(scroll_layout)
        
        # 交互状态
        self.create_interaction_status(scroll_layout)
        
        # 环境状态
        self.create_environment_status(scroll_layout)
        
        # 性能指标
        self.create_performance_metrics(scroll_layout)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)
        
        self.setLayout(main_layout)
    
    def create_system_overview(self, layout):
        """创建系统概览区域"""
        group = QGroupBox("📊 系统概览")
        grid = QGridLayout()
        
        self.system_ready_label = StatusLabel("未知", "normal")
        self.uptime_label = StatusLabel("0s", "normal")
        self.interactions_label = StatusLabel("0", "normal")
        self.idle_time_label = StatusLabel("0s", "normal")
        
        grid.addWidget(QLabel("系统状态:"), 0, 0)
        grid.addWidget(self.system_ready_label, 0, 1)
        grid.addWidget(QLabel("运行时间:"), 0, 2)
        grid.addWidget(self.uptime_label, 0, 3)
        
        grid.addWidget(QLabel("交互次数:"), 1, 0)
        grid.addWidget(self.interactions_label, 1, 1)
        grid.addWidget(QLabel("空闲时间:"), 1, 2)
        grid.addWidget(self.idle_time_label, 1, 3)
        
        group.setLayout(grid)
        layout.addWidget(group)
    
    def create_component_status(self, layout):
        """创建组件状态区域"""
        group = QGroupBox("🔧 组件状态")
        grid = QGridLayout()
        
        # Brain状态
        self.brain_status_label = StatusLabel("😴 sleeping", "warning")
        self.interrupt_mode_label = StatusLabel("未知", "normal")
        
        # Ear状态
        self.ear_status_label = StatusLabel("🔇 muted", "warning")
        self.ear_enabled_label = StatusLabel("未知", "normal")
        
        # Mouth状态
        self.mouth_status_label = StatusLabel("🤐 quiet", "normal")
        self.mouth_enabled_label = StatusLabel("未知", "normal")
        
        # Agent状态
        self.agent_status_label = StatusLabel("❌ 未初始化", "error")
        self.agent_mode_label = StatusLabel("未知", "normal")
        
        # Body状态
        self.body_status_label = StatusLabel("🧍 static", "warning")
        
        grid.addWidget(QLabel("🧠 Brain:"), 0, 0)
        grid.addWidget(self.brain_status_label, 0, 1)
        grid.addWidget(QLabel("打断模式:"), 0, 2)
        grid.addWidget(self.interrupt_mode_label, 0, 3)
        
        grid.addWidget(QLabel("👂 Ear:"), 1, 0)
        grid.addWidget(self.ear_status_label, 1, 1)
        grid.addWidget(QLabel("启用状态:"), 1, 2)
        grid.addWidget(self.ear_enabled_label, 1, 3)
        
        grid.addWidget(QLabel("🗣️ Mouth:"), 2, 0)
        grid.addWidget(self.mouth_status_label, 2, 1)
        grid.addWidget(QLabel("启用状态:"), 2, 2)
        grid.addWidget(self.mouth_enabled_label, 2, 3)
        
        grid.addWidget(QLabel("🤖 Agent:"), 3, 0)
        grid.addWidget(self.agent_status_label, 3, 1)
        grid.addWidget(QLabel("模式:"), 3, 2)
        grid.addWidget(self.agent_mode_label, 3, 3)
        
        grid.addWidget(QLabel("💃 Body:"), 4, 0)
        grid.addWidget(self.body_status_label, 4, 1)
        
        group.setLayout(grid)
        layout.addWidget(group)
    
    def create_interaction_status(self, layout):
        """创建交互状态区域"""
        group = QGroupBox("💬 交互状态")
        grid = QGridLayout()
        
        self.current_input_label = StatusLabel("无", "normal")
        self.last_text_label = StatusLabel("无", "normal")
        self.current_response_label = StatusLabel("无", "normal")
        self.interaction_mode_label = StatusLabel("未知", "normal")
        
        grid.addWidget(QLabel("当前输入:"), 0, 0)
        grid.addWidget(self.current_input_label, 0, 1)
        grid.addWidget(QLabel("交互模式:"), 0, 2)
        grid.addWidget(self.interaction_mode_label, 0, 3)
        
        grid.addWidget(QLabel("最后识别:"), 1, 0)
        grid.addWidget(self.last_text_label, 1, 1, 1, 3)
        
        grid.addWidget(QLabel("当前响应:"), 2, 0)
        grid.addWidget(self.current_response_label, 2, 1, 1, 3)
        
        group.setLayout(grid)
        layout.addWidget(group)
    
    def create_environment_status(self, layout):
        """创建环境状态区域"""
        group = QGroupBox("🌐 环境状态")
        grid = QGridLayout()
        
        self.asr_server_label = StatusLabel("❌ 未连接", "error")
        self.tts_server_label = StatusLabel("❌ 未连接", "error")
        self.llm_server_label = StatusLabel("❌ 未连接", "error")
        self.model_loaded_label = StatusLabel("❌ 未加载", "error")
        self.error_count_label = StatusLabel("0", "good")
        self.last_error_label = StatusLabel("无", "good")
        
        grid.addWidget(QLabel("ASR服务:"), 0, 0)
        grid.addWidget(self.asr_server_label, 0, 1)
        grid.addWidget(QLabel("TTS服务:"), 0, 2)
        grid.addWidget(self.tts_server_label, 0, 3)
        
        grid.addWidget(QLabel("LLM服务:"), 1, 0)
        grid.addWidget(self.llm_server_label, 1, 1)
        grid.addWidget(QLabel("模型加载:"), 1, 2)
        grid.addWidget(self.model_loaded_label, 1, 3)
        
        grid.addWidget(QLabel("错误计数:"), 2, 0)
        grid.addWidget(self.error_count_label, 2, 1)
        grid.addWidget(QLabel("最后错误:"), 2, 2)
        grid.addWidget(self.last_error_label, 2, 3)
        
        group.setLayout(grid)
        layout.addWidget(group)
    
    def create_performance_metrics(self, layout):
        """创建性能指标区域"""
        group = QGroupBox("⚡ 性能指标")
        grid = QGridLayout()
        
        self.transcription_delay_label = StatusLabel("--", "normal")
        self.ai_delay_label = StatusLabel("--", "normal")
        self.tts_delay_label = StatusLabel("--", "normal")
        self.total_delay_label = StatusLabel("--", "normal")
        
        grid.addWidget(QLabel("转录延迟:"), 0, 0)
        grid.addWidget(self.transcription_delay_label, 0, 1)
        grid.addWidget(QLabel("AI处理延迟:"), 0, 2)
        grid.addWidget(self.ai_delay_label, 0, 3)
        
        grid.addWidget(QLabel("TTS延迟:"), 1, 0)
        grid.addWidget(self.tts_delay_label, 1, 1)
        grid.addWidget(QLabel("总响应延迟:"), 1, 2)
        grid.addWidget(self.total_delay_label, 1, 3)
        
        group.setLayout(grid)
        layout.addWidget(group)
    
    def start_monitoring(self):
        """开始监控"""
        self.update_thread = StatusUpdateThread(self.feel_state)
        self.update_thread.status_updated.connect(self.update_display)
        self.update_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        if self.update_thread:
            self.update_thread.stop()
    
    def update_display(self, status: dict):
        """更新显示"""
        try:
            # 系统概览
            self.system_ready_label.set_status(
                "✅ 就绪" if status["system_ready"] else "❌ 未就绪",
                "good" if status["system_ready"] else "error"
            )
            
            self.uptime_label.set_status(f"{status['uptime']:.1f}s")
            self.interactions_label.set_status(str(status["total_interactions"]))
            self.idle_time_label.set_status(f"{status['idle_time']:.1f}s")
            
            # 组件状态
            comp_status = status["component_status"]
            
            # Brain
            self.brain_status_label.set_status(
                "🧠 awake" if comp_status["brain_awake"] else "😴 sleeping",
                "good" if comp_status["brain_awake"] else "warning"
            )
            
            interrupt_mode = comp_status["interrupt_mode"]
            if isinstance(interrupt_mode, dict) and "_name_" in interrupt_mode:
                mode_name = interrupt_mode["_name_"]
            else:
                mode_name = str(interrupt_mode)
            self.interrupt_mode_label.set_status(mode_name)
            
            # Ear
            if comp_status["is_hearing"]:
                ear_status = "👂 listening"
                ear_type = "good"
            elif comp_status["ear_enabled"]:
                ear_status = "👂 ready"
                ear_type = "normal"
            else:
                ear_status = "🔇 muted"
                ear_type = "warning"
            self.ear_status_label.set_status(ear_status, ear_type)
            self.ear_enabled_label.set_status("✅" if comp_status["ear_enabled"] else "❌")
            
            # Mouth
            if comp_status["is_speaking"]:
                mouth_status = "🗣️ speaking"
                mouth_type = "good"
            elif comp_status["mouth_enabled"]:
                mouth_status = "🤐 quiet"
                mouth_type = "normal"
            else:
                mouth_status = "🔇 muted"
                mouth_type = "warning"
            self.mouth_status_label.set_status(mouth_status, mouth_type)
            self.mouth_enabled_label.set_status("✅" if comp_status["mouth_enabled"] else "❌")
            
            # Agent
            self.agent_status_label.set_status(
                "✅ 已初始化" if comp_status["agent_initialized"] else "❌ 未初始化",
                "good" if comp_status["agent_initialized"] else "error"
            )
            
            agent_mode = comp_status["agent_mode"]
            if isinstance(agent_mode, dict) and "_name_" in agent_mode:
                mode_name = agent_mode["_name_"]
            else:
                mode_name = str(agent_mode)
            self.agent_mode_label.set_status(mode_name)
            
            # Body
            self.body_status_label.set_status(
                "💃 active" if comp_status["body_initialized"] else "🧍 static",
                "good" if comp_status["body_initialized"] else "warning"
            )
            
            # 交互状态
            inter_status = status["interaction_state"]
            
            current_input = inter_status.get("current_user_input", "") or ""
            self.current_input_label.set_status(current_input[:50] + "..." if len(current_input) > 50 else current_input or "无")
            
            last_text = inter_status.get("last_text", "") or ""
            self.last_text_label.set_status(last_text[:50] + "..." if len(last_text) > 50 else last_text or "无")
            
            current_response = inter_status.get("current_response", "") or ""
            self.current_response_label.set_status(current_response[:50] + "..." if len(current_response) > 50 else current_response or "无")
            
            interaction_mode = comp_status["interaction_mode"]
            if isinstance(interaction_mode, dict) and "_name_" in interaction_mode:
                mode_name = interaction_mode["_name_"]
            else:
                mode_name = str(interaction_mode)
            self.interaction_mode_label.set_status("🗣️ voice" if mode_name == "VOICE" else "⌨️ text")
            
            # 环境状态
            env_status = status["environment_state"]
            
            self.asr_server_label.set_status(
                "✅ 已连接" if env_status["asr_server_connected"] else "❌ 未连接",
                "good" if env_status["asr_server_connected"] else "error"
            )
            
            self.tts_server_label.set_status(
                "✅ 已连接" if env_status["tts_server_connected"] else "❌ 未连接",
                "good" if env_status["tts_server_connected"] else "error"
            )
            
            self.llm_server_label.set_status(
                "✅ 已连接" if env_status["llm_connected"] else "❌ 未连接",
                "good" if env_status["llm_connected"] else "error"
            )
            
            self.model_loaded_label.set_status(
                "✅ 已加载" if env_status["model_loaded"] else "❌ 未加载",
                "good" if env_status["model_loaded"] else "error"
            )
            
            error_count = env_status["error_count"]
            self.error_count_label.set_status(
                str(error_count),
                "good" if error_count == 0 else "warning" if error_count < 5 else "error"
            )
            
            last_error = env_status.get("last_error", "") or ""
            self.last_error_label.set_status(
                last_error[:30] + "..." if len(last_error) > 30 else last_error or "无",
                "good" if not last_error else "error"
            )
            
            # 性能指标
            perf_metrics = status["performance_metrics"]
            
            def format_delay(delay_ms):
                if delay_ms is None:
                    return "--"
                if delay_ms < 100:
                    return f"{delay_ms:.0f}ms"
                elif delay_ms < 1000:
                    return f"{delay_ms:.0f}ms"
                else:
                    return f"{delay_ms/1000:.1f}s"
            
            def get_delay_status(delay_ms):
                if delay_ms is None:
                    return "normal"
                if delay_ms < 200:
                    return "good"
                elif delay_ms < 500:
                    return "warning"
                else:
                    return "error"
            
            transcription_delay = perf_metrics.get("transcription_delay")
            transcription_delay_ms = transcription_delay * 1000 if transcription_delay else None
            self.transcription_delay_label.set_status(
                format_delay(transcription_delay_ms),
                get_delay_status(transcription_delay_ms)
            )
            
            aife_delay = perf_metrics.get("aife_delay")
            aife_delay_ms = aife_delay * 1000 if aife_delay else None
            self.ai_delay_label.set_status(
                format_delay(aife_delay_ms),
                get_delay_status(aife_delay_ms)
            )
            
            tts_delay = perf_metrics.get("tts_delay")
            tts_delay_ms = tts_delay * 1000 if tts_delay else None
            self.tts_delay_label.set_status(
                format_delay(tts_delay_ms),
                get_delay_status(tts_delay_ms)
            )
            
            total_delay = perf_metrics.get("total_response_delay")
            total_delay_ms = total_delay * 1000 if total_delay else None
            self.total_delay_label.set_status(
                format_delay(total_delay_ms),
                get_delay_status(total_delay_ms)
            )
            
        except Exception as e:
            print(f"更新显示时出错: {e}")
    
    def closeEvent(self, event):
        """关闭事件"""
        self.stop_monitoring()
        event.accept()


class BrainMonitor:
    """Brain监控器主类"""
    
    def __init__(self, feel_state: FeelState):
        self.feel_state = feel_state
        self.panel = None
        self.visible = False
    
    def show_panel(self):
        """显示监控面板"""
        if not self.panel:
            self.panel = BrainMonitorPanel(self.feel_state)
        
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        self.visible = True
    
    def hide_panel(self):
        """隐藏监控面板"""
        if self.panel:
            self.panel.hide()
        self.visible = False
    
    def toggle_panel(self):
        """切换监控面板显示状态"""
        if self.visible:
            self.hide_panel()
        else:
            self.show_panel()
    
    def cleanup(self):
        """清理资源"""
        if self.panel:
            self.panel.stop_monitoring()
            self.panel.close()
            self.panel = None


# 测试代码
if __name__ == "__main__":
    from Head.Brain.feel import FeelState
    
    app = QApplication(sys.argv)
    
    # 创建测试用的FeelState
    feel_state = FeelState()
    feel_state.update_component_status("brain", brain_awake=True)
    feel_state.update_component_status("ear", ear_running=True, ear_enabled=True)
    feel_state.update_environment_state(asr_server_connected=True)
    
    # 创建监控面板
    monitor = BrainMonitor(feel_state)
    monitor.show_panel()
    
    sys.exit(app.exec())