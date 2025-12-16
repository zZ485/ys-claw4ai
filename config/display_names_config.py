"""
配置显示名称映射
用于存储各个配置的显示名称和实际键值的映射关系
"""

import json
import os
from typing import Dict

# 获取配置文件路径
CONFIG_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "display_names_config.json"
)


def load_config() -> Dict[str, str]:
    """
    从JSON配置文件中加载配置

    Returns:
        配置字典，如果加载失败则返回空字典
    """
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            return config_data.get("config_display_names", {})
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return {}


class ConfigDisplayNames:
    """配置显示名称管理类"""

    @classmethod
    def get_all_display_names(cls) -> Dict[str, str]:
        """
        获取所有配置的显示名称映射

        Returns:
            配置键值到显示名称的映射字典
        """
        return load_config().copy()

    @classmethod
    def get_display_name(cls, config_key: str) -> str:
        """
        获取指定配置的显示名称

        Args:
            config_key: 配置键值

        Returns:
            对应的显示名称，如果不存在则返回原始键值
        """
        config = load_config()
        return config.get(config_key, config_key)

    @classmethod
    def get_formatted_configs(cls) -> list:
        """
        获取格式化的配置列表，用于API返回

        Returns:
            格式化后的配置列表，每个元素包含key和value
        """
        config = load_config()
        formatted_configs = []
        for config_key in config.keys():
            display_name = config[config_key]
            formatted_configs.append({"key": display_name, "value": config_key})
        return formatted_configs

    @classmethod
    def add_config(cls, config_key: str, display_name: str) -> bool:
        """
        添加新的配置项

        Args:
            config_key: 配置键值
            display_name: 显示名称

        Returns:
            是否添加成功
        """
        config = load_config()
        config[config_key] = display_name
        return cls.update_config(config)

    @classmethod
    def display_name_exists(cls, display_name: str) -> bool:
        """
        检查指定的显示名称是否存在

        Args:
            display_name: 显示名称

        Returns:
            显示名称是否存在
        """
        config = load_config()
        return display_name in config.values()

    @classmethod
    def reload_config(cls) -> Dict[str, str]:
        """
        重新加载配置

        Returns:
            最新的配置字典
        """
        return load_config()

    @classmethod
    def update_config(cls, config_dict: Dict[str, str]) -> bool:
        """
        更新配置并保存到JSON文件

        Args:
            config_dict: 新的配置字典

        Returns:
            是否更新成功
        """
        try:
            # 创建完整的数据结构
            data = {"config_display_names": config_dict}

            # 写入JSON文件
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            return True
        except Exception as e:
            print(f"更新配置文件失败: {e}")
            return False
