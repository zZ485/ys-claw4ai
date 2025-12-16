import asyncio
import pyperclip
import requests
import os
import sys
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter, BM25ContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from config.target_elements_config import TargetElementsConfig


async def main():
    # 显示可用配置
    print("可用的目标元素配置:")
    configs = TargetElementsConfig.get_all_configs()
    for i, (name, elements) in enumerate(configs.items(), 1):
        print(f"{i}. {name}: {elements}")

    # 获取用户选择的配置
    config_choice = input("请选择配置 (直接回车使用默认配置): ").strip()
    if config_choice:
        try:
            # 如果是数字，转换为对应配置名
            config_index = int(config_choice)
            config_names = list(configs.keys())
            if 1 <= config_index <= len(config_names):
                selected_config = config_names[config_index - 1]
            else:
                print("无效的选择，将使用默认配置")
                selected_config = "default"
        except ValueError:
            # 如果是文本，直接作为配置名
            if TargetElementsConfig.config_exists(config_choice):
                selected_config = config_choice
            else:
                print("无效的配置名，将使用默认配置")
                selected_config = "default"
    else:
        selected_config = "default"

    # 获取配置的目标元素
    target_elements = TargetElementsConfig.get_config(selected_config)
    print(f"使用配置: {selected_config}")
    print(f"目标元素: {target_elements}")

    url = input("请输入要爬取的URL: ").strip()
    if not url:
        print("未输入URL，程序退出")
        return

    browser_config = BrowserConfig(
        # headless=True,
        # verbose=False,
        text_mode=True,
        user_agent_mode="random",
    )

    # 基础配置参数
    run_config_kwargs = {
        "cache_mode": CacheMode.BYPASS,
        "markdown_generator": DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(
                threshold=0.48, threshold_type="fixed", min_word_threshold=0
            )
        ),
        "excluded_tags": ["form", "header", "footer", "nav", "img"],
        "exclude_social_media_links": True,
        # "remove_overlay_elements": True,  # 移除遮罩层元素（如弹窗广告、cookie提示等）
        # "simulate_user": True,         # 模拟真实用户行为，防止被反爬虫机制检测
        # "override_navigator": True,     # 覆盖浏览器导航信息，增强反检测能力
        # "exclude_external_images": True, # 排除外部图片
    }

    # 如果有目标元素配置，添加到配置参数中
    if target_elements:
        run_config_kwargs["target_elements"] = target_elements

    run_config = CrawlerRunConfig(**run_config_kwargs)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=url,
            config=run_config,
        )

        # 复制到剪切板
        if result.markdown.fit_markdown:
            pyperclip.copy(result.markdown.fit_markdown)
            print("✓ 结果已复制到剪切板")
        else:
            print("⚠ 没有获取到内容")


if __name__ == "__main__":
    asyncio.run(main())
