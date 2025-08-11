import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from logger import get_logger


class Assets:
    """管理所有资源文件的类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化资源管理器"""
        if self._initialized:
            return
        
        self._initialized = True
        self.logger = get_logger('assets')
        self.assets_root = Path("./assets")
        self.cache: Dict[str, Any] = {}
        self.supported_formats = {
            'image': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg'],
            'audio': ['.mp3', '.wav', '.ogg', '.m4a', '.flac'],
            'model': ['.moc3', '.model3.json', '.physics3.json', '.pose3.json'],
            'config': ['.json', '.toml', '.yaml', '.yml']
        }
        
        # 创建资源目录结构
        self._create_asset_directories()
        
        # 扫描并索引资源
        self.refresh_assets()
    
    def _create_asset_directories(self) -> None:
        """创建资源目录结构"""
        directories = [
            self.assets_root,
            self.assets_root / "images",
            self.assets_root / "audio",
            self.assets_root / "models" / "live2d",
            self.assets_root / "configs",
            self.assets_root / "themes",
            self.assets_root / "fonts",
            self.assets_root / "cache"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("资源目录结构创建完成")
    
    def refresh_assets(self) -> None:
        """刷新资源索引"""
        self.cache.clear()
        self._scan_directory(self.assets_root)
        self.logger.info(f"资源扫描完成，共发现 {len(self.cache)} 个资源文件")
    
    def _scan_directory(self, directory: Path) -> None:
        """递归扫描目录
        
        Args:
            directory: 要扫描的目录
        """
        if not directory.exists():
            return
        
        for item in directory.iterdir():
            if item.is_file():
                relative_path = item.relative_to(self.assets_root)
                asset_key = str(relative_path).replace('\\', '/')
                
                self.cache[asset_key] = {
                    'path': item,
                    'type': self._get_asset_type(item),
                    'size': item.stat().st_size,
                    'modified': item.stat().st_mtime
                }
            elif item.is_dir() and not item.name.startswith('.'):
                self._scan_directory(item)
    
    def _get_asset_type(self, file_path: Path) -> str:
        """获取资源类型
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 资源类型
        """
        suffix = file_path.suffix.lower()
        
        for asset_type, extensions in self.supported_formats.items():
            if suffix in extensions:
                return asset_type
        
        return 'unknown'
    
    def get_asset_path(self, asset_key: str) -> Optional[Path]:
        """获取资源文件路径
        
        Args:
            asset_key: 资源键名
            
        Returns:
            Optional[Path]: 资源文件路径
        """
        if asset_key in self.cache:
            return self.cache[asset_key]['path']
        return None
    
    def get_asset_info(self, asset_key: str) -> Optional[Dict[str, Any]]:
        """获取资源信息
        
        Args:
            asset_key: 资源键名
            
        Returns:
            Optional[Dict[str, Any]]: 资源信息
        """
        return self.cache.get(asset_key)
    
    def list_assets_by_type(self, asset_type: str) -> List[str]:
        """按类型列出资源
        
        Args:
            asset_type: 资源类型
            
        Returns:
            List[str]: 资源键名列表
        """
        return [key for key, info in self.cache.items() 
                if info['type'] == asset_type]
    
    def add_asset(self, asset_key: str, source_path: str) -> bool:
        """添加资源文件
        
        Args:
            asset_key: 资源键名
            source_path: 源文件路径
            
        Returns:
            bool: 是否添加成功
        """
        try:
            source = Path(source_path)
            if not source.exists():
                self.logger.error(f"源文件不存在: {source_path}")
                return False
            
            target = self.assets_root / asset_key
            target.parent.mkdir(parents=True, exist_ok=True)
            
            # 复制文件
            import shutil
            shutil.copy2(source, target)
            
            # 更新缓存
            self.cache[asset_key] = {
                'path': target,
                'type': self._get_asset_type(target),
                'size': target.stat().st_size,
                'modified': target.stat().st_mtime
            }
            
            self.logger.info(f"资源添加成功: {asset_key}")
            return True
        except Exception as e:
            self.logger.error(f"添加资源失败: {e}")
            return False
    
    def remove_asset(self, asset_key: str) -> bool:
        """删除资源文件
        
        Args:
            asset_key: 资源键名
            
        Returns:
            bool: 是否删除成功
        """
        try:
            if asset_key not in self.cache:
                self.logger.warning(f"资源不存在: {asset_key}")
                return False
            
            asset_path = self.cache[asset_key]['path']
            if asset_path.exists():
                asset_path.unlink()
            
            del self.cache[asset_key]
            self.logger.info(f"资源删除成功: {asset_key}")
            return True
        except Exception as e:
            self.logger.error(f"删除资源失败: {e}")
            return False
    
    def get_cache_size(self) -> int:
        """获取缓存大小
        
        Returns:
            int: 缓存大小（字节）
        """
        return sum(info['size'] for info in self.cache.values())
    
    def clear_cache(self) -> None:
        """清空缓存目录"""
        cache_dir = self.assets_root / "cache"
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir)
            cache_dir.mkdir()
        self.logger.info("缓存目录已清空")
    
    def export_asset_list(self, output_path: str) -> bool:
        """导出资源列表
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            bool: 是否导出成功
        """
        try:
            asset_list = {
                'total_count': len(self.cache),
                'total_size': self.get_cache_size(),
                'assets': {
                    key: {
                        'type': info['type'],
                        'size': info['size'],
                        'path': str(info['path'])
                    }
                    for key, info in self.cache.items()
                }
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(asset_list, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"资源列表导出成功: {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"导出资源列表失败: {e}")
            return False


# 创建全局资源管理器实例
assets_manager = Assets()

# 便捷函数
def get_asset_path(asset_key: str) -> Optional[Path]:
    """获取资源路径的便捷函数"""
    return assets_manager.get_asset_path(asset_key)

def get_asset_info(asset_key: str) -> Optional[Dict[str, Any]]:
    """获取资源信息的便捷函数"""
    return assets_manager.get_asset_info(asset_key)

def list_assets(asset_type: str = None) -> List[str]:
    """列出资源的便捷函数"""
    if asset_type:
        return assets_manager.list_assets_by_type(asset_type)
    return list(assets_manager.cache.keys())