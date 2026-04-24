"""
数据库配置模块
用于管理 SQLite 数据库的连接配置
兼容旧版达梦数据库配置接口
"""

import os
import json
from typing import Any, Dict

from config.logger_config import LoggerConfig

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


def get_db_config() -> Dict[str, Any]:
    """
    获取数据库配置信息

    Returns:
        Dict: 数据库配置信息
    """
    try:
        # 获取配置文件路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, "config", "db_config.json")

        # 检查配置文件是否存在
        if not os.path.exists(config_path):
            logger.warning(f"数据库配置文件不存在: {config_path}，使用默认配置")
            return _get_default_config()

        # 读取配置文件
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        db_config = config_data.get("database", {})

        # 构建配置（保留旧字段以兼容上层代码，但 SQLite 不使用它们）
        result = {
            "type": db_config.get("type", "sqlite"),
            "database": os.getenv("DB_NAME", db_config.get("database", "crawler")),
            "log_sql": os.getenv(
                "DB_LOG_SQL", str(db_config.get("log_sql", "false"))
            ).lower()
            == "true",
            "pool_size": int(
                os.getenv("DB_POOL_SIZE", str(db_config.get("pool_size", "5")))
            ),
            # 以下字段保留以兼容旧接口，SQLite 不使用
            "host": "localhost",
            "port": 0,
            "user": "",
            "password": "",
        }

        return result
    except ValueError as e:
        logger.error(f"数据库配置解析错误: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"获取数据库配置时发生未知错误: {str(e)}")
        logger.warning("使用默认数据库配置")
        return _get_default_config()


def _get_default_config() -> Dict[str, Any]:
    """
    获取默认数据库配置

    Returns:
        Dict: 默认数据库配置信息
    """
    return {
        "type": "sqlite",
        "host": "localhost",
        "port": 0,
        "user": "",
        "password": "",
        "database": "crawler",
        "log_sql": False,
        "pool_size": 5,
    }


def validate_db_config(config: Dict[str, Any]) -> bool:
    """
    验证数据库配置是否有效

    Args:
        config: 数据库配置信息

    Returns:
        bool: 配置是否有效
    """
    # SQLite 只需要 database 字段
    if "database" not in config or not config["database"]:
        logger.error("数据库配置缺少必要字段: database")
        return False

    return True
