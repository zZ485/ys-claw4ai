import asyncio
import re
import json
from datetime import datetime
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
import pyperclip
import sys
import os

# 添加项目根目录到系统路径，以便导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入增量爬取辅助模块
from utils.incremental_crawler import filter_links_for_crawl, prepare_links_result


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
    pattern = r"\[.*?\]\((http://www\.customs\.gov\.cn/customs/302249/302266/302267/\d+/index\.html)[^\s\)]*"

    # 查找所有匹配的链接
    links = re.findall(pattern, content)

    return links


async def get_links(
    is_incremental=False, max_pages=198, use_dynamic_proxy: bool = False
):
    """
    获取海关总署法规链接并保存到文件

    Args:
        is_incremental: 是否增量模式，默认为False（全量模式）
        max_pages: 最大爬取页数，默认为5页
        use_dynamic_proxy: 是否使用动态代理，默认为False

    Returns:
        dict: 包含链接数量和链接列表的字典
    """
    all_links = []

    # 爬取海关总署法规页面
    await crawl_page(all_links, max_pages, use_dynamic_proxy=use_dynamic_proxy)

    # 去重并排序链接
    unique_links = list(set(all_links))

    # 按数字部分排序（提取URL中的数字部分）
    def sort_key(url):
        # 从URL中提取数字部分
        # 例如：http://www.customs.gov.cn/customs/302249/302266/302267/6866912/index.html
        parts = url.split("/")
        number = int(parts[-2])  # 获取倒数第二部分（数字）并转为整数
        return number

    sorted_links = sorted(unique_links, key=sort_key)

    # 根据是否增量模式过滤链接
    filtered_links = await filter_links_for_crawl(sorted_links, is_incremental)

    # 准备结果
    result = prepare_links_result(filtered_links, is_incremental)

    # 保存结果到文件
    url_list_dir = os.path.join(project_root, "url_list")
    os.makedirs(url_list_dir, exist_ok=True)

    # 生成文件名：customs_regulations_模式_时间戳.json
    mode_suffix = "incremental" if result.get("is_incremental") else "full"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"customs_regulations_{mode_suffix}_{timestamp}.json"
    filepath = os.path.join(url_list_dir, filename)

    # 写入文件
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n链接已保存到文件: {filepath}")

    return result


async def crawl_page(all_links: list, max_pages=2, use_dynamic_proxy: bool = False):
    """爬取多个页面的法规链接

    Args:
        all_links: 存储所有链接的列表
        max_pages: 最大爬取页数，默认为5页
        use_dynamic_proxy: 是否使用动态代理，默认为False
    """
    browser_config = BrowserConfig(
        headless=True, verbose=False, text_mode=True, user_agent_mode="random"
    )

    # 构建run_config
    run_config_kwargs = {
        "cache_mode": CacheMode.BYPASS,
        "markdown_generator": DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(
                threshold=0.48, threshold_type="fixed", min_word_threshold=0
            )
        ),
    }

    # 如果启用动态代理，添加代理轮询策略
    if use_dynamic_proxy:
        from utils.crawler_utils import get_global_proxy_pool

        proxy_pool = get_global_proxy_pool()
        if proxy_pool.is_ready():
            proxy_strategy = proxy_pool.get_proxy_strategy()
            if proxy_strategy:
                run_config_kwargs["proxy_rotation_strategy"] = proxy_strategy
                print(f"已启用动态代理轮询，代理数量: {len(proxy_pool.proxy_configs)}")
            else:
                print("警告: 代理池未就绪，不使用代理进行爬取")
        else:
            print("警告: 代理池未就绪，不使用代理进行爬取")

    run_config = CrawlerRunConfig(**run_config_kwargs)

    total_links = 0

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for page_num in range(1, max_pages + 1):
            url = f"http://www.customs.gov.cn/eportal/ui?pageId=302266&currentPage={page_num}&moduleId=08654b53d1cc42478813b0b2feddcb57&staticRequest=yes"
            print(f"正在爬取第 {page_num} 页: {url}")

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
                total_links += len(links)
                print(f"第 {page_num} 页提取到 {len(links)} 个链接")
            else:
                print(f"第 {page_num} 页爬取失败")

    print(f"总共提取到 {total_links} 个链接")


async def main():
    """命令行运行时的主函数，打印结果到控制台并保存到文件"""
    import argparse

    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="获取海关总署法规链接")
    parser.add_argument(
        "--incremental", action="store_true", help="启用增量模式（只获取新的链接）"
    )
    parser.add_argument("--pages", type=int, default=5, help="爬取的页数，默认为5页")
    parser.add_argument(
        "--use-proxy", action="store_true", help="启用动态代理轮询（默认不启用）"
    )

    # 解析命令行参数
    args = parser.parse_args()

    # 调用get_links函数
    result = await get_links(
        is_incremental=args.incremental,
        max_pages=args.pages,
        use_dynamic_proxy=args.use_proxy,
    )

    # 打印结果
    mode = "增量模式" if result.get("is_incremental") else "全量模式"
    proxy_mode = "使用动态代理" if args.use_proxy else "不使用代理"
    print(
        f"\n{mode}（{args.pages}页）- {proxy_mode}：总共获取到 {result['count']} 个链接:"
    )
    for i, link in enumerate(result["links"], 1):
        print(f"{i}. {link}")


if __name__ == "__main__":
    asyncio.run(main())
