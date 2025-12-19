import os
import sys
import asyncio
import argparse
import aiohttp
import json
import random
import time
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from typing import List, Optional, Dict

# 添加项目根目录到系统路径，以便导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入配置和增量爬取辅助模块
from config.logger_config import LoggerConfig
from utils.incremental_crawler import (
    filter_links_for_crawl,
    prepare_links_result,
    get_latest_link_from_db,
)

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


def get_random_user_agent():
    """随机获取User-Agent"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    ]
    return random.choice(user_agents)


def get_random_headers():
    """获取随机请求头"""
    user_agent = get_random_user_agent()
    chrome_version = random.choice(["143", "142", "141"])

    headers = {
        "accept": random.choice(
            ["*/*", "application/json", "application/json, text/plain, */*"]
        ),
        "accept-language": random.choice(
            [
                "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
                "zh-CN,zh;q=0.9,en;q=0.8",
            ]
        ),
        "sec-ch-ua": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
        "sec-fetch-dest": random.choice(["empty", "cors"]),
        "sec-fetch-mode": "cors",
        "sec-fetch-site": random.choice(["same-site", "same-origin"]),
        "x-requested-with": "XMLHttpRequest",
        "user-agent": user_agent,
        "referer": "https://www.ebrun.com/businessnews/",
    }
    return headers


async def get_fecu_token():
    """通过捕获网络请求获取FECU令牌"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_random_user_agent())
        page = await context.new_page()

        logger.info("正在通过 Playwright 访问页面获取 FECU 令牌...")
        await page.goto("https://www.ebrun.com/newest/", wait_until="networkidle")
        await page.wait_for_timeout(1000)

        captured_token = None

        def handle_request(request):
            nonlocal captured_token
            url = request.url
            if "/more/" in url and "FECU=" in url:
                match = re.search(r"FECU=([a-zA-Z0-9%+/=]+)", url)
                if match:
                    captured_token = match.group(1)

        page.on("request", handle_request)

        try:
            # 尝试点击加载更多按钮以触发请求
            await page.click(
                "#app > main > div.ebrun-global-content > section.main-module > div.button-group > a"
            )
            await page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning(f"尝试点击加载更多按钮时出错（可能令牌已获取）: {e}")

        await browser.close()
        if captured_token:
            logger.info(f"成功获取 FECU 令牌: {captured_token[:20]}...")
        return captured_token


async def random_delay():
    """随机延时，避免请求过于规律"""
    delay = random.uniform(1.0, 2.5)
    await asyncio.sleep(delay)


async def fetch_page(session, page_num, proxy=None, max_retries=3, fecu_token=None):
    """模拟亿邦动力网站的分页请求"""
    if not fecu_token:
        raise ValueError("必须提供 FECU 令牌")

    # 专栏文章的基础URL
    base_url = f"https://www.ebrun.com/zl/more/{{page}}?date=&FECU={fecu_token}"
    url = base_url.format(page=page_num)
    headers = get_random_headers()

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                await random_delay()

            logger.info(f"请求第 {page_num} 页数据 (第 {attempt + 1} 次尝试)...")
            if proxy:
                logger.debug(f"使用代理: {proxy}")

            async with session.get(
                url, headers=headers, proxy=proxy, timeout=15
            ) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        return data
                    except Exception:
                        logger.error(f"第 {page_num} 页响应不是有效的 JSON 格式")
                        return None
                elif response.status in [429, 503]:
                    retry_after = random.uniform(5, 10) * (attempt + 1)
                    logger.warning(
                        f"触发反爬 ({response.status})，等待 {retry_after:.1f} 秒..."
                    )
                    await asyncio.sleep(retry_after)
                else:
                    logger.error(f"第 {page_num} 页请求失败，状态码: {response.status}")
                    if attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"第 {page_num} 页请求发生异常: {str(e)}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2)
    return None


def extract_news_img_links(html_content):
    """从HTML内容中提取链接地址"""
    links = []
    if not html_content:
        return links

    soup = BeautifulSoup(html_content, "html.parser")
    news_img_divs = soup.find_all("div", class_="news-img")

    for div in news_img_divs:
        a_tag = div.find("a")
        if a_tag and a_tag.has_attr("href"):
            href = a_tag["href"]
            if href.startswith("/"):
                href = f"https://www.ebrun.com{href}"
            links.append(href)
    return links


