import os
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Union
from enum import Enum
from dataclasses import dataclass, field
from loguru import logger
import json
import toml
from collections import defaultdict, deque
import asyncio
from concurrent.futures import ThreadPoolExecutor


class LogLevel(Enum):
    """日志级别枚举"""
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogConfig:
    """日志配置类"""
    module_name: str
    level: LogLevel = LogLevel.INFO
    file_enabled: bool = True
    console_enabled: bool = True
    file_path: Optional[str] = None
    max_file_size: str = "10 MB"  # 单个日志文件最大大小
    retention: str = "7 days"  # 日志保留时间
    rotation: str = "1 day"  # 日志轮转周期
    format: str = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
    filter_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    enable_compression: bool = True
    enable_json_format: bool = False


@dataclass
class LogStats:
    """日志统计信息"""
    module_name: str
    total_logs: int = 0
    error_count: int = 0
    warning_count: int = 0
    last_error_time: Optional[datetime] = None
    last_warning_time: Optional[datetime] = None
    avg_logs_per_minute: float = 0.0
    log_history: deque = field(default_factory=lambda: deque(maxlen=1000))


class LogFilter:
    """日志过滤器"""
    
    def __init__(self, config: LogConfig):
        self.config = config
        self.include_keywords = config.filter_keywords
        self.exclude_keywords = config.exclude_keywords
    
    def should_log(self, record) -> bool:
        """判断是否应该记录此日志"""
        message = record.get("message", "")
        
        # 检查排除关键词
        if self.exclude_keywords:
            for keyword in self.exclude_keywords:
                if keyword.lower() in message.lower():
                    return False
        
        # 检查包含关键词
        if self.include_keywords:
            for keyword in self.include_keywords:
                if keyword.lower() in message.lower():
                    return True
            return False
        
        return True


class LogMonitor:
    """日志监控器"""
    
    def __init__(self):
        self.callbacks: List[Callable] = []
        self.error_callbacks: List[Callable] = []
        self.warning_callbacks: List[Callable] = []
        self.stats: Dict[str, LogStats] = {}
        self.lock = threading.Lock()
    
    def add_callback(self, callback: Callable, level: Optional[LogLevel] = None):
        """添加日志回调函数"""
        if level == LogLevel.ERROR:
            self.error_callbacks.append(callback)
        elif level == LogLevel.WARNING:
            self.warning_callbacks.append(callback)
        else:
            self.callbacks.append(callback)
    
    def on_log(self, record):
        """处理日志记录"""
        module_name = record.get("name", "unknown")
        level = record.get("level", {}).get("name", "INFO")
        message = record.get("message", "")
        timestamp = datetime.now()
        
        with self.lock:
            # 更新统计信息
            if module_name not in self.stats:
                self.stats[module_name] = LogStats(module_name=module_name)
            
            stats = self.stats[module_name]
            stats.total_logs += 1
            stats.log_history.append((timestamp, level, message))
            
            if level == "ERROR":
                stats.error_count += 1
                stats.last_error_time = timestamp
            elif level == "WARNING":
                stats.warning_count += 1
                stats.last_warning_time = timestamp
            
            # 计算平均日志频率
            if len(stats.log_history) > 1:
                time_span = (stats.log_history[-1][0] - stats.log_history[0][0]).total_seconds() / 60
                if time_span > 0:
                    stats.avg_logs_per_minute = len(stats.log_history) / time_span
        
        # 调用回调函数
        for callback in self.callbacks:
            try:
                callback(record)
            except Exception as e:
                print(f"日志回调函数执行失败: {e}")
        
        # 特定级别的回调
        if level == "ERROR":
            for callback in self.error_callbacks:
                try:
                    callback(record)
                except Exception as e:
                    print(f"错误日志回调函数执行失败: {e}")
        elif level == "WARNING":
            for callback in self.warning_callbacks:
                try:
                    callback(record)
                except Exception as e:
                    print(f"警告日志回调函数执行失败: {e}")
    
    def get_stats(self, module_name: Optional[str] = None) -> Union[LogStats, Dict[str, LogStats]]:
        """获取统计信息"""
        with self.lock:
            if module_name:
                return self.stats.get(module_name)
            return self.stats.copy()


