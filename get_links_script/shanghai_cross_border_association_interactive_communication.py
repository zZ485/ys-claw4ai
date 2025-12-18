import os
import sys

# 添加项目根目录到系统路径，以便导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入增量爬取辅助模块
from utils.incremental_crawler import (
    filter_links_for_crawl,
    prepare_links_result,
    get_latest_link_from_db,
)
import asyncio
import argparse
import re
import time
from typing import List, Optional
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from config.logger_config import LoggerConfig

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)

# 配置最大重试次数
MAX_RETRIES = 3


# 爬取上海跨境电商协会互动交流链接列表
def extract_links(text):
    """从文本中提取指定格式的链接"""
    # https://www.scea.co/assoc/show/id/3740.html
    pattern = r"https://www\.scea\.co/assoc/show/id/(\d+)\.html"
    matches = re.findall(pattern, text)
    # 返回完整链接（去重由外部处理）
    return [f"https://www.scea.co/assoc/show/id/{id_}.html" for id_ in matches]


def sort_links_by_id_desc(links):
    """按 ID 数值降序排序链接"""

    def extract_id(link):
        match = re.search(r"/id/(\d+)\.html$", link)
        return int(match.group(1)) if match else -1

    # 去重并保持唯一
    unique_links = list(dict.fromkeys(links))  # 保留顺序去重
    # 按 ID 降序排序
    return sorted(unique_links, key=extract_id, reverse=True)


async def get_links(is_incremental=False, max_pages=None):
    """获取SCEA互动交流链接列表

    Args:
        is_incremental: 是否启用增量模式
        max_pages: 最大爬取页面数（None表示不限制）

    Returns:
        dict: 包含链接数量和链接列表的字典
    """
    all_links = []
    page_num = 1
    should_continue = True

    # 如果是增量模式，先获取最新链接
    latest_link = None
    if is_incremental:
        latest_link = await get_latest_link_from_db()
        if latest_link:
            logger.info(f"增量模式：最新链接为 {latest_link}")
        else:
            logger.info("增量模式：未找到最新链接，将爬取所有链接")

    # 创建单一的浏览器实例，复用于所有页面爬取
    browser_config = BrowserConfig(
        headless=True, verbose=False, text_mode=True, user_agent_mode="random"
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(
                threshold=0.48, threshold_type="fixed", min_word_threshold=0
            )
        ),
        remove_overlay_elements=True,
        simulate_user=True,
        override_navigator=True,
        target_elements=[".blog-post"],
    )

    # 使用上下文管理器创建单一爬虫实例
    async with AsyncWebCrawler(config=browser_config) as crawler:
        while should_continue:
            # 检查是否达到最大页面数限制
            if max_pages is not None and page_num > max_pages:
                logger.info(f"已达到最大页面数限制 {max_pages}，停止爬取")
                break

            logger.info(f"正在爬取第 {page_num} 页...")
            page_links = []

            # 使用重试机制爬取当前页面
            success = await crawl_page_with_retry(
                crawler,
                page_num,
                page_links,
                run_config,
                max_retries=MAX_RETRIES,
                delay=2,
            )

            # 如果所有重试都失败，停止爬取
            if not success:
                logger.error(f"第 {page_num} 页爬取失败，已达最大重试次数，停止爬取")
                should_continue = False
                continue

            if not page_links:
                logger.warning(f"第 {page_num} 页没有提取到链接，停止爬取")
                should_continue = False
                continue

            # 将当前页的链接与已存在的链接合并并去重
            previous_count = len(all_links)
            all_links.extend(page_links)
            all_links = sort_links_by_id_desc(all_links)

            # 如果去重后链接数量没有增加，说明该页的链接都已存在，停止爬取
            if len(all_links) == previous_count:
                logger.info(f"第 {page_num} 页的所有链接都已存在，停止爬取")
                should_continue = False
                continue

            # 增量模式：检查最新链接是否在当前页面中
            if is_incremental and latest_link:
                if latest_link in page_links:
                    logger.info(f"第 {page_num} 页包含最新链接，停止爬取")
                    # 获取最新链接之前的所有链接
                    index = all_links.index(latest_link)
                    all_links = all_links[:index]
                    should_continue = False
                    continue

            logger.info(
                f"第 {page_num} 页新增了 {len(all_links) - previous_count} 个新链接"
            )
            page_num += 1

    # 按 ID 降序排序
    final_sorted_links = sort_links_by_id_desc(all_links)

    # 准备结果
    return prepare_links_result(final_sorted_links, is_incremental)