async def fetch_all_links(
    use_proxy=False, proxy_list=None, max_pages=None, is_incremental=False
):
    """获取所有页面链接"""
    all_links = []
    page_count = 0
    latest_link = None

    if is_incremental:
        latest_link = await get_latest_link_from_db()
        if latest_link:
            logger.info(f"增量模式启动：数据库最新记录为 {latest_link}")
        else:
            logger.info("增量模式启动：未找到历史记录，将进行全量爬取")

    proxies = proxy_list if use_proxy and proxy_list else []
    connector = aiohttp.TCPConnector(verify_ssl=False) if proxies else None

    logger.info("正在获取初始化 FECU 令牌...")
    fecu_token = await get_fecu_token()
    if not fecu_token:
        raise Exception("无法获取 FECU 令牌，爬虫任务终止")

    async with aiohttp.ClientSession(connector=connector) as session:
        fecu_retry_count = 0
        max_fecu_retries = 3
        should_continue = True

        while should_continue and (max_pages is None or page_count < max_pages):
            page_num = page_count + 1
            current_proxy = random.choice(proxies) if proxies else None

            data = await fetch_page(
                session, page_num, current_proxy, fecu_token=fecu_token
            )

            if not data:
                fecu_retry_count += 1
                if fecu_retry_count >= max_fecu_retries:
                    logger.critical("连续多次获取数据失败，疑似令牌失效或被封禁")
                    break

                logger.info(f"尝试刷新 FECU 令牌 (第 {fecu_retry_count} 次)...")
                fecu_token = await get_fecu_token()
                continue

            if data and data.get("code") == 200200:
                fecu_retry_count = 0  # 重置错误计数
                data_obj = data.get("data", {})
                is_end = data_obj.get("is_end", 0)
                html_content = data_obj.get("html", "")

                if html_content:
                    page_links = extract_news_img_links(html_content)

                    # 合并并保持有序去重
                    previous_count = len(all_links)
                    for link in page_links:
                        if link not in all_links:
                            all_links.append(link)

                    # 排序（按ID降序）
                    all_links.sort(
                        key=lambda x: x.split("/")[-1].split(".")[0], reverse=True
                    )

                    logger.info(
                        f"第 {page_num} 页提取到 {len(page_links)} 个链接，当前新链接总数: {len(all_links)}"
                    )

                    # 增量检查
                    if is_incremental and latest_link and latest_link in page_links:
                        logger.info(f"匹配到数据库最新链接，增量爬取结束")
                        index = all_links.index(latest_link)
                        all_links = all_links[:index]
                        should_continue = False

                    # 如果这页链接全都在 list 里了且不是第一页，说明后面也没新东西了
                    if len(all_links) == previous_count and page_num > 1:
                        logger.info(f"检测到重复数据，停止爬取")
                        should_continue = False

                if is_end == 1:
                    logger.info(f"已触达网站最后一页，爬取完成")
                    should_continue = False
            else:
                logger.error(
                    f"服务器返回错误代码: {data.get('code') if data else 'Unknown'}"
                )

            page_count += 1
            if should_continue:
                await random_delay()

    logger.info(f"爬取阶段结束，共获取有效新链接 {len(all_links)} 条")
    return all_links


def get_proxy_list():
    return []


async def get_links(
    use_proxy=False, proxy_list=None, max_pages=None, is_incremental=False
):
    """外部调用入口"""
    if use_proxy and not proxy_list:
        proxy_list = get_proxy_list()
        if not proxy_list:
            logger.warning("未配置有效代理列表，切换回直接连接模式")
            use_proxy = False

    all_links = await fetch_all_links(
        use_proxy=use_proxy,
        proxy_list=proxy_list,
        max_pages=max_pages,
        is_incremental=is_incremental,
    )

    # 最终确保唯一和排序
    unique_links = list(dict.fromkeys(all_links))
    unique_links.sort(key=lambda x: x.split("/")[-1].split(".")[0], reverse=True)

    return prepare_links_result(unique_links, is_incremental)


async def main():
    """命令行主函数"""
    LoggerConfig.setup_crawler_logger(
        log_file="ebrun_column_crawler", project_root=project_root
    )

    parser = argparse.ArgumentParser(description="亿邦动力专栏链接获取工具")
    parser.add_argument("--incremental", action="store_true", help="启用增量模式")
    parser.add_argument("--max-pages", type=int, help="限制最大爬取页数")
    args = parser.parse_args()

    logger.info("=== 亿邦动力网专栏文章爬虫启动 ===")
    mode_str = "增量模式" if args.incremental else "全量模式"
    logger.info(f"配置信息 -> 模式: {mode_str}, 最大页数: {args.max_pages or '无限制'}")

    result = await get_links(
        use_proxy=False, max_pages=args.max_pages, is_incremental=args.incremental
    )

    logger.info(f"任务完成：本次爬取获得 {result['count']} 条新链接")
    for i, link in enumerate(result["links"][:15], 1):
        logger.info(f"  [{i}] {link}")

    if result["count"] > 15:
        logger.info(f"  ... 及其余 {result['count'] - 15} 条记录")

    return result


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户中断了任务")
    except Exception as e:
        logger.exception(f"任务执行过程中发生未捕获异常: {e}")
