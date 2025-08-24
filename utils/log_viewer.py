import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QComboBox, QLabel, QPushButton, QCheckBox, QLineEdit,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSpinBox, QDateTimeEdit, QProgressBar, QStatusBar
)
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, QThread, Qt, QDateTime
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
import json
from collections import defaultdict, deque
from utils.log_manager import log_manager, LogLevel


class LogEntry:
    """日志条目"""
    def __init__(self, timestamp: datetime, level: str, module: str, message: str, 
                 function: str = "", line: int = 0):
        self.timestamp = timestamp
        self.level = level
        self.module = module
        self.message = message
        self.function = function
        self.line = line


class LogCollector(QObject):
    """日志收集器"""
    log_received = pyqtSignal(object)  # LogEntry
    
    def __init__(self):
        super().__init__()
        self.buffer = deque(maxlen=10000)  # 最多保存10000条日志
        self.filters = {
            'level': None,
            'module': None,
            'keyword': None
        }
        
        # 注册到日志管理器
        log_manager.add_monitor_callback(self.on_log_received)
    
    def on_log_received(self, record):
        """接收日志记录"""
        try:
            entry = LogEntry(
                timestamp=datetime.now(),
                level=record.get('level', {}).get('name', 'INFO'),
                module=record.get('name', 'unknown'),
                message=record.get('message', ''),
                function=record.get('function', ''),
                line=record.get('line', 0)
            )
            
            self.buffer.append(entry)
            
            # 检查过滤条件
            if self._should_display(entry):
                self.log_received.emit(entry)
        except Exception as e:
            print(f"处理日志记录失败: {e}")
    
    def _should_display(self, entry: LogEntry) -> bool:
        """检查是否应该显示此日志条目"""
        # 级别过滤
        if self.filters['level'] and entry.level != self.filters['level']:
            return False
        
        # 模块过滤
        if self.filters['module'] and entry.module != self.filters['module']:
            return False
        
        # 关键词过滤
        if self.filters['keyword']:
            keyword = self.filters['keyword'].lower()
            if keyword not in entry.message.lower():
                return False
        
        return True
    
    def set_filter(self, filter_type: str, value: str):
        """设置过滤条件"""
        if filter_type in self.filters:
            self.filters[filter_type] = value if value else None
    
    def get_logs(self, count: int = 1000) -> List[LogEntry]:
        """获取最近的日志"""
        return list(self.buffer)[-count:]


