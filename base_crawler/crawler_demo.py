import asyncio
from crawl4ai import AsyncWebCrawler
import pyperclip
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


async def crawl():
    # 获取用户输入的URL
    url = input("请输入要爬取的网页URL: ")
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # remove_overlay_elements=True,  # 移除遮罩层元素（如弹窗广告、cookie提示等）
        # simulate_user=True,         # 模拟真实用户行为，防止被反爬虫机制检测
        # override_navigator=True,     # 覆盖浏览器导航信息，增强反检测能力
        # exclude_external_images=True, # 排除外部图片
        # excluded_tags=[".ebrun-global-header"],
        # css_selector=".con_detail_news"
        # 上海跨境电商协会 行业新闻，政策解读，行业数据，互动交流
        # target_elements=[".page-heading > h1",".post-content > section"]
        # 上海跨境电商协会 最新政策
        # target_elements=[".page-heading > h1",".post-content > h2",".post-content > p"]
        # 亿邦动力 最新全部，独家重磅，商情动态，专栏，专题
        # target_elements=[".post-text-title",".post-text"]
        # 亿邦动力 快讯
        # target_elements=[".post-text-title",".post-text p:first-child"]
        # 电商报 快讯，零售，物流，生活服务，B2B，人物，跨境电商，行业观察
        # target_elements=[".mb-3.border.bg-card.p-9.md\:px-16 > h1","#post-body"]
        # 亿恩网快讯
        # target_elements=[".short_con_content_title",".short_detail",".con_detail_news"]
        # 亿恩网咨讯
        # target_elements=[".short_con_content_title",".con_detail_news:nth-child(1)"]
        # target_elements=[".page-heading > h1", ".post-content > h2", ".post-content > p", ".post-content > section"]
        # target_elements=[".easysite-news-title",".easysite-news-text"]
        # target_elements=[".py-1 > a"]
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
