import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from logger import get_logger


class EmojiType(Enum):
    """表情类型枚举"""
    EMOTION = "emotion"  # 情感表情
    ACTION = "action"   # 动作表情
    OBJECT = "object"   # 物品表情
    SYMBOL = "symbol"   # 符号表情
    CUSTOM = "custom"   # 自定义表情


class EmojiItem:
    """表情项类"""
    
    def __init__(self, name: str, file_path: str, emoji_type: EmojiType = EmojiType.CUSTOM, 
                 tags: List[str] = None, description: str = ""):
        """初始化表情项
        
        Args:
            name: 表情名称
            file_path: 文件路径
            emoji_type: 表情类型
            tags: 标签列表
            description: 描述
        """
        self.name = name
        self.file_path = Path(file_path)
        self.emoji_type = emoji_type
        self.tags = tags or []
        self.description = description
        self.usage_count = 0
        self.favorite = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典
        
        Returns:
            Dict[str, Any]: 表情项字典
        """
        return {
            'name': self.name,
            'file_path': str(self.file_path),
            'type': self.emoji_type.value,
            'tags': self.tags,
            'description': self.description,
            'usage_count': self.usage_count,
            'favorite': self.favorite
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EmojiItem':
        """从字典创建表情项
        
        Args:
            data: 表情项字典
            
        Returns:
            EmojiItem: 表情项实例
        """
        item = cls(
            name=data['name'],
            file_path=data['file_path'],
            emoji_type=EmojiType(data.get('type', 'custom')),
            tags=data.get('tags', []),
            description=data.get('description', '')
        )
        item.usage_count = data.get('usage_count', 0)
        item.favorite = data.get('favorite', False)
        return item


class EmojiCollection:
    """表情集合类"""
    
    def __init__(self, name: str, description: str = ""):
        """初始化表情集合
        
        Args:
            name: 集合名称
            description: 集合描述
        """
        self.name = name
        self.description = description
        self.emojis: Dict[str, EmojiItem] = {}
        self.created_time = None
        self.updated_time = None
    
    def add_emoji(self, emoji: EmojiItem) -> bool:
        """添加表情
        
        Args:
            emoji: 表情项
            
        Returns:
            bool: 是否添加成功
        """
        if emoji.name in self.emojis:
            return False
        
        self.emojis[emoji.name] = emoji
        return True
    
    def remove_emoji(self, name: str) -> bool:
        """移除表情
        
        Args:
            name: 表情名称
            
        Returns:
            bool: 是否移除成功
        """
        if name in self.emojis:
            del self.emojis[name]
            return True
        return False
    
    def get_emoji(self, name: str) -> Optional[EmojiItem]:
        """获取表情
        
        Args:
            name: 表情名称
            
        Returns:
            Optional[EmojiItem]: 表情项
        """
        return self.emojis.get(name)
    
    def list_emojis(self) -> List[str]:
        """列出所有表情名称
        
        Returns:
            List[str]: 表情名称列表
        """
        return list(self.emojis.keys())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典
        
        Returns:
            Dict[str, Any]: 集合字典
        """
        return {
            'name': self.name,
            'description': self.description,
            'emojis': {name: emoji.to_dict() for name, emoji in self.emojis.items()},
            'created_time': self.created_time,
            'updated_time': self.updated_time
        }


