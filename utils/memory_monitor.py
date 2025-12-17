import os
import psutil
import logging
from typing import Dict, Any, Optional

from config.logger_config import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class MemoryMonitor:
    """内存监控工具类"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MemoryMonitor, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.process = psutil.Process(os.getpid())
            self._initialized = True

    def get_memory_info(self) -> Dict[str, Any]:
        """获取当前进程的内存使用信息"""
        try:
            memory_info = self.process.memory_info()
            memory_percent = self.process.memory_percent()

            return {
                "rss_mb": memory_info.rss / 1024 / 1024,  # 物理内存使用量(MB)
                "vms_mb": memory_info.vms / 1024 / 1024,  # 虚拟内存使用量(MB)
                "percent": memory_percent,  # 占总内存的百分比
                "available_mb": psutil.virtual_memory().available
                / 1024
                / 1024,  # 系统可用内存(MB)
            }
        except Exception as e:
            logger.error(f"获取内存信息失败: {str(e)}")
            return {}

    def check_memory_threshold(self, threshold_percent: float = 80.0) -> bool:
        """检查内存使用是否超过阈值

        Args:
            threshold_percent: 内存使用阈值百分比，默认80%

        Returns:
            bool: True表示超过阈值，False表示未超过
        """
        try:
            memory_info = self.get_memory_info()
            current_percent = memory_info.get("percent", 0)

            if current_percent > threshold_percent:
                logger.warning(
                    f"内存使用率过高: {current_percent:.2f}% > {threshold_percent}%"
                )
                return True

            return False
        except Exception as e:
            logger.error(f"检查内存阈值失败: {str(e)}")
            return False

    def log_memory_usage(self, context: str = "", log_level: str = "warning"):
        """记录当前内存使用情况

        Args:
            context: 上下文信息，用于日志记录
            log_level: 日志级别，"info"或"warning"，默认为"warning"表示仅在内存使用率高时记录
        """
        try:
            memory_info = self.get_memory_info()
            if memory_info:
                # 仅在内存使用率超过60%或明确要求info级别时才记录
                if memory_info["percent"] > 60 or log_level == "info":
                    context_str = f"[{context}] " if context else ""
                    log_msg = (
                        f"{context_str}内存使用情况: "
                        f"物理内存={memory_info['rss_mb']:.2f}MB, "
                        f"虚拟内存={memory_info['vms_mb']:.2f}MB, "
                        f"使用率={memory_info['percent']:.2f}%, "
                        f"系统可用={memory_info['available_mb']:.2f}MB"
                    )

                    if memory_info["percent"] > 80:
                        logger.warning(log_msg)
                    else:
                        logger.info(log_msg)
        except Exception as e:
            logger.error(f"记录内存使用情况失败: {str(e)}")

    def get_memory_recommendations(self, url_count: int) -> Dict[str, Any]:
        """根据URL数量和当前内存情况提供内存优化建议

        Args:
            url_count: 要处理的URL数量

        Returns:
            Dict: 包含内存优化建议的字典
        """
        try:
            memory_info = self.get_memory_info()
            if not memory_info:
                return {}

            # 基础建议
            recommendations = {
                "url_count": url_count,
                "current_memory_mb": memory_info["rss_mb"],
                "memory_percent": memory_info["percent"],
                "enable_memory_optimization": False,
                "recommended_batch_size": 20,
                "recommended_concurrency": 4,
                "recommended_flush_interval": 15,
            }

            # 根据内存使用情况和URL数量调整建议
            if url_count > 1000 or memory_info["percent"] > 60:
                recommendations["enable_memory_optimization"] = True

                if memory_info["percent"] > 80:
                    # 内存使用率高，大幅降低并发和批量大小
                    recommendations["recommended_batch_size"] = 10
                    recommendations["recommended_concurrency"] = 2
                    recommendations["recommended_flush_interval"] = 5
                elif memory_info["percent"] > 60:
                    # 内存使用率中等，适度降低参数
                    recommendations["recommended_batch_size"] = 15
                    recommendations["recommended_concurrency"] = 3
                    recommendations["recommended_flush_interval"] = 10

            return recommendations
        except Exception as e:
            logger.error(f"生成内存优化建议失败: {str(e)}")
            return {}


# 创建全局内存监控实例
memory_monitor = MemoryMonitor()