async def crawl_page(page_num: int, links_list: list, crawler, run_config):
    """爬取单个页面（使用已创建的爬虫实例）

    Args:
        page_num: 页码
        links_list: 用于存储提取的链接的列表
        crawler: 已创建的爬虫实例
        run_config: 爬取配置

    Returns:
        bool: 爬取是否成功
    """
    # https://www.scea.co/portal/assoc/bulletin/p/1.html
    url = f"https://www.scea.co/portal/assoc/bulletin/p/{page_num}.html"

    try:
        result = await crawler.arun(url=url, config=run_config)
        if result.success:
            links = extract_links(result.markdown.fit_markdown)
            links_list.extend(links)
            logger.debug(f"第 {page_num} 页提取到 {len(links)} 个链接")
            return True
        else:
            logger.error(
                f"第 {page_num} 页爬取失败: {result.error_message if hasattr(result, 'error_message') else '未知错误'}"
            )
            return False
    except Exception as e:
        logger.error(f"第 {page_num} 页爬取异常: {str(e)}")
        return False


async def crawl_page_with_retry(
    crawler,
    page_num: int,
    links_list: list,
    run_config,
    max_retries: int = None,
    delay: int = 2,
):
    """带有重试机制的页面爬取函数

    Args:
        crawler: 已创建的爬虫实例
        page_num: 页码
        links_list: 用于存储提取的链接的列表
        run_config: 爬取配置
        max_retries: 最大重试次数，默认使用全局配置
        delay: 重试间隔（秒）

    Returns:
        bool: 爬取是否最终成功
    """
    # 使用默认值
    if max_retries is None:
        max_retries = MAX_RETRIES

    for attempt in range(1, max_retries + 1):
        logger.info(f"尝试爬取第 {page_num} 页，第 {attempt} 次/共 {max_retries} 次")

        success = await crawl_page(page_num, links_list, crawler, run_config)

        if success:
            return True

        # 如果不是最后一次尝试，等待后重试
        if attempt < max_retries:
            logger.info(f"第 {attempt} 次尝试失败，{delay} 秒后重试...")
            await asyncio.sleep(delay)
            # 随着重试次数增加，延长等待时间
            delay = int(delay * 1.5)  # 确保延迟时间是整数

    logger.error(f"第 {page_num} 页爬取失败，已达到最大重试次数 {max_retries}")
    return False


async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="获取链接")
    parser.add_argument(
        "--incremental", action="store_true", help="启用增量模式（只获取新的链接）"
    )
    parser.add_argument("--output", "-o", type=str, help="输出结果到文件（可选）")
    parser.add_argument(
        "--max-pages", type=int, help="最大爬取页面数（可选，默认不限制）"
    )

    # 解析命令行参数
    args = parser.parse_args()

    try:
        start_time = time.time()

        # 调用get_links函数
        result = await get_links(
            is_incremental=args.incremental, max_pages=args.max_pages
        )

        end_time = time.time()
        elapsed = end_time - start_time

        logger.info(f"\n总共提取到 {result['count']} 个唯一链接（按 ID 降序）:")
        for link in result["links"]:
            logger.info(link)

        logger.info(f"爬取完成，耗时: {elapsed:.2f} 秒")

        # 如果指定了输出文件，将结果写入文件
        if args.output:
            try:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(f"# 上海跨境电商协会互动交流链接\n\n")
                    f.write(f"总链接数: {result['count']}\n")
                    f.write(f"爬取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(
                        f"增量模式: {'是' if result['is_incremental'] else '否'}\n\n"
                    )
                    f.write("## 链接列表\n\n")
                    for link in result["links"]:
                        f.write(f"{link}\n")
                logger.info(f"结果已保存到文件: {args.output}")
            except Exception as e:
                logger.error(f"保存文件失败: {str(e)}")

    except KeyboardInterrupt:
        logger.info("用户中断爬取")
    except Exception as e:
        logger.error(f"爬取过程出错: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
