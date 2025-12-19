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

        logger.info("正在访问页面获取 FECU 令牌...")
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
            # 点击“加载更多”按钮触发 FECU 接口
            await page.click(
                "#app > main > div.ebrun-global-content > section.main-module > div.button-group > a"
            )
            await page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(
                f"触发 FECU 令牌点击操作时出错（可能令牌已通过其他方式捕获）: {e}"
            )

        await browser.close()
        return captured_token


async def random_delay():
    """随机延时，避免请求过于规律"""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)


async def fetch_page(session, page_num, proxy=None, max_retries=3, fecu_token=None):
    """模拟亿邦动力网站的分页请求"""
    if not fecu_token:
        raise ValueError("必须提供 FECU 令牌")

    # 商业趋势的基础 URL
    base_url = (
        f"https://www.ebrun.com/businessnews/more/{{page}}?date=&FECU={fecu_token}"
    )
    url = base_url.format(page=page_num)
    headers = get_random_headers()

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                await random_delay()

            logger.info(f"正在爬取第 {page_num} 页 (第 {attempt + 1} 次尝试)...")
            if proxy:
                logger.debug(f"使用代理: {proxy}")

            async with session.get(
                url, headers=headers, proxy=proxy, timeout=10
            ) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        return data
                    except Exception:
                        logger.error(f"第 {page_num} 页解析 JSON 失败")
                        return None
                elif response.status in [429, 503]:
                    retry_after = random.uniform(3, 8) * (attempt + 1)
                    logger.warning(
                        f"请求受限 ({response.status})，等待 {retry_after:.1f} 秒后重试..."
                    )
                    await asyncio.sleep(retry_after)
                else:
                    logger.error(f"第 {page_num} 页响应状态异常: {response.status}")
                    if attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"第 {page_num} 页请求发生异常: {str(e)}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)

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

    # 如果是增量模式，先获取最新链接
    latest_link = None
    if is_incremental:
        latest_link = await get_latest_link_from_db()
        if latest_link:
            logger.info(f"增量模式启动：数据库最新链接为 {latest_link}")
        else:
            logger.info("增量模式启动：未找到历史链接，将进行全量爬取")

    proxies = proxy_list if (use_proxy and proxy_list) else []
    connector = aiohttp.TCPConnector(verify_ssl=False) if proxies else None

    logger.info("正在初始化获取 FECU 令牌...")
    fecu_token = await get_fecu_token()
    if not fecu_token:
        raise Exception("无法获取 FECU 令牌，任务终止")

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
                    logger.critical("无法获取数据且达到 FECU 重试上限，任务强制终止")
                    break

                logger.info(
                    f"数据获取失败，尝试刷新 FECU 令牌 (第 {fecu_retry_count} 次)..."
                )
                fecu_token = await get_fecu_token()
                continue

            if data and data.get("code") == 200200:
                fecu_retry_count = 0  # 成功获取数据，重置重试计数
                data_obj = data.get("data", {})
                is_end = data_obj.get("is_end", 0)
                quick_news_date = data_obj.get("quick_news_date", "")
                html_content = data_obj.get("html", "")

                logger.info(
                    f"解析成功 -> 日期: {quick_news_date}, 最后一页: {'是' if is_end else '否'}"
                )

                if html_content:
                    page_links = extract_news_img_links(html_content)

                    previous_count = len(all_links)
                    # 使用有序去重
                    for link in page_links:
                        if link not in all_links:
                            all_links.append(link)

                    # 排序（按ID降序）
                    all_links.sort(
                        key=lambda x: x.split("/")[-1].split(".")[0], reverse=True
                    )

                    logger.info(f"第 {page_num} 页提取到 {len(page_links)} 个链接")

                    # 增量模式逻辑
                    if is_incremental and latest_link and latest_link in page_links:
                        logger.info(
                            f"第 {page_num} 页包含数据库记录的最新链接，触发增量停止条件"
                        )
                        index = all_links.index(latest_link)
                        all_links = all_links[:index]
                        should_continue = False

                    # 重复检查逻辑
                    elif len(all_links) == previous_count and page_num > 1:
                        logger.info("本页链接已全部存在于收录列表，停止爬取")
                        should_continue = False

                if not is_incremental and is_end == 1:
                    logger.info("到达全量爬取终点")
                    should_continue = False
            else:
                logger.error(
                    f"服务器返回异常代码: {data.get('code') if data else 'None'}"
                )

            page_count += 1
            if should_continue:
                await random_delay()

    logger.info(f"数据采集结束，累计获取有效新链接 {len(all_links)} 条")
    return all_links


async def get_links(
    use_proxy=False, proxy_list=None, max_pages=None, is_incremental=False
):
    """外部调用入口：获取商业趋势文章列表"""
    if use_proxy and not proxy_list:
        logger.warning("未配置有效代理列表，将使用直接连接")
        use_proxy = False

    all_links = await fetch_all_links(
        use_proxy=use_proxy,
        proxy_list=proxy_list,
        max_pages=max_pages,
        is_incremental=is_incremental,
    )

    # 最终去重与排序（确保逻辑万无一失）
    unique_links = list(dict.fromkeys(all_links))
    unique_links.sort(key=lambda x: x.split("/")[-1].split(".")[0], reverse=True)

    return prepare_links_result(unique_links, is_incremental)


async def main():
    """命令行运行入口"""
    # 初始化日志
    LoggerConfig.setup_crawler_logger(
        log_file="ebrun_business_news_crawler", project_root=project_root
    )

    parser = argparse.ArgumentParser(description="亿邦动力网商业趋势文章爬虫")
    parser.add_argument("--incremental", action="store_true", help="启用增量模式")
    parser.add_argument("--max-pages", type=int, help="限制爬取页数")
    args = parser.parse_args()

    logger.info("=== 亿邦动力网商业趋势文章爬虫启动 ===")
    mode_label = "增量模式" if args.incremental else "全量模式"
    logger.info(
        f"运行配置 -> 模式: {mode_label}, 最大页数: {args.max_pages or '无限制'}"
    )

    result = await get_links(
        use_proxy=False, max_pages=args.max_pages, is_incremental=args.incremental
    )

    # 打印概览结果
    logger.info(f"采集结果 [{mode_label}]：共获取到 {result['count']} 个新链接")
    for i, link in enumerate(result["links"][:10], 1):
        logger.info(f"{i}. {link}")

    if result["count"] > 10:
        logger.info(f"... 及其他 {result['count'] - 10} 条链接")

    return result


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户手动停止了任务")
    except Exception as e:
        logger.exception(f"程序运行发生未捕获异常: {e}")
