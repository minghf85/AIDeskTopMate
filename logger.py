import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""
    
    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }
    
    def format(self, record):
        # 获取原始格式化的消息
        log_message = super().format(record)
        
        # 添加颜色
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        return f"{color}{log_message}{reset}"


class Logger:
    """日志管理器类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化日志器"""
        if self._initialized:
            return
        
        self._initialized = True
        self.loggers: Dict[str, logging.Logger] = {}
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # 默认配置
        self.default_config = {
            'level': 'INFO',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'date_format': '%Y-%m-%d %H:%M:%S',
            'file_enabled': True,
            'console_enabled': True,
            'colored_console': True,
            'max_file_size': 10 * 1024 * 1024,  # 10MB
            'backup_count': 5
        }
        
        # 创建根日志器
        self.setup_logger('root')
    
    def setup_logger(self, 
                    name: str, 
                    level: Optional[str] = None,
                    log_file: Optional[str] = None,
                    config: Optional[Dict[str, Any]] = None) -> logging.Logger:
        """设置日志器
        
        Args:
            name: 日志器名称
            level: 日志级别
            log_file: 日志文件名
            config: 自定义配置
            
        Returns:
            logging.Logger: 配置好的日志器
        """
        if name in self.loggers:
            return self.loggers[name]
        
        # 合并配置
        final_config = self.default_config.copy()
        if config:
            final_config.update(config)
        
        # 创建日志器
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, (level or final_config['level']).upper()))
        
        # 清除已有的处理器
        logger.handlers.clear()
        
        # 创建格式化器
        formatter = logging.Formatter(
            final_config['format'],
            datefmt=final_config['date_format']
        )
        
        # 控制台处理器
        if final_config['console_enabled']:
            console_handler = logging.StreamHandler(sys.stdout)
            
            if final_config['colored_console']:
                colored_formatter = ColoredFormatter(
                    final_config['format'],
                    datefmt=final_config['date_format']
                )
                console_handler.setFormatter(colored_formatter)
            else:
                console_handler.setFormatter(formatter)
            
            logger.addHandler(console_handler)
        
        # 文件处理器
        if final_config['file_enabled']:
            if log_file is None:
                timestamp = datetime.now().strftime('%Y%m%d')
                log_file = f"{name}_{timestamp}.log"
            
            file_path = self.log_dir / log_file
            
            # 使用RotatingFileHandler来管理文件大小
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=final_config['max_file_size'],
                backupCount=final_config['backup_count'],
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        # 防止日志传播到父日志器
        logger.propagate = False
        
        self.loggers[name] = logger
        return logger
    
    def get_logger(self, name: str) -> logging.Logger:
        """获取日志器
        
        Args:
            name: 日志器名称
            
        Returns:
            logging.Logger: 日志器实例
        """
        if name not in self.loggers:
            return self.setup_logger(name)
        return self.loggers[name]
    
    def set_level(self, name: str, level: str) -> None:
        """设置日志器级别
        
        Args:
            name: 日志器名称
            level: 日志级别
        """
        if name in self.loggers:
            self.loggers[name].setLevel(getattr(logging, level.upper()))
    
    def set_global_level(self, level: str) -> None:
        """设置所有日志器的级别
        
        Args:
            level: 日志级别
        """
        for logger in self.loggers.values():
            logger.setLevel(getattr(logging, level.upper()))
    
    def disable_console(self, name: str) -> None:
        """禁用控制台输出
        
        Args:
            name: 日志器名称
        """
        if name in self.loggers:
            logger = self.loggers[name]
            # 移除控制台处理器
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler) and not hasattr(handler, 'baseFilename'):
                    logger.removeHandler(handler)
    
    def enable_console(self, name: str) -> None:
        """启用控制台输出
        
        Args:
            name: 日志器名称
        """
        if name in self.loggers:
            logger = self.loggers[name]
            # 检查是否已有控制台处理器
            has_console = any(
                isinstance(handler, logging.StreamHandler) and not hasattr(handler, 'baseFilename')
                for handler in logger.handlers
            )
            
            if not has_console:
                console_handler = logging.StreamHandler(sys.stdout)
                colored_formatter = ColoredFormatter(
                    self.default_config['format'],
                    datefmt=self.default_config['date_format']
                )
                console_handler.setFormatter(colored_formatter)
                logger.addHandler(console_handler)
    
    def cleanup_old_logs(self, days: int = 7) -> None:
        """清理旧的日志文件
        
        Args:
            days: 保留天数
        """
        import time
        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 60 * 60)
        
        for log_file in self.log_dir.glob("*.log*"):
            if log_file.stat().st_mtime < cutoff_time:
                try:
                    log_file.unlink()
                    print(f"Deleted old log file: {log_file}")
                except Exception as e:
                    print(f"Failed to delete log file {log_file}: {e}")


# 创建全局日志管理器实例
logger_manager = Logger()

# 便捷函数
def get_logger(name: str = 'root') -> logging.Logger:
    """获取日志器的便捷函数
    
    Args:
        name: 日志器名称，默认为'root'
        
    Returns:
        logging.Logger: 日志器实例
    """
    return logger_manager.get_logger(name)


def setup_logger(name: str, 
                 level: str = 'INFO',
                 log_file: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """设置日志器的便捷函数
    
    Args:
        name: 日志器名称
        level: 日志级别
        log_file: 日志文件名
        config: 自定义配置
        
    Returns:
        logging.Logger: 配置好的日志器
    """
    return logger_manager.setup_logger(name, level, log_file, config)


def set_global_log_level(level: str) -> None:
    """设置全局日志级别的便捷函数
    
    Args:
        level: 日志级别
    """
    logger_manager.set_global_level(level)


# 创建一些常用的日志器
app_logger = get_logger('app')
brain_logger = get_logger('brain')
action_logger = get_logger('action')
agent_logger = get_logger('agent')
message_logger = get_logger('message')
voice_logger = get_logger('voice')
ui_logger = get_logger('ui')


if __name__ == "__main__":
    # 测试日志系统
    test_logger = get_logger('test')
    
    test_logger.debug("这是一个调试消息")
    test_logger.info("这是一个信息消息")
    test_logger.warning("这是一个警告消息")
    test_logger.error("这是一个错误消息")
    test_logger.critical("这是一个严重错误消息")
    
    print("\n日志测试完成！检查logs目录下的日志文件。")