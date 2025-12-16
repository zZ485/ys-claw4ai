import os
import sys

# 添加项目根目录到系统路径，以便导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入增量爬取辅助模块
from utils.incremental_crawler import filter_links_for_crawl, prepare_links_result
import asyncio
import argparse
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator


# 爬取上海跨境电商协会行业新闻链接列表
def extract_links(text):
    """从文本中提取指定格式的链接"""
    pattern = r"https://www\.scea\.co/trends/show/id/(\d+)\.html"
    matches = re.findall(pattern, text)
    # 返回完整链接（去重由外部处理）
    return [f"https://www.scea.co/trends/show/id/{id_}.html" for id_ in matches]


def sort_links_by_id_desc(links):
    """按 ID 数值降序排序链接"""

    def extract_id(link):
        match = re.search(r"/id/(\d+)\.html$", link)
        return int(match.group(1)) if match else -1

    # 去重并保持唯一
    unique_links = list(dict.fromkeys(links))  # 保留顺序去重
    # 按 ID 降序排序
    return sorted(unique_links, key=extract_id, reverse=True)


async def get_links(is_incremental=False):
    """获取SCEA趋势链接列表

    Returns:
        dict: 包含链接数量和链接列表的字典
    """
    all_links = []
    tasks = [crawl_page(i, all_links) for i in range(1, 5)]  # 1 到 10 页
    await asyncio.gather(*tasks)

    # 去重 + 按 ID 降序排序
    final_sorted_links = sort_links_by_id_desc(all_links)

    # 根据是否增量模式过滤链接

    filtered_links = await filter_links_for_crawl(final_sorted_links, is_incremental)

    # 准备结果

    return prepare_links_result(filtered_links, is_incremental)


async def crawl_page(page_num: int, all_links: list):
    url = f"https://www.scea.co/portal/trends/index/p/{page_num}.html"

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

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=url,
            config=run_config,
        )
        if result.success:
            links = extract_links(result.markdown.fit_markdown)
            all_links.extend(links)
            print(f"第 {page_num} 页提取到 {len(links)} 个链接")
        else:
            print(f"第 {page_num} 页爬取失败")


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

    print(f"\n总共提取到 {result['count']} 个唯一链接（按 ID 降序）:")
    for link in result["links"]:
        print(link)


if __name__ == "__main__":
    asyncio.run(main())
