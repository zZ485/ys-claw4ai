"""
数据库配置模块
用于管理达梦数据库的连接配置
"""

import os
import json
from typing import Dict, Any, Optional
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

        # 如果配置文件中缺少某些字段，从环境变量获取
        db_config = {
            "host": os.getenv("DB_HOST", db_config.get("host", "localhost")),
            "port": int(os.getenv("DB_PORT", str(db_config.get("port", 5236)))),
            "user": os.getenv("DB_USER", db_config.get("user", "SYSDBA")),
            "password": os.getenv("DB_PASSWORD", db_config.get("password", "123456yY")),
            "database": os.getenv("DB_NAME", db_config.get("database", "SYSDBA")),
            "log_sql": os.getenv(
                "DB_LOG_SQL", str(db_config.get("log_sql", "false"))
            ).lower()
            == "true",
            "pool_size": int(
                os.getenv("DB_POOL_SIZE", str(db_config.get("pool_size", "10")))
            ),
        }

        # # 记录当前使用的配置（隐藏密码）
        # logger.info(
        #     f"数据库配置 - 主机: {db_config['host']}, 端口: {db_config['port']}, 用户: {db_config['user']}, 数据库: {db_config['database']}"
        # )

        # 检查是否所有必要的配置都已设置
        missing_fields = [
            k
            for k, v in db_config.items()
            if not v and k in ["user", "password", "database"]
        ]
        if missing_fields:
            logger.warning(f"数据库配置中缺少必要字段: {', '.join(missing_fields)}")

        # 验证端口是否有效
        if not (1 <= db_config["port"] <= 65535):
            logger.error(f"无效的端口号: {db_config['port']}")
            raise ValueError(f"无效的端口号: {db_config['port']}")

        return db_config
    except ValueError as e:
        logger.error(f"数据库配置解析错误: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"获取数据库配置时发生未知错误: {str(e)}")
        # 如果读取配置文件失败，返回默认配置
        logger.warning("使用默认数据库配置")
        return _get_default_config()


def _get_default_config() -> Dict[str, Any]:
    """
    获取默认数据库配置

    Returns:
        Dict: 默认数据库配置信息
    """
    return {
        "host": "localhost",
        "port": 5236,
        "user": "SYSDBA",
        "password": "123456yY",
        "database": "SYSDBA",
        "log_sql": False,
        "pool_size": 10,  # 添加连接池大小的默认配置
    }


def validate_db_config(config: Dict[str, Any]) -> bool:
    """
    验证数据库配置是否有效

    Args:
        config: 数据库配置信息

    Returns:
        bool: 配置是否有效
    """
    required_fields = ["host", "port", "user", "password", "database"]

    for field in required_fields:
        if field not in config or not config[field]:
            logger.error(f"数据库配置缺少必要字段: {field}")
            return False

    return True
