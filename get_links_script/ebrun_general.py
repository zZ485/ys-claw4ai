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


# 爬取亿邦动力最新全部链接列表
def extract_links(content):
    """
    从Markdown格式的文本中提取所有亿邦动力(ebrun.com)的链接
    仅提取符合日期格式路径的链接（如 /20251204/627854.shtml）

    参数:
        content (str): 包含Markdown链接的文本内容

    返回:
        list: 提取到的所有链接URL列表
    """
    # 修改后的正则表达式，只匹配包含8位日期格式的URL路径
    pattern = r"\[.*?\]\((https://www\.ebrun\.com/\d{8}/\d+\.shtml)[^\s\)]*"

    # 查找所有匹配的链接
    links = re.findall(pattern, content)

    return links


async def get_links(is_incremental=False):
    all_links = []
    tasks = [crawl_page(i, all_links) for i in range(1, 2)]
    await asyncio.gather(*tasks)

    # 去重并排序链接（按日期和数字降序）
    unique_links = list(set(all_links))

    # 自定义排序函数：先按日期降序，再按数字降序
    def sort_key(url):
        # 从URL中提取日期和数字部分
        # 例如：https://www.ebrun.com/20251204/627840.shtml
        parts = url.split("/")
        date = int(parts[3])  # 获取日期部分并转为整数
        number = int(parts[4].split(".")[0])  # 获取数字部分并转为整数
        # 使用负号实现降序
        return (-date, -number)

    final_links = sorted(unique_links, key=sort_key)

    # 根据是否增量模式过滤链接

    filtered_links = await filter_links_for_crawl(final_links, is_incremental)

    # 准备结果

    return prepare_links_result(filtered_links, is_incremental)


async def crawl_page(page_num: int, all_links: list):
    # https://www.ebrun.com/information/1/
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

    # 打印结果
    mode = "增量模式" if result.get("is_incremental") else "全量模式"
    print(f"\n{mode}：总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result["links"], 1):
        print(f"{i}. {link}")


if __name__ == "__main__":
    asyncio.run(main())