class LogStatisticsWidget(QWidget):
    """日志统计窗口"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_statistics)
        self.update_timer.start(5000)  # 每5秒更新一次
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 统计表格
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(6)
        self.stats_table.setHorizontalHeaderLabels([
            '模块', '总日志数', '错误数', '警告数', '最后错误时间', '平均频率/分钟'
        ])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        
        layout.addWidget(QLabel("日志统计信息:"))
        layout.addWidget(self.stats_table)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.update_statistics)
        
        export_btn = QPushButton("导出统计")
        export_btn.clicked.connect(self.export_statistics)
        
        clear_btn = QPushButton("清除统计")
        clear_btn.clicked.connect(self.clear_statistics)
        
        button_layout.addWidget(refresh_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(clear_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def update_statistics(self):
        """更新统计信息"""
        try:
            stats = log_manager.get_stats()
            
            self.stats_table.setRowCount(len(stats))
            
            for row, (module_name, module_stats) in enumerate(stats.items()):
                self.stats_table.setItem(row, 0, QTableWidgetItem(module_name))
                self.stats_table.setItem(row, 1, QTableWidgetItem(str(module_stats.total_logs)))
                self.stats_table.setItem(row, 2, QTableWidgetItem(str(module_stats.error_count)))
                self.stats_table.setItem(row, 3, QTableWidgetItem(str(module_stats.warning_count)))
                
                last_error = module_stats.last_error_time
                last_error_str = last_error.strftime('%H:%M:%S') if last_error else '-'
                self.stats_table.setItem(row, 4, QTableWidgetItem(last_error_str))
                
                avg_freq = f"{module_stats.avg_logs_per_minute:.2f}"
                self.stats_table.setItem(row, 5, QTableWidgetItem(avg_freq))
        
        except Exception as e:
            print(f"更新统计信息失败: {e}")
    
    def export_statistics(self):
        """导出统计信息"""
        try:
            stats = log_manager.get_stats()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"log_statistics_{timestamp}.json"
            
            export_data = {}
            for module_name, module_stats in stats.items():
                export_data[module_name] = {
                    'total_logs': module_stats.total_logs,
                    'error_count': module_stats.error_count,
                    'warning_count': module_stats.warning_count,
                    'last_error_time': module_stats.last_error_time.isoformat() if module_stats.last_error_time else None,
                    'avg_logs_per_minute': module_stats.avg_logs_per_minute
                }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            print(f"统计信息已导出到: {filename}")
        
        except Exception as e:
            print(f"导出统计信息失败: {e}")
    
    def clear_statistics(self):
        """清除统计信息"""
        # 这里可以添加清除统计的逻辑
        self.stats_table.setRowCount(0)


class LogViewerWidget(QWidget):
    """日志查看器主窗口"""
    
    def __init__(self):
        super().__init__()
        self.collector = LogCollector()
        self.collector.log_received.connect(self.add_log_entry)
        
        self.init_ui()
        self.setup_colors()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 过滤控件
        filter_layout = QHBoxLayout()
        
        # 级别过滤
        filter_layout.addWidget(QLabel("级别:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(['全部', 'TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL'])
        self.level_combo.currentTextChanged.connect(self.on_level_filter_changed)
        filter_layout.addWidget(self.level_combo)
        
        # 模块过滤
        filter_layout.addWidget(QLabel("模块:"))
        self.module_combo = QComboBox()
        self.module_combo.addItem('全部')
        self.module_combo.currentTextChanged.connect(self.on_module_filter_changed)
        filter_layout.addWidget(self.module_combo)
        
        # 关键词过滤
        filter_layout.addWidget(QLabel("关键词:"))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.textChanged.connect(self.on_keyword_filter_changed)
        filter_layout.addWidget(self.keyword_edit)
        
        # 自动滚动
        self.auto_scroll_cb = QCheckBox("自动滚动")
        self.auto_scroll_cb.setChecked(True)
        filter_layout.addWidget(self.auto_scroll_cb)
        
        # 清除按钮
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self.clear_logs)
        filter_layout.addWidget(clear_btn)
        
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # 日志显示区域
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_display)
        
        # 状态栏信息
        status_layout = QHBoxLayout()
        self.log_count_label = QLabel("日志数: 0")
        self.last_update_label = QLabel("最后更新: -")
        status_layout.addWidget(self.log_count_label)
        status_layout.addStretch()
        status_layout.addWidget(self.last_update_label)
        layout.addLayout(status_layout)
        
        self.setLayout(layout)
        
        # 更新模块列表
        self.update_module_list()
        
        # 定时更新模块列表
        self.module_timer = QTimer()
        self.module_timer.timeout.connect(self.update_module_list)
        self.module_timer.start(10000)  # 每10秒更新一次
        
        self.log_count = 0
    
    def setup_colors(self):
        """设置不同级别日志的颜色"""
        self.level_colors = {
            'TRACE': QColor(128, 128, 128),      # 灰色
            'DEBUG': QColor(0, 128, 255),        # 蓝色
            'INFO': QColor(0, 0, 0),             # 黑色
            'SUCCESS': QColor(0, 128, 0),        # 绿色
            'WARNING': QColor(255, 165, 0),      # 橙色
            'ERROR': QColor(255, 0, 0),          # 红色
            'CRITICAL': QColor(128, 0, 128)      # 紫色
        }
    
    def update_module_list(self):
        """更新模块列表"""
        try:
            stats = log_manager.get_stats()
            current_modules = set(stats.keys())
            
            # 获取当前选中的模块
            current_selection = self.module_combo.currentText()
            
            # 清除并重新添加
            self.module_combo.clear()
            self.module_combo.addItem('全部')
            
            for module in sorted(current_modules):
                self.module_combo.addItem(module)
            
            # 恢复选择
            if current_selection in [self.module_combo.itemText(i) for i in range(self.module_combo.count())]:
                self.module_combo.setCurrentText(current_selection)
        
        except Exception as e:
            print(f"更新模块列表失败: {e}")
    
    def on_level_filter_changed(self, level: str):
        """级别过滤变化"""
        filter_level = None if level == '全部' else level
        self.collector.set_filter('level', filter_level)
        self.refresh_display()
    
    def on_module_filter_changed(self, module: str):
        """模块过滤变化"""
        filter_module = None if module == '全部' else module
        self.collector.set_filter('module', filter_module)
        self.refresh_display()
    
    def on_keyword_filter_changed(self, keyword: str):
        """关键词过滤变化"""
        self.collector.set_filter('keyword', keyword)
        self.refresh_display()
    
    def refresh_display(self):
        """刷新显示"""
        self.log_display.clear()
        self.log_count = 0
        
        # 重新显示符合条件的日志
        logs = self.collector.get_logs()
        for log_entry in logs:
            if self.collector._should_display(log_entry):
                self.add_log_entry(log_entry)
    
    def add_log_entry(self, entry: LogEntry):
        """添加日志条目"""
        try:
            # 格式化日志文本
            timestamp_str = entry.timestamp.strftime('%H:%M:%S.%f')[:-3]
            log_text = f"[{timestamp_str}] [{entry.level:8}] [{entry.module}] {entry.message}"
            
            # 设置颜色
            cursor = self.log_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            format = QTextCharFormat()
            color = self.level_colors.get(entry.level, QColor(0, 0, 0))
            format.setForeground(color)
            
            cursor.setCharFormat(format)
            cursor.insertText(log_text + "\n")
            
            # 自动滚动
            if self.auto_scroll_cb.isChecked():
                self.log_display.moveCursor(QTextCursor.MoveOperation.End)
            
            # 更新计数
            self.log_count += 1
            self.log_count_label.setText(f"日志数: {self.log_count}")
            self.last_update_label.setText(f"最后更新: {datetime.now().strftime('%H:%M:%S')}")
        
        except Exception as e:
            print(f"添加日志条目失败: {e}")
    
    def clear_logs(self):
        """清除日志显示"""
        self.log_display.clear()
        self.log_count = 0
        self.log_count_label.setText("日志数: 0")
        self.last_update_label.setText("最后更新: -")


class LogViewerMainWindow(QMainWindow):
    """日志查看器主窗口"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("AIDeskTopMate 日志查看器")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 实时日志标签页
        self.log_viewer = LogViewerWidget()
        tab_widget.addTab(self.log_viewer, "实时日志")
        
        # 统计信息标签页
        self.stats_viewer = LogStatisticsWidget()
        tab_widget.addTab(self.stats_viewer, "统计信息")
        
        self.setCentralWidget(tab_widget)
        
        # 状态栏
        self.statusBar().showMessage("日志查看器已启动")
        
        # 菜单栏
        self.create_menu()
    
    def create_menu(self):
        """创建菜单"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu('文件')
        
        export_action = file_menu.addAction('导出日志')
        export_action.triggered.connect(self.export_logs)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction('退出')
        exit_action.triggered.connect(self.close)
        
        # 视图菜单
        view_menu = menubar.addMenu('视图')
        
        refresh_action = view_menu.addAction('刷新')
        refresh_action.triggered.connect(self.refresh_all)
        
        clear_action = view_menu.addAction('清除所有')
        clear_action.triggered.connect(self.clear_all)
    
    def export_logs(self):
        """导出日志"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"exported_logs_{timestamp}.txt"
            
            logs = self.log_viewer.collector.get_logs()
            
            with open(filename, 'w', encoding='utf-8') as f:
                for log_entry in logs:
                    timestamp_str = log_entry.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    f.write(f"[{timestamp_str}] [{log_entry.level:8}] [{log_entry.module}] {log_entry.message}\n")
            
            self.statusBar().showMessage(f"日志已导出到: {filename}")
        
        except Exception as e:
            self.statusBar().showMessage(f"导出失败: {e}")
    
    def refresh_all(self):
        """刷新所有"""
        self.log_viewer.refresh_display()
        self.stats_viewer.update_statistics()
        self.statusBar().showMessage("已刷新")
    
    def clear_all(self):
        """清除所有"""
        self.log_viewer.clear_logs()
        self.stats_viewer.clear_statistics()
        self.statusBar().showMessage("已清除")


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 初始化日志管理器
    from utils.log_manager import setup_logging_from_config
    setup_logging_from_config("logging_config.toml")
    
    # 创建并显示主窗口
    window = LogViewerMainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()