import os
import sys
import asyncio
import argparse
import re

# 添加项目根目录到系统路径，以便导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入配置和增量爬取辅助模块
from config.logger_config import LoggerConfig
from utils.incremental_crawler import (
    filter_links_for_crawl,
    prepare_links_result,
    get_latest_link_from_db,
)
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


# 爬取亿邦动力最新全部链接列表
def extract_links(content):
    """
    从Markdown格式的文本中提取所有亿邦动力(ebrun.com)的链接
    仅提取符合日期格式路径的链接（如 /20251204/627854.shtml）
    """
    # 匹配包含8位日期格式的URL路径
    pattern = r"\[.*?\]\((https://www\.ebrun\.com/\d{8}/\d+\.shtml)[^\s\)]*"

    # 查找所有匹配的链接
    links = re.findall(pattern, content)
    return links


async def get_links(max_pages=None, is_incremental=False):
    all_links = []
    page_num = 1
    should_continue = True

    # 如果是增量模式，先获取最新链接
    latest_link = None
    if is_incremental:
        latest_link = await get_latest_link_from_db()
        if latest_link:
            logger.info(f"增量模式：数据库中最新链接为 {latest_link}")
        else:
            logger.info("增量模式：未找到最新链接，将爬取所有链接")

    while should_continue and (max_pages is None or page_num <= max_pages):
        logger.info(f"正在爬取第 {page_num} 页...")
        page_links = []
        await crawl_page(page_num, page_links)

        if not page_links:
            logger.warning(f"第 {page_num} 页没有提取到链接，停止爬取")
            should_continue = False
            continue

        # 将当前页的链接与已存在的链接合并并去重
        previous_count = len(all_links)
        all_links.extend(page_links)

        # 去重
        unique_links = list(set(all_links))

        # 自定义排序函数：先按日期降序，再按数字降序
        def sort_key(url):
            try:
                # 例如：https://www.ebrun.com/20251204/627840.shtml
                parts = url.split("/")
                date = int(parts[3])  # 获取日期部分
                number = int(parts[4].split(".")[0])  # 获取数字部分
                return (-date, -number)
            except (IndexError, ValueError):
                return (0, 0)

        all_links = sorted(unique_links, key=sort_key)

        # 如果去重后链接数量没有增加，说明该页的链接都已存在
        if len(all_links) == previous_count and page_num > 1:
            logger.info(f"第 {page_num} 页的所有链接都已存在，停止爬取")
            should_continue = False
            continue

        # 增量模式：检查最新链接是否在当前页面中
        if is_incremental and latest_link:
            if latest_link in page_links:
                logger.info(f"第 {page_num} 页包含数据库最新链接，触发增量停止条件")
                # 获取最新链接之前的所有链接（即真正的新链接）
                index = all_links.index(latest_link)
                all_links = all_links[:index]
                should_continue = False
                continue

        logger.info(f"第 {page_num} 页处理完成，当前累计新链接数: {len(all_links)}")
        page_num += 1

    # 准备结果
    return prepare_links_result(all_links, is_incremental)


async def crawl_page(page_num: int, links_list: list):
    url = f"https://www.ebrun.com/information/{page_num}/"

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
        target_elements=[".news-item"],
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        try:
            result = await crawler.arun(
                url=url,
                config=run_config,
            )
            if result.success:
                links = extract_links(result.markdown.fit_markdown)
                links_list.extend(links)
                logger.debug(f"第 {page_num} 页解析成功，提取到 {len(links)} 个链接")
            else:
                logger.error(f"第 {page_num} 页爬取失败: {result.error_message}")
        except Exception as e:
            logger.exception(f"爬取第 {page_num} 页时发生异常: {str(e)}")


async def main():
    """命令行运行时的主函数"""
    # 初始化日志配置
    LoggerConfig.setup_crawler_logger(
        log_file="ebrun_crawler", project_root=project_root
    )

    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="获取亿邦动力文章链接")
    parser.add_argument(
        "--incremental", action="store_true", help="启用增量模式（只获取新的链接）"
    )
    parser.add_argument("--max-pages", type=int, help="限制最大爬取页数（可选）")

    # 解析命令行参数
    args = parser.parse_args()

    logger.info("=== 亿邦动力网文章爬虫启动 ===")
    mode = "增量模式" if args.incremental else "全量模式"
    logger.info(f"爬取模式: {mode}")

    if args.max_pages:
        logger.info(f"最大页面数限制: {args.max_pages}")
    else:
        logger.info("未设置页面限制，将持续爬取直到遇到重复或空页")

    # 调用核心获取函数
    result = await get_links(max_pages=args.max_pages, is_incremental=args.incremental)

    # 输出最终结果概览
    final_mode = "增量模式" if result.get("is_incremental") else "全量模式"
    logger.info(f"任务结束 [{final_mode}]：总共获取到 {result['count']} 个新链接")

    # 如果链接不多，打印出来；如果太多，只打印前5条
    links_to_show = result["links"]
    for i, link in enumerate(links_to_show[:10], 1):
        logger.info(f"链接 {i}: {link}")

    if len(links_to_show) > 10:
        logger.info(f"... 等共 {len(links_to_show)} 条链接")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("用户手动停止了爬虫任务")
    except Exception as e:
        logger.critical(f"系统未捕获异常: {str(e)}")
