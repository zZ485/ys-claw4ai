import os
import json
from typing import Optional


class KnowledgeBaseConfig:
    """知识库配置类，用于管理知识库相关配置"""

    _config_cache = None
    _config_file_path = None

    @classmethod
    def _get_config_file_path(cls) -> str:
        """获取配置文件路径"""
        if cls._config_file_path is None:
            # 获取当前文件所在目录的绝对路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            cls._config_file_path = os.path.join(
                current_dir, "knowledge_base_config.json"
            )
        return cls._config_file_path

    @classmethod
    def _load_config(cls) -> dict:
        """从JSON文件加载配置"""
        if cls._config_cache is not None:
            return cls._config_cache

        config_file = cls._get_config_file_path()

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
                cls._config_cache = config.get("knowledge_base", {})
                return cls._config_cache
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"警告: 无法加载知识库配置文件 {config_file}: {str(e)}")
            # 返回默认配置
            cls._config_cache = {
                "api_base_url": "http://192.168.9.47:8000",
                "upload_timeout": 300,
                "auto_upload": True,
            }
            return cls._config_cache

    @classmethod
    def _reload_config(cls) -> dict:
        """重新加载配置文件"""
        cls._config_cache = None
        return cls._load_config()

    @staticmethod
    def get_api_base_url() -> str:
        """获取知识库API基础URL

        Returns:
            str: 知识库API基础URL
        """
        config = KnowledgeBaseConfig._load_config()
        # 优先从环境变量获取，如果不存在则使用配置文件值
        return os.environ.get(
            "KNOWLEDGE_BASE_API_URL",
            config.get("api_base_url", "http://192.168.9.47:8000"),
        )

    @staticmethod
    def get_upload_timeout() -> int:
        """获取上传超时时间

        Returns:
            int: 上传超时时间(秒)
        """
        config = KnowledgeBaseConfig._load_config()
        # 优先从环境变量获取，如果不存在则使用配置文件值
        try:
            timeout = os.environ.get(
                "KNOWLEDGE_BASE_UPLOAD_TIMEOUT", str(config.get("upload_timeout", 300))
            )
            return int(timeout)
        except (ValueError, TypeError):
            return 300

    @staticmethod
    def is_auto_upload_enabled() -> bool:
        """检查是否启用自动上传功能

        Returns:
            bool: 是否启用自动上传
        """
        config = KnowledgeBaseConfig._load_config()
        # 优先从环境变量获取，如果不存在则使用配置文件值
        enabled = os.environ.get(
            "KNOWLEDGE_BASE_AUTO_UPLOAD", str(config.get("auto_upload", True))
        )
        return enabled.lower() in ("true", "1", "yes", "on")

    @classmethod
    def get_all_config(cls) -> dict:
        """获取所有知识库配置

        Returns:
            dict: 包含所有知识库配置的字典
        """
        config = cls._load_config()
        return {
            "api_base_url": cls.get_api_base_url(),
            "upload_timeout": cls.get_upload_timeout(),
            "auto_upload": cls.is_auto_upload_enabled(),
        }
