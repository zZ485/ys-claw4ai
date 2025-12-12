import asyncio
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
import pyperclip

# 爬取海关总署法规列表链接
def extract_links(content):
    """
    从Markdown格式的文本中提取所有海关总署法规相关链接
    需要提取的链接示例：http://www.customs.gov.cn/customs/302249/302266/302267/6866912/index.html
    
    参数:
        content (str): 包含Markdown链接的文本内容
        
    返回:
        list: 提取到的所有链接URL列表
    """
    # 匹配海关总署法规链接的正则表达式
    pattern = r'\[.*?\]\((http://www\.customs\.gov\.cn/customs/302249/302266/302267/\d+/index\.html)[^\s\)]*'
    
    # 查找所有匹配的链接
    links = re.findall(pattern, content)
    
    return links


async def get_links():
    all_links = []
    
    # 爬取海关总署法规页面
    await crawl_page(all_links)
    
    # 去重并排序链接
    unique_links = list(set(all_links))
    
    # 按数字部分排序（提取URL中的数字部分）
    def sort_key(url):
        # 从URL中提取数字部分
        # 例如：http://www.customs.gov.cn/customs/302249/302266/302267/6866912/index.html
        parts = url.split('/')
        number = int(parts[-2])  # 获取倒数第二部分（数字）并转为整数
        return number
    
    final_links = sorted(unique_links, key=sort_key)
    
    return {
        "count": len(final_links),
        "links": final_links
    }


async def crawl_page(all_links: list):
    url = "http://www.customs.gov.cn/customs/302249/302266/08654b53-1.html"

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
        # remove_overlay_elements=True,
        # simulate_user=True,
        # override_navigator=True,
        # target_elements=[".easysite-news-title", ".easysite-news-text"]
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=url,
            config=run_config,
        )
        if result.success:
            # # 复制到剪贴板
            # try:
            #     pyperclip.copy(result.markdown)
            #     print("\n内容已成功复制到剪贴板！")
            # except Exception as e:
            #     print(f"\n复制到剪贴板失败: {e}")
            #     print("请安装 pyperclip 库: pip install pyperclip")
            
            links = extract_links(result.markdown.fit_markdown)
            all_links.extend(links)
            print(f"提取到 {len(links)} 个链接")
        else:
            print("页面爬取失败")


async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    result = await get_links()
    
    print(f"\n总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result['links'], 1):
        print(f"{i}. {link}")


if __name__ == "__main__":
    asyncio.run(main())