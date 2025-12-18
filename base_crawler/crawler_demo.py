import asyncio
from crawl4ai import AsyncWebCrawler
import pyperclip
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


async def crawl():
    # 获取用户输入的URL
    url = input("请输入要爬取的网页URL: ")
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
    )

    browser_config = BrowserConfig(
        # headless=True,
        # verbose=False,
        # text_mode=True,
        user_agent_mode="random"
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        # 爬取网站
        result = await crawler.arun(url=url, config=run_config)

        # 检查结果是否有效
        if not result:
            print("❌ 未能获取到结果")
            return

        # 复制到剪贴板
        try:
            pyperclip.copy(result.markdown)
            print("\n内容已成功复制到剪贴板！")
        except Exception as e:
            print(f"\n复制到剪贴板失败: {e}")
            print("请安装 pyperclip 库: pip install pyperclip")


if __name__ == "__main__":
    asyncio.run(crawl())
