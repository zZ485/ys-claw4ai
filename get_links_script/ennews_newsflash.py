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
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator


def extract_id_from_url(url):
    """从快讯URL中提取文章ID"""
    match = re.search(r"news-(\d+)\.html", url)
    return int(match.group(1)) if match else 0


async def get_links(is_incremental=False):
    """获取最新快讯链接列表"""
    # 访问快讯首页获取最新文章ID
    url = "https://www.ennews.com/news/"

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
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=url,
            config=run_config,
        )

        if not result.success:
            print("获取快讯首页失败")
            return prepare_links_result([], is_incremental)

        # 从markdown内容中提取最新文章链接
        latest_url = None
        latest_id = 0

        # 寻找最新快讯URL，尝试多种匹配模式
        content = result.markdown.fit_markdown

        # 模式1: 直接匹配 [标题](URL) 格式
        pattern1 = re.findall(
            r"\[([^\]]*)\]\((https://www\.ennews\.com/news-(\d+)\.html)\)", content
        )

        if pattern1:
            for title, url, article_id in pattern1:
                article_id = int(article_id)
                if article_id > latest_id:
                    latest_id = article_id
                    latest_url = url

        # 如果模式1没有找到，尝试模式2: 任何包含news-数字.html格式的URL
        if not latest_url:
            pattern2 = re.findall(
                r"(https://www\.ennews\.com/news-(\d+)\.html)", content
            )
            for url, article_id in pattern2:
                article_id = int(article_id)
                if article_id > latest_id:
                    latest_id = article_id
                    latest_url = url

        if not latest_url:
            print("未找到最新快讯链接")
            return prepare_links_result([], is_incremental)

        # 如果是增量模式，先获取数据库中的最新链接
        latest_link = None
        if is_incremental:
            latest_link = await get_latest_link_from_db()
            if latest_link:
                print(f"增量模式：最新链接为 {latest_link}")
            else:
                print("增量模式：未找到最新链接，将生成所有链接")

        # 基于最新ID生成链接列表
        final_links = []
        should_continue = True
        current_id = latest_id

        while should_continue and current_id > 0:
            link = f"https://www.ennews.com/news-{current_id}.html"

            # 增量模式：检查是否已达到数据库中的最新链接
            if is_incremental and latest_link and link == latest_link:
                print(f"增量模式：已达到最新链接 {latest_link}，停止生成")
                should_continue = False
                break

            final_links.append(link)

            # 全量模式：如果已经生成到news-1.html，则停止
            if not is_incremental and current_id == 1:
                print("全量模式：已生成到 news-1.html，停止生成")
                should_continue = False
                break

            current_id -= 1

        # 准备结果
        return prepare_links_result(final_links, is_incremental)


async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="获取链接")
    parser.add_argument(
        "--incremental", action="store_true", help="启用增量模式（只获取新的链接）"
    )

    # 解析命令行参数
    args = parser.parse_args()

    # 调用get_links函数
    result = await get_links(is_incremental=args.incremental)

    print(f"\n获取到最新快讯ID: {result.get('latest_id', 'N/A')}")
    print(f"总共生成 {result['count']} 个链接:")
    for i, link in enumerate(result["links"], 1):
        print(f"{i}. {link}")


if __name__ == "__main__":
    asyncio.run(main())
