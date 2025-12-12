import asyncio
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# 爬取上海跨境电商协会政策解读链接列表
def extract_links(text):
    """从文本中提取指定格式的链接"""
    # https://www.scea.co/policy/show/id/3455.html
    pattern = r'https://www\.scea\.co/policy/show/id/(\d+)\.html'
    matches = re.findall(pattern, text)
    # 返回完整链接（去重由外部处理）
    return [f"https://www.scea.co/policy/show/id/{id_}.html" for id_ in matches]


def sort_links_by_id_desc(links):
    """按 ID 数值降序排序链接"""
    def extract_id(link):
        match = re.search(r'/id/(\d+)\.html$', link)
        return int(match.group(1)) if match else -1

    # 去重并保持唯一
    unique_links = list(dict.fromkeys(links))  # 保留顺序去重
    # 按 ID 降序排序
    return sorted(unique_links, key=extract_id, reverse=True)


async def get_links():
    """获取SCEA趋势链接列表
    
    Returns:
        dict: 包含链接数量和链接列表的字典
    """
    all_links = []
    tasks = [crawl_page(i, all_links) for i in range(1, 2)]  # 1 到 10 页
    await asyncio.gather(*tasks)

    # 去重 + 按 ID 降序排序
    final_sorted_links = sort_links_by_id_desc(all_links)
    
    return {
        "count": len(final_sorted_links),
        "links": final_sorted_links
    }


async def crawl_page(page_num: int, all_links: list):
    # https://www.scea.co/portal/policy/read/p/1.html
    url = f"https://www.scea.co/portal/policy/read/p/{page_num}.html"

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        text_mode=True,
        user_agent_mode="random"
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.48, threshold_type="fixed", min_word_threshold=0)
        ),
        remove_overlay_elements=True,
        simulate_user=True,
        override_navigator=True,
        target_elements=[".blog-post"]
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
    result = await get_links()
    
    print(f"\n总共提取到 {result['count']} 个唯一链接（按 ID 降序）:")
    for link in result['links']:
        print(link)


if __name__ == "__main__":
    asyncio.run(main())