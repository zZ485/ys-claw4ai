import asyncio
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# 爬取亿恩网资讯链接列表
def extract_urls_from_markdown(text):
    return [url.strip() for url in re.findall(r'\]\((https?://[^\s\)]+)\)', text)]

def extract_id_from_url(url):
    """从URL中提取文章ID"""
    match = re.search(r'article-(\d+)-', url)
    return int(match.group(1)) if match else 0

async def get_links():
    final_links = []
    
    # 爬取多页数据
    for page_num in range(1, 2):  # 爬取前1页
        await crawl_page(page_num, final_links)
    
    # 去重
    final_links = list(set(final_links))
    
    # 根据URL中的ID进行降序排序
    final_links.sort(key=lambda url: extract_id_from_url(url), reverse=True)
    
    return {
        "count": len(final_links),
        "links": final_links
    }


async def crawl_page(page_num: int, all_links: list):
    # https://www.ennews.com/Home/NewsFlash/index?&page=1&page_size=20
    url = f"https://www.ennews.com/Home/NewsFlash/index?&page={page_num}&page_size=20"

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
        target_elements=[".z-con-news"]
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=url,
            config=run_config,
        )
        if result.success:
            links = extract_urls_from_markdown(result.markdown.fit_markdown)
            all_links.extend(links)
            print(f"第 {page_num} 页提取到 {len(links)} 个链接")
        else:
            print(f"第 {page_num} 页爬取失败")


async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    result = await get_links()
    
    print(f"\n总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result['links'], 1):
        print(f"{i}. {link}")


if __name__ == "__main__":
    asyncio.run(main())