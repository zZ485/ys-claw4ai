"""
目标元素配置类
用于定义各种网站的CSS选择器预设配置
"""
import json
import os
from typing import Dict, List, Optional

# 获取配置文件路径
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "target_elements_config.json")

def load_config() -> Dict[str, List[str]]:
    """
    从JSON配置文件中加载配置
    
    Returns:
        配置字典，如果加载失败则返回空字典
    """
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            return config_data.get('preset_configs', {})
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return {}

class TargetElementsConfig:
    """目标元素配置类"""
    
    @classmethod
    def get_config(cls, config_name: str) -> Optional[List[str]]:
        """
        获取指定名称的配置
        
        Args:
            config_name: 配置名称
            
        Returns:
            CSS选择器列表，如果配置不存在则返回None
        """
        config = load_config()
        return config.get(config_name)
    
    @classmethod
    def get_all_configs(cls) -> Dict[str, List[str]]:
        """
        获取所有预设配置
        
        Returns:
            包含所有预设配置的字典
        """
        return load_config().copy()
    
    @classmethod
    def config_exists(cls, config_name: str) -> bool:
        """
        检查指定名称的配置是否存在
        
        Args:
            config_name: 配置名称
            
        Returns:
            配置是否存在
        """
        config = load_config()
        return config_name in config
    
    @classmethod
    def get_config_names(cls) -> List[str]:
        """
        获取所有配置名称
        
        Returns:
            配置名称列表
        """
        config = load_config()
        return list(config.keys())
    
    @classmethod
    def reload_config(cls) -> Dict[str, List[str]]:
        """
        重新加载配置
        
        Returns:
            最新的配置字典
        """
        return load_config()
    
    @classmethod
    def update_config(cls, config_dict: Dict[str, List[str]]) -> bool:
        """
        更新配置并保存到JSON文件
        
        Args:
            config_dict: 新的配置字典
            
        Returns:
            是否更新成功
        """
        try:
            # 创建完整的数据结构
            data = {"preset_configs": config_dict}
            
            # 写入JSON文件
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"更新配置文件失败: {e}")
            return False
    
    @classmethod
    def add_config(cls, config_name: str, selectors: List[str]) -> bool:
        """
        添加新的配置项
        
        Args:
            config_name: 配置名称
            selectors: CSS选择器列表
            
        Returns:
            是否添加成功
        """
        config = load_config()
        config[config_name] = selectors
        return cls.update_config(config)