class Emoji:
    """管理表情包的类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化表情管理器"""
        if self._initialized:
            return
        
        self._initialized = True
        self.logger = get_logger('emoji')
        self.emoji_root = Path("./assets/emojis")
        self.collections: Dict[str, EmojiCollection] = {}
        self.supported_formats = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
        self.config_file = self.emoji_root / "emoji_config.json"
        
        # 创建表情目录结构
        self._create_emoji_directories()
        
        # 加载表情配置
        self.load_config()
        
        # 扫描表情文件
        self.scan_emojis()
    
    def _create_emoji_directories(self) -> None:
        """创建表情目录结构"""
        directories = [
            self.emoji_root,
            self.emoji_root / "emotions",
            self.emoji_root / "actions",
            self.emoji_root / "objects",
            self.emoji_root / "symbols",
            self.emoji_root / "custom",
            self.emoji_root / "collections"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("表情目录结构创建完成")
    
    def load_config(self) -> None:
        """加载表情配置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # 加载表情集合
                for collection_data in config_data.get('collections', []):
                    collection = EmojiCollection(
                        name=collection_data['name'],
                        description=collection_data.get('description', '')
                    )
                    
                    # 加载表情项
                    for emoji_data in collection_data.get('emojis', {}).values():
                        emoji = EmojiItem.from_dict(emoji_data)
                        collection.add_emoji(emoji)
                    
                    self.collections[collection.name] = collection
                
                self.logger.info(f"表情配置加载成功，共 {len(self.collections)} 个集合")
            else:
                # 创建默认集合
                self._create_default_collections()
                self.save_config()
        except Exception as e:
            self.logger.error(f"加载表情配置失败: {e}")
            self._create_default_collections()
    
    def _create_default_collections(self) -> None:
        """创建默认表情集合"""
        default_collections = [
            ("emotions", "情感表情"),
            ("actions", "动作表情"),
            ("objects", "物品表情"),
            ("symbols", "符号表情"),
            ("favorites", "收藏表情"),
            ("recent", "最近使用")
        ]
        
        for name, description in default_collections:
            collection = EmojiCollection(name, description)
            self.collections[name] = collection
        
        self.logger.info("默认表情集合创建完成")
    
    def save_config(self) -> bool:
        """保存表情配置
        
        Returns:
            bool: 是否保存成功
        """
        try:
            config_data = {
                'collections': [collection.to_dict() for collection in self.collections.values()]
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info("表情配置保存成功")
            return True
        except Exception as e:
            self.logger.error(f"保存表情配置失败: {e}")
            return False
    
    def scan_emojis(self) -> None:
        """扫描表情文件"""
        emoji_count = 0
        
        for emoji_type in EmojiType:
            type_dir = self.emoji_root / emoji_type.value
            if type_dir.exists():
                emoji_count += self._scan_directory(type_dir, emoji_type)
        
        # 扫描自定义目录
        custom_dir = self.emoji_root / "custom"
        if custom_dir.exists():
            emoji_count += self._scan_directory(custom_dir, EmojiType.CUSTOM)
        
        self.logger.info(f"表情扫描完成，共发现 {emoji_count} 个表情文件")
    
    def _scan_directory(self, directory: Path, emoji_type: EmojiType) -> int:
        """扫描目录中的表情文件
        
        Args:
            directory: 目录路径
            emoji_type: 表情类型
            
        Returns:
            int: 发现的表情数量
        """
        count = 0
        collection_name = emoji_type.value
        
        if collection_name not in self.collections:
            self.collections[collection_name] = EmojiCollection(
                collection_name, f"{emoji_type.value}表情"
            )
        
        collection = self.collections[collection_name]
        
        for file_path in directory.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.supported_formats:
                emoji_name = file_path.stem
                
                # 检查是否已存在
                if collection.get_emoji(emoji_name) is None:
                    emoji = EmojiItem(
                        name=emoji_name,
                        file_path=str(file_path),
                        emoji_type=emoji_type,
                        tags=[emoji_type.value]
                    )
                    collection.add_emoji(emoji)
                    count += 1
        
        return count
    
    def add_emoji(self, collection_name: str, name: str, file_path: str, 
                  emoji_type: EmojiType = EmojiType.CUSTOM, tags: List[str] = None, 
                  description: str = "") -> bool:
        """添加表情
        
        Args:
            collection_name: 集合名称
            name: 表情名称
            file_path: 文件路径
            emoji_type: 表情类型
            tags: 标签列表
            description: 描述
            
        Returns:
            bool: 是否添加成功
        """
        try:
            if collection_name not in self.collections:
                self.collections[collection_name] = EmojiCollection(collection_name)
            
            collection = self.collections[collection_name]
            emoji = EmojiItem(name, file_path, emoji_type, tags, description)
            
            if collection.add_emoji(emoji):
                self.logger.info(f"表情添加成功: {collection_name}/{name}")
                return True
            else:
                self.logger.warning(f"表情已存在: {collection_name}/{name}")
                return False
        except Exception as e:
            self.logger.error(f"添加表情失败: {e}")
            return False
    
    def remove_emoji(self, collection_name: str, name: str) -> bool:
        """移除表情
        
        Args:
            collection_name: 集合名称
            name: 表情名称
            
        Returns:
            bool: 是否移除成功
        """
        if collection_name not in self.collections:
            return False
        
        collection = self.collections[collection_name]
        if collection.remove_emoji(name):
            self.logger.info(f"表情移除成功: {collection_name}/{name}")
            return True
        return False
    
    def get_emoji(self, collection_name: str, name: str) -> Optional[EmojiItem]:
        """获取表情
        
        Args:
            collection_name: 集合名称
            name: 表情名称
            
        Returns:
            Optional[EmojiItem]: 表情项
        """
        if collection_name not in self.collections:
            return None
        
        return self.collections[collection_name].get_emoji(name)
    
    def search_emojis(self, query: str, collection_name: str = None) -> List[Tuple[str, EmojiItem]]:
        """搜索表情
        
        Args:
            query: 搜索关键词
            collection_name: 指定集合名称（可选）
            
        Returns:
            List[Tuple[str, EmojiItem]]: 搜索结果列表 (集合名, 表情项)
        """
        results = []
        query_lower = query.lower()
        
        collections_to_search = [self.collections[collection_name]] if collection_name else self.collections.values()
        
        for collection in collections_to_search:
            for emoji in collection.emojis.values():
                # 搜索名称、标签和描述
                if (query_lower in emoji.name.lower() or 
                    any(query_lower in tag.lower() for tag in emoji.tags) or 
                    query_lower in emoji.description.lower()):
                    results.append((collection.name, emoji))
        
        # 按使用次数排序
        results.sort(key=lambda x: x[1].usage_count, reverse=True)
        return results
    
    def get_popular_emojis(self, limit: int = 10) -> List[Tuple[str, EmojiItem]]:
        """获取热门表情
        
        Args:
            limit: 返回数量限制
            
        Returns:
            List[Tuple[str, EmojiItem]]: 热门表情列表
        """
        all_emojis = []
        
        for collection in self.collections.values():
            for emoji in collection.emojis.values():
                all_emojis.append((collection.name, emoji))
        
        # 按使用次数排序
        all_emojis.sort(key=lambda x: x[1].usage_count, reverse=True)
        return all_emojis[:limit]
    
    def get_favorite_emojis(self) -> List[Tuple[str, EmojiItem]]:
        """获取收藏表情
        
        Returns:
            List[Tuple[str, EmojiItem]]: 收藏表情列表
        """
        favorites = []
        
        for collection in self.collections.values():
            for emoji in collection.emojis.values():
                if emoji.favorite:
                    favorites.append((collection.name, emoji))
        
        return favorites
    
    def use_emoji(self, collection_name: str, name: str) -> bool:
        """使用表情（增加使用次数）
        
        Args:
            collection_name: 集合名称
            name: 表情名称
            
        Returns:
            bool: 是否使用成功
        """
        emoji = self.get_emoji(collection_name, name)
        if emoji:
            emoji.usage_count += 1
            
            # 添加到最近使用集合
            if "recent" in self.collections:
                recent_collection = self.collections["recent"]
                if recent_collection.get_emoji(name) is None:
                    recent_emoji = EmojiItem(
                        name=emoji.name,
                        file_path=str(emoji.file_path),
                        emoji_type=emoji.emoji_type,
                        tags=emoji.tags.copy(),
                        description=emoji.description
                    )
                    recent_collection.add_emoji(recent_emoji)
            
            self.logger.debug(f"表情使用: {collection_name}/{name}")
            return True
        return False
    
    def toggle_favorite(self, collection_name: str, name: str) -> bool:
        """切换表情收藏状态
        
        Args:
            collection_name: 集合名称
            name: 表情名称
            
        Returns:
            bool: 新的收藏状态
        """
        emoji = self.get_emoji(collection_name, name)
        if emoji:
            emoji.favorite = not emoji.favorite
            
            # 更新收藏集合
            if "favorites" in self.collections:
                favorites_collection = self.collections["favorites"]
                if emoji.favorite:
                    # 添加到收藏
                    if favorites_collection.get_emoji(name) is None:
                        fav_emoji = EmojiItem(
                            name=emoji.name,
                            file_path=str(emoji.file_path),
                            emoji_type=emoji.emoji_type,
                            tags=emoji.tags.copy(),
                            description=emoji.description
                        )
                        fav_emoji.favorite = True
                        favorites_collection.add_emoji(fav_emoji)
                else:
                    # 从收藏移除
                    favorites_collection.remove_emoji(name)
            
            self.logger.debug(f"表情收藏状态切换: {collection_name}/{name} -> {emoji.favorite}")
            return emoji.favorite
        return False
    
    def list_collections(self) -> List[str]:
        """列出所有集合名称
        
        Returns:
            List[str]: 集合名称列表
        """
        return list(self.collections.keys())
    
    def get_collection_info(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """获取集合信息
        
        Args:
            collection_name: 集合名称
            
        Returns:
            Optional[Dict[str, Any]]: 集合信息
        """
        if collection_name not in self.collections:
            return None
        
        collection = self.collections[collection_name]
        return {
            'name': collection.name,
            'description': collection.description,
            'emoji_count': len(collection.emojis),
            'emojis': collection.list_emojis()
        }
    
    def export_collection(self, collection_name: str, output_path: str) -> bool:
        """导出表情集合
        
        Args:
            collection_name: 集合名称
            output_path: 输出文件路径
            
        Returns:
            bool: 是否导出成功
        """
        if collection_name not in self.collections:
            return False
        
        try:
            collection = self.collections[collection_name]
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(collection.to_dict(), f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"表情集合导出成功: {collection_name} -> {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"导出表情集合失败: {e}")
            return False
    
    def import_collection(self, file_path: str) -> bool:
        """导入表情集合
        
        Args:
            file_path: 集合文件路径
            
        Returns:
            bool: 是否导入成功
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                collection_data = json.load(f)
            
            collection = EmojiCollection(
                name=collection_data['name'],
                description=collection_data.get('description', '')
            )
            
            for emoji_data in collection_data.get('emojis', {}).values():
                emoji = EmojiItem.from_dict(emoji_data)
                collection.add_emoji(emoji)
            
            self.collections[collection.name] = collection
            self.logger.info(f"表情集合导入成功: {collection.name}")
            return True
        except Exception as e:
            self.logger.error(f"导入表情集合失败: {e}")
            return False


# 创建全局表情管理器实例
emoji_manager = Emoji()

# 便捷函数
def get_emoji(collection_name: str, name: str) -> Optional[EmojiItem]:
    """获取表情的便捷函数"""
    return emoji_manager.get_emoji(collection_name, name)

def search_emojis(query: str, collection_name: str = None) -> List[Tuple[str, EmojiItem]]:
    """搜索表情的便捷函数"""
    return emoji_manager.search_emojis(query, collection_name)

def use_emoji(collection_name: str, name: str) -> bool:
    """使用表情的便捷函数"""
    return emoji_manager.use_emoji(collection_name, name)

def get_popular_emojis(limit: int = 10) -> List[Tuple[str, EmojiItem]]:
    """获取热门表情的便捷函数"""
    return emoji_manager.get_popular_emojis(limit)