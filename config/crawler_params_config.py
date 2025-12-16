import json
import os
from typing import Dict, List, Optional, Any
from config.logger_config import LoggerConfig

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


class CrawlerParamsConfig:
    """爬虫参数配置管理类"""

    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CrawlerParamsConfig, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._load_config()
            self._initialized = True

    def _load_config(self):
        """加载配置文件"""
        try:
            # 获取当前文件所在目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(current_dir, "crawler_params_config.json")

            with open(config_file, "r", encoding="utf-8") as f:
                self._config = json.load(f)

            logger.info("爬虫参数配置加载成功")
        except FileNotFoundError:
            logger.error(f"爬虫参数配置文件未找到: {config_file}")
            # 使用默认配置
            self._config = self._get_default_config()
            logger.warning("使用默认爬虫参数配置")
        except json.JSONDecodeError as e:
            logger.error(f"爬虫参数配置文件JSON格式错误: {str(e)}")
            self._config = self._get_default_config()
            logger.warning("使用默认爬虫参数配置")

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "crawler_config": {
                "chunk_size": 8,
                "concurrency_settings": {
                    "max_crawlers_by_url_count": [
                        {"max_urls": 50, "max_crawlers": 2},
                        {"max_urls": 200, "max_crawlers": 4},
                        {"max_urls": 500, "max_crawlers": 6},
                        {"max_urls": 999999, "max_crawlers": 8},
                    ]
                },
                "batch_size_settings": {
                    "by_url_count": [
                        {"max_urls": 50, "batch_size": 5},
                        {"max_urls": 200, "batch_size": 10},
                        {"max_urls": 500, "batch_size": 20},
                        {"max_urls": 999999, "batch_size": 50},
                    ]
                },
                "flush_interval_settings": {
                    "by_url_count": [
                        {"max_urls": 100, "flush_interval": 60},
                        {"max_urls": 500, "flush_interval": 30},
                        {"max_urls": 999999, "flush_interval": 15},
                    ]
                },
                "progress_settings": {
                    "progress_after_fetch": 20,
                    "progress_after_crawl": 90,
                    "progress_complete": 100,
                },
                "error_handling": {
                    "max_retry_attempts": 3,
                    "retry_delay_seconds": 1.0,
                    "log_success_threshold": 100,
                },
            }
        }

    @classmethod
    def reload_config(cls):
        """重新加载配置"""
        if cls._instance is None:
            cls._instance = cls()
        else:
            cls._instance._load_config()
        return cls._instance.get_config()

    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self._config.get("crawler_config", {})

    def get_chunk_size(self) -> int:
        """获取每个爬虫实例处理的URL数量"""
        return self.get_config().get("chunk_size", 8)

    def get_max_crawlers(self, url_count: int) -> int:
        """根据URL数量获取最大并发爬虫实例数"""
        settings = (
            self.get_config()
            .get("concurrency_settings", {})
            .get("max_crawlers_by_url_count", [])
        )
        for setting in settings:
            if url_count <= setting.get("max_urls", 999999):
                return setting.get("max_crawlers", 2)
        return 2

    def get_batch_size(self, url_count: int) -> int:
        """根据URL数量获取批量写入大小"""
        settings = (
            self.get_config().get("batch_size_settings", {}).get("by_url_count", [])
        )
        for setting in settings:
            if url_count <= setting.get("max_urls", 999999):
                return setting.get("batch_size", 10)
        return 10

    def get_flush_interval(self, url_count: int) -> int:
        """根据URL数量获取刷新间隔"""
        settings = (
            self.get_config().get("flush_interval_settings", {}).get("by_url_count", [])
        )
        for setting in settings:
            if url_count <= setting.get("max_urls", 999999):
                return setting.get("flush_interval", 30)
        return 30

    def get_progress_settings(self) -> Dict[str, int]:
        """获取进度设置"""
        return self.get_config().get(
            "progress_settings",
            {
                "progress_after_fetch": 20,
                "progress_after_crawl": 90,
                "progress_complete": 100,
            },
        )

    def get_error_handling_settings(self) -> Dict[str, Any]:
        """获取错误处理设置"""
        return self.get_config().get(
            "error_handling",
            {
                "max_retry_attempts": 3,
                "retry_delay_seconds": 1.0,
                "log_success_threshold": 100,
            },
        )


# 创建全局配置实例
crawler_params_config = CrawlerParamsConfig()
