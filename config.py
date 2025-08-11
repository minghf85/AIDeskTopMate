import toml
import os
from typing import Dict, Any, Optional, Union
from pathlib import Path
import copy
from logger import get_logger


class ConfigManager:
    """配置管理器类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, config_file: str = "config.toml"):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config_file: str = "config.toml"):
        """初始化配置管理器
        
        Args:
            config_file: 配置文件路径
        """
        if self._initialized:
            return
        
        self._initialized = True
        self.config_file = Path(config_file)
        self.logger = get_logger('config')
        self._config: Dict[str, Any] = {}
        self._default_config: Dict[str, Any] = {}
        
        # 设置默认配置
        self._setup_default_config()
        
        # 加载配置
        self.load_config()
    
    def _setup_default_config(self) -> None:
        """设置默认配置"""
        self._default_config = {
            "general": {
                "project_name": "AIDeskTopMate",
                "log_level": "INFO",
                "debug_mode": False
            },
            "agent": {
                "name": "AI助手",
                "type": "langchain",
                "personality": "友好、乐于助人、有点俏皮"
            },
            "llm": {
                "default_model": "gpt-3.5-turbo",
                "temperature": 0.7,
                "max_tokens": 2000,
                "openai": {
                    "api_key": "",
                    "model": "gpt-3.5-turbo",
                    "base_url": "https://api.openai.com/v1"
                },
                "local": {
                    "enabled": False,
                    "model_path": "",
                    "model_type": "llama"
                }
            },
            "memory": {
                "type": "simple",
                "max_tokens": 2000,
                "persist_path": "./data/memory"
            },
            "voice": {
                "stt": {
                    "enabled": True,
                    "type": "local"
                },
                "tts": {
                    "enabled": True,
                    "type": "local",
                    "voice": "female"
                }
            },
            "actions": {
                "enabled": ["dialog", "emotion", "memory"],
                "dialog": {
                    "enabled": True
                },
                "emotion": {
                    "enabled": True,
                    "default_emotion": "neutral"
                },
                "memory": {
                    "enabled": True,
                    "store_path": "./data/memory"
                },
                "web_search": {
                    "enabled": False,
                    "engine": "google"
                }
            },
            "ui": {
                "live2d": {
                    "model_path": "",
                    "scale": 1.0,
                    "position_x": 0,
                    "position_y": 0,
                    "opacity": 0.9
                },
                "window": {
                    "always_on_top": True,
                    "frameless": True,
                    "background_color": "transparent",
                    "width": 400,
                    "height": 600
                }
            }
        }
    
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = toml.load(f)
                
                # 合并默认配置和加载的配置
                self._config = self._merge_configs(self._default_config, loaded_config)
                self.logger.info(f"配置文件加载成功: {self.config_file}")
            else:
                # 如果配置文件不存在，使用默认配置并创建文件
                self._config = copy.deepcopy(self._default_config)
                self.save_config()
                self.logger.info(f"配置文件不存在，已创建默认配置: {self.config_file}")
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            self._config = copy.deepcopy(self._default_config)
    
    def save_config(self) -> bool:
        """保存配置到文件
        
        Returns:
            bool: 是否保存成功
        """
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                toml.dump(self._config, f)
            
            self.logger.info(f"配置文件保存成功: {self.config_file}")
            return True
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值
        
        Args:
            key: 配置键，支持点分隔的嵌套键，如 'llm.openai.api_key'
            default: 默认值
            
        Returns:
            Any: 配置值
        """
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """设置配置值
        
        Args:
            key: 配置键，支持点分隔的嵌套键
            value: 配置值
        """
        keys = key.split('.')
        config = self._config
        
        # 导航到最后一级的父级
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # 设置值
        config[keys[-1]] = value
        self.logger.debug(f"设置配置: {key} = {value}")
    
    def update(self, updates: Dict[str, Any]) -> None:
        """批量更新配置
        
        Args:
            updates: 要更新的配置字典
        """
        self._config = self._merge_configs(self._config, updates)
        self.logger.info(f"批量更新配置: {list(updates.keys())}")
    
    def reset_to_default(self) -> None:
        """重置为默认配置"""
        self._config = copy.deepcopy(self._default_config)
        self.logger.info("配置已重置为默认值")
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """获取配置段
        
        Args:
            section: 段名称
            
        Returns:
            Dict[str, Any]: 配置段内容
        """
        return self.get(section, {})
    
    def set_section(self, section: str, config: Dict[str, Any]) -> None:
        """设置配置段
        
        Args:
            section: 段名称
            config: 配置段内容
        """
        self.set(section, config)
    
    def has_key(self, key: str) -> bool:
        """检查是否存在指定的配置键
        
        Args:
            key: 配置键
            
        Returns:
            bool: 是否存在
        """
        return self.get(key) is not None
    
    def delete(self, key: str) -> bool:
        """删除配置键
        
        Args:
            key: 配置键
            
        Returns:
            bool: 是否删除成功
        """
        keys = key.split('.')
        config = self._config
        
        try:
            # 导航到最后一级的父级
            for k in keys[:-1]:
                config = config[k]
            
            # 删除键
            if keys[-1] in config:
                del config[keys[-1]]
                self.logger.debug(f"删除配置键: {key}")
                return True
            return False
        except (KeyError, TypeError):
            return False
    
    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """合并配置字典
        
        Args:
            base: 基础配置
            override: 覆盖配置
            
        Returns:
            Dict[str, Any]: 合并后的配置
        """
        result = copy.deepcopy(base)
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """获取完整配置字典
        
        Returns:
            Dict[str, Any]: 配置字典的副本
        """
        return copy.deepcopy(self._config)
    
    def reload(self) -> None:
        """重新加载配置文件"""
        self.load_config()
        self.logger.info("配置文件已重新加载")
    
    def backup_config(self, backup_path: Optional[str] = None) -> bool:
        """备份配置文件
        
        Args:
            backup_path: 备份文件路径，如果为None则自动生成
            
        Returns:
            bool: 是否备份成功
        """
        try:
            if backup_path is None:
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_path = f"{self.config_file.stem}_backup_{timestamp}.toml"
            
            backup_file = Path(backup_path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                toml.dump(self._config, f)
            
            self.logger.info(f"配置文件备份成功: {backup_file}")
            return True
        except Exception as e:
            self.logger.error(f"备份配置文件失败: {e}")
            return False


# 创建全局配置管理器实例
config_manager = ConfigManager()

# 便捷函数
def get_config(key: str, default: Any = None) -> Any:
    """获取配置值的便捷函数
    
    Args:
        key: 配置键
        default: 默认值
        
    Returns:
        Any: 配置值
    """
    return config_manager.get(key, default)


def set_config(key: str, value: Any) -> None:
    """设置配置值的便捷函数
    
    Args:
        key: 配置键
        value: 配置值
    """
    config_manager.set(key, value)


def save_config() -> bool:
    """保存配置的便捷函数
    
    Returns:
        bool: 是否保存成功
    """
    return config_manager.save_config()


def reload_config() -> None:
    """重新加载配置的便捷函数"""
    config_manager.reload()


def get_section(section: str) -> Dict[str, Any]:
    """获取配置段的便捷函数
    
    Args:
        section: 段名称
        
    Returns:
        Dict[str, Any]: 配置段内容
    """
    return config_manager.get_section(section)


if __name__ == "__main__":
    # 测试配置系统
    print("测试配置系统...")
    
    # 测试获取配置
    print(f"项目名称: {get_config('general.project_name')}")
    print(f"日志级别: {get_config('general.log_level')}")
    print(f"LLM模型: {get_config('llm.default_model')}")
    
    # 测试设置配置
    set_config('general.debug_mode', True)
    set_config('llm.temperature', 0.8)
    
    # 测试保存配置
    if save_config():
        print("配置保存成功")
    
    # 测试获取配置段
    llm_config = get_section('llm')
    print(f"LLM配置: {llm_config}")
    
    print("配置系统测试完成！")