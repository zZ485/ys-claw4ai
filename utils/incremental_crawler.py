"""
增量爬取辅助模块
用于处理增量爬取的通用逻辑
"""

import os
import sys
from typing import List, Optional, Dict, Any
from config.logger_config import LoggerConfig
from utils.db_manager import get_db_manager

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


def get_template_name() -> str:
    """
    获取当前脚本的模板名称
    通过获取调用此函数的脚本文件名来确定模板名称

    Returns:
        str: 模板名称
    """
    # 获取调用栈中的第一个不是本文件的文件名
    import inspect

    frame = inspect.currentframe()
    try:
        # 向上查找调用栈，直到找到非本文件的frame
        caller_frame = frame.f_back
        while caller_frame:
            caller_file = caller_frame.f_globals.get("__file__")
            if caller_file and not caller_file.endswith("incremental_crawler.py"):
                # 获取文件名（不带路径和扩展名）
                template_name = os.path.basename(caller_file)
                if template_name.endswith(".py"):
                    template_name = template_name[:-3]
                return template_name
            caller_frame = caller_frame.f_back
        return "unknown"
    finally:
        del frame


async def get_latest_link_from_db(
    template_name: Optional[str] = None, db_manager=None
) -> Optional[str]:
    """
    从数据库获取指定模板的最新链接

    Args:
        template_name: 模板名称，如果不提供则自动获取
        db_manager: 数据库管理器实例，如果不提供则创建新实例

    Returns:
        最新链接URL，如果不存在则返回None
    """
    if template_name is None:
        template_name = get_template_name()

    try:
        # 使用提供的数据库管理器或创建新的实例
        if db_manager is None:
            from utils.db_manager import get_db_manager
            from config.db_config import get_db_config

            db_config = get_db_config()
            db_manager = get_db_manager(
                host=db_config.get("host", "localhost"),
                port=db_config.get("port", 5236),
                user=db_config.get("user", ""),
                password=db_config.get("password", ""),
                database=db_config.get("database", ""),
                log_sql=db_config.get("log_sql", False),
            )

        # 确保数据库已连接
        if not await db_manager.is_connected():
            await db_manager.connect()

        # 获取最新链接
        latest_link = await db_manager.get_latest_link(template_name)

        return latest_link
    except Exception as e:
        logger.error(f"获取最新链接失败: {str(e)}")
        return None


def filter_links_incrementally(
    links: List[str], latest_link: Optional[str]
) -> List[str]:
    """
    过滤链接列表，实现增量爬取逻辑

    Args:
        links: 完整的链接列表
        latest_link: 最新链接URL，如果为None则返回所有链接

    Returns:
        过滤后的链接列表
    """
    if not latest_link:
        logger.info("未找到最新链接，返回所有链接")
        return links

    # 查找最新链接在列表中的位置
    if latest_link in links:
        index = links.index(latest_link)
        # 返回最新链接之前的所有链接（不包括最新链接）
        filtered_links = links[:index]
        logger.info(f"增量爬取：找到最新链接，返回 {len(filtered_links)} 个新链接")
        return filtered_links
    else:
        logger.warning(f"最新链接不在当前链接列表中，返回所有链接")
        return links


async def filter_links_for_crawl(
    links: List[str],
    is_incremental: bool,
    template_name: Optional[str] = None,
    db_manager=None,
) -> List[str]:
    """
    根据是否增量采集模式过滤链接列表

    Args:
        links: 完整的链接列表
        is_incremental: 是否增量采集模式，0表示增量采集，1表示全量采集
        template_name: 模板名称，如果不提供则自动获取
        db_manager: 数据库管理器实例，可选

    Returns:
        过滤后的链接列表
    """
    if not is_incremental:
        # 全量采集模式，返回所有链接
        # logger.info("全量采集模式：返回所有链接")
        return links

    # 增量模式，需要过滤链接
    logger.info("增量模式：正在过滤链接")

    # 从数据库获取最新链接
    latest_link = await get_latest_link_from_db(template_name, db_manager)

    if not latest_link:
        logger.info("未找到最新链接，返回所有链接")
        return links

    # 过滤链接
    return filter_links_incrementally(links, latest_link)


def prepare_links_result(links: List[str], is_incremental: bool) -> Dict[str, Any]:
    """
    准备链接结果，统一返回格式

    Args:
        links: 链接列表
        is_incremental: 是否增量采集模式，0表示增量采集，1表示全量采集

    Returns:
        格式化的结果字典
    """
    return {"count": len(links), "is_incremental": is_incremental, "links": links}
