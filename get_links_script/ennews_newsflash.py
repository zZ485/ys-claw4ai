import asyncio
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

def extract_id_from_url(url):
    """从快讯URL中提取文章ID"""
    match = re.search(r'news-(\d+)\.html', url)
    return int(match.group(1)) if match else 0

async def get_links():
    """获取最新快讯链接列表"""
    # 访问快讯首页获取最新文章ID
    url = "https://www.ennews.com/news/"
    
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
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=url,
            config=run_config,
        )
        
        if not result.success:
            print("获取快讯首页失败")
            return {"count": 0, "links": []}
        
        # 从markdown内容中提取最新文章链接
        latest_url = None
        latest_id = 0
        
        # 寻找最新快讯URL，尝试多种匹配模式
        content = result.markdown.fit_markdown
        
        # 模式1: 直接匹配 [标题](URL) 格式
        pattern1 = re.findall(r'\[([^\]]*)\]\((https://www\.ennews\.com/news-(\d+)\.html)\)', content)
        
        if pattern1:
            for title, url, article_id in pattern1:
                article_id = int(article_id)
                if article_id > latest_id:
                    latest_id = article_id
                    latest_url = url
        
        # 如果模式1没有找到，尝试模式2: 任何包含news-数字.html格式的URL
        if not latest_url:
            pattern2 = re.findall(r'(https://www\.ennews\.com/news-(\d+)\.html)', content)
            for url, article_id in pattern2:
                article_id = int(article_id)
                if article_id > latest_id:
                    latest_id = article_id
                    latest_url = url
        
        if not latest_url:
            print("未找到最新快讯链接")
            return {"count": 0, "links": []}
        
        # 基于最新ID，生成最多50条链接
        max_links = 50
        final_links = []
        
        for i in range(max_links):
            current_id = latest_id - i
            if current_id <= 0:
                break
            link = f"https://www.ennews.com/news-{current_id}.html"
            final_links.append(link)
        
        return {
            "count": len(final_links),
            "links": final_links
        }

async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    result = await get_links()
    
    print(f"\n获取到最新快讯ID: {result.get('latest_id', 'N/A')}")
    print(f"总共生成 {result['count']} 个链接:")
    for i, link in enumerate(result['links'], 1):
        print(f"{i}. {link}")

if __name__ == "__main__":
    asyncio.run(main())