class LogManager:
    """统一日志管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.configs: Dict[str, LogConfig] = {}
        self.filters: Dict[str, LogFilter] = {}
        self.monitor = LogMonitor()
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        self.handler_ids: Dict[str, List[int]] = defaultdict(list)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="LogManager")
        
        # 移除默认的loguru处理器
        logger.remove()
        
        # 设置默认配置
        self._setup_default_config()
    
    def _setup_default_config(self):
        """设置默认配置"""
        default_config = LogConfig(
            module_name="default",
            level=LogLevel.INFO,
            file_enabled=True,
            console_enabled=True
        )
        self.register_module("default", default_config)
    
    def register_module(self, module_name: str, config: LogConfig):
        """注册模块日志配置"""
        self.configs[module_name] = config
        self.filters[module_name] = LogFilter(config)
        self._setup_handlers(module_name, config)
    
    def _setup_handlers(self, module_name: str, config: LogConfig):
        """设置日志处理器"""
        # 清除现有处理器
        if module_name in self.handler_ids:
            for handler_id in self.handler_ids[module_name]:
                try:
                    logger.remove(handler_id)
                except ValueError:
                    pass
            self.handler_ids[module_name].clear()
        
        # 创建过滤函数
        def log_filter(record):
            record_module = record.get("name", "default")
            if record_module == module_name or module_name == "default":
                return self.filters[module_name].should_log(record)
            return False
        
        # 控制台处理器
        if config.console_enabled:
            handler_id = logger.add(
                sys.stdout,
                format=config.format,
                level=config.level.value,
                filter=log_filter,
                colorize=True
            )
            self.handler_ids[module_name].append(handler_id)
        
        # 文件处理器
        if config.file_enabled:
            log_file = config.file_path or self.log_dir / f"{module_name}_{datetime.now().strftime('%Y%m%d')}.log"
            
            handler_id = logger.add(
                log_file,
                format=config.format,
                level=config.level.value,
                filter=log_filter,
                rotation=config.rotation,
                retention=config.retention,
                compression="gz" if config.enable_compression else None,
                serialize=config.enable_json_format,
                enqueue=True,  # 异步写入
                catch=True
            )
            self.handler_ids[module_name].append(handler_id)
        
        # 添加监控处理器
        monitor_handler_id = logger.add(
            self.monitor.on_log,
            format=config.format,
            level="TRACE",  # 监控所有级别
            filter=log_filter
        )
        self.handler_ids[module_name].append(monitor_handler_id)
    
    def get_logger(self, module_name: str) -> logger:
        """获取指定模块的日志器"""
        if module_name not in self.configs:
            # 使用默认配置
            config = LogConfig(module_name=module_name)
            self.register_module(module_name, config)
        
        return logger.bind(name=module_name)
    
    def update_config(self, module_name: str, **kwargs):
        """更新模块配置"""
        if module_name in self.configs:
            config = self.configs[module_name]
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            # 重新设置处理器
            self.filters[module_name] = LogFilter(config)
            self._setup_handlers(module_name, config)
    
    def set_level(self, module_name: str, level: Union[str, LogLevel]):
        """设置模块日志级别"""
        if isinstance(level, str):
            level = LogLevel(level.upper())
        self.update_config(module_name, level=level)
    
    def add_monitor_callback(self, callback: Callable, level: Optional[LogLevel] = None):
        """添加监控回调"""
        self.monitor.add_callback(callback, level)
    
    def get_stats(self, module_name: Optional[str] = None):
        """获取统计信息"""
        return self.monitor.get_stats(module_name)
    
    def cleanup_old_logs(self, days: int = 7):
        """清理旧日志文件"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        def cleanup_task():
            for log_file in self.log_dir.glob("*.log*"):
                try:
                    file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if file_time < cutoff_date:
                        log_file.unlink()
                        print(f"删除旧日志文件: {log_file}")
                except Exception as e:
                    print(f"删除日志文件失败 {log_file}: {e}")
        
        self.executor.submit(cleanup_task)
    
    def export_logs(self, module_name: str, start_time: datetime, end_time: datetime, 
                   output_file: str, format: str = "json"):
        """导出指定时间范围的日志"""
        def export_task():
            try:
                stats = self.get_stats(module_name)
                if not stats:
                    return
                
                filtered_logs = [
                    {"timestamp": log[0].isoformat(), "level": log[1], "message": log[2]}
                    for log in stats.log_history
                    if start_time <= log[0] <= end_time
                ]
                
                if format.lower() == "json":
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(filtered_logs, f, ensure_ascii=False, indent=2)
                elif format.lower() == "txt":
                    with open(output_file, 'w', encoding='utf-8') as f:
                        for log in filtered_logs:
                            f.write(f"{log['timestamp']} | {log['level']} | {log['message']}\n")
                
                print(f"日志导出完成: {output_file}")
            except Exception as e:
                print(f"日志导出失败: {e}")
        
        self.executor.submit(export_task)
    
    def load_config_from_file(self, config_file: str):
        """从配置文件加载日志配置"""
        try:
            if config_file.endswith('.toml'):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = toml.load(f)
            elif config_file.endswith('.json'):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            else:
                raise ValueError("不支持的配置文件格式")
            
            # 解析日志配置
            if 'logging' in config_data:
                logging_config = config_data['logging']
                
                # 全局配置
                global_config = logging_config.get('global', {})
                if 'log_dir' in global_config:
                    self.log_dir = Path(global_config['log_dir'])
                    self.log_dir.mkdir(exist_ok=True)
                
                # 模块配置
                modules_config = logging_config.get('modules', {})
                for module_name, module_config in modules_config.items():
                    config = LogConfig(
                        module_name=module_name,
                        level=LogLevel(module_config.get('level', 'INFO').upper()),
                        file_enabled=module_config.get('file_enabled', True),
                        console_enabled=module_config.get('console_enabled', True),
                        file_path=module_config.get('file_path'),
                        max_file_size=module_config.get('max_file_size', '10 MB'),
                        retention=module_config.get('retention', '7 days'),
                        rotation=module_config.get('rotation', '1 day'),
                        format=module_config.get('format', config.format),
                        filter_keywords=module_config.get('filter_keywords', []),
                        exclude_keywords=module_config.get('exclude_keywords', []),
                        enable_compression=module_config.get('enable_compression', True),
                        enable_json_format=module_config.get('enable_json_format', False)
                    )
                    self.register_module(module_name, config)
        
        except Exception as e:
            print(f"加载日志配置失败: {e}")
    
    def shutdown(self):
        """关闭日志管理器"""
        logger.remove()
        self.executor.shutdown(wait=True)


# 全局日志管理器实例
log_manager = LogManager()


def get_logger(module_name: str):
    """获取模块日志器的便捷函数"""
    return log_manager.get_logger(module_name)


def setup_logging_from_config(config_file: str = "config.toml"):
    """从配置文件设置日志系统"""
    if os.path.exists(config_file):
        log_manager.load_config_from_file(config_file)
    else:
        print(f"配置文件不存在: {config_file}，使用默认配置")