import os
import sys
import asyncio
import re
import random
import aiohttp
import argparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup
from typing import List, Optional
from playwright.async_api import async_playwright

# 添加项目根目录到系统路径
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
        "sec-fetch-site": "same-origin",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": user_agent,
        "referer": "https://www.ebrun.com/topic/",
    }
    return headers


async def get_fecu_token():
    """通过捕获网络请求获取FECU令牌"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_random_user_agent())
        page = await context.new_page()

        # logger.info("正在通过 Playwright 访问页面获取 FECU 令牌...")
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


async def fetch_topic_page(
    session,
    page_num: int,
    fecu_token: str,
    proxy: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[dict]:
    """获取专题页面数据"""
    url = f"https://www.ebrun.com/topic/more/{page_num}?date=&FECU={fecu_token}"
    headers = get_random_headers()

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                await random_delay()

            logger.debug(f"请求第 {page_num} 页专题数据 (第 {attempt + 1} 次尝试)...")

            async with session.get(
                url, headers=headers, proxy=proxy, timeout=15
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
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


def extract_topic_links(html_content: str) -> List[str]:
    """从HTML内容中提取专题链接，格式如 https://www.ebrun.com/tc/2416.shtml"""
    links = []
    if not html_content:
        return links

    soup = BeautifulSoup(html_content, "html.parser")

    # 查找所有带有 data-dmp-url 属性的 li 标签
    for li_tag in soup.find_all("li", attrs={"data-dmp-url": True}):
        dmp_url = li_tag.get("data-dmp-url")
        if dmp_url and re.match(r"^https://www\.ebrun\.com/tc/\d+\.shtml$", dmp_url):
            links.append(dmp_url)

    return list(dict.fromkeys(links))  # 去重


def extract_article_links(markdown_content: str) -> List[str]:
    """从 markdown 内容中提取文章链接，格式如 https://www.ebrun.com/20250530/581780.shtml"""
    links = []
    if not markdown_content:
        return links

    # 匹配 http://www.ebrun.com/数字/数字.shtml 或 https://www.ebrun.com/数字/数字.shtml 格式
    pattern = r"https?://www\.ebrun\.com/\d+/\d+\.shtml"
    matches = re.findall(pattern, markdown_content)

    for match in matches:
        if match not in links:
            links.append(match)

    return links


async def crawl_topic_page(topic_url: str) -> Optional[str]:
    """使用 crawl4ai 爬取专题页面"""
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
    )

    browser_config = BrowserConfig(user_agent_mode="random")

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=topic_url, config=run_config)

        if not result:
            logger.warning(f"❌ 未能获取到 {topic_url} 的结果")
            return None

        return result.markdown


async def fetch_all_topic_links(
    fecu_token: str,
    use_proxy: bool = False,
    proxy_list: Optional[List[str]] = None,
    max_pages: Optional[int] = None,
    is_incremental: bool = False,
) -> List[str]:
    """获取所有专题链接"""
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

    fecu_retry_count = 0
    max_fecu_retries = 3
    should_continue = True

    async with aiohttp.ClientSession(connector=connector) as session:
        while should_continue and (max_pages is None or page_count < max_pages):
            page_num = page_count + 1
            current_proxy = random.choice(proxies) if proxies else None

            data = await fetch_topic_page(session, page_num, fecu_token, current_proxy)

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
                    page_links = extract_topic_links(html_content)

                    # 合并并保持有序去重
                    previous_count = len(all_links)
                    for link in page_links:
                        if link not in all_links:
                            all_links.append(link)

                    # 排序（按ID降序）
                    all_links.sort(
                        key=lambda x: int(x.split("/")[-1].split(".")[0]), reverse=True
                    )

                    logger.info(
                        f"第 {page_num} 页提取到 {len(page_links)} 个专题链接，当前新链接总数: {len(all_links)}"
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

    logger.info(f"专题爬取阶段结束，共获取有效新链接 {len(all_links)} 条")
    return all_links


async def crawl_all_articles_from_topics(
    topic_links: List[str],
) -> List[str]:
    """爬取所有专题页面以获取文章链接"""
    all_article_links = []

    for i, topic_url in enumerate(topic_links, 1):
        logger.info(f"[{i}/{len(topic_links)}] 正在爬取专题: {topic_url}")
        markdown_content = await crawl_topic_page(topic_url)

        if markdown_content:
            article_links = extract_article_links(markdown_content)
            logger.info(f"  提取到 {len(article_links)} 个文章链接")

            for link in article_links:
                if link not in all_article_links:
                    all_article_links.append(link)

        await random_delay()

    # 排序（按日期和ID降序）
    all_article_links.sort(
        key=lambda x: (int(x.split("/")[-2]), int(x.split("/")[-1].split(".")[0])),
        reverse=True,
    )

    logger.info(f"文章爬取阶段结束，共获取 {len(all_article_links)} 个文章链接")
    return all_article_links


async def get_links(
    use_proxy: bool = False,
    proxy_list: Optional[List[str]] = None,
    max_pages: Optional[int] = None,
    is_incremental: bool = False,
):
    """外部调用入口"""
    # 1. 获取 FECU 令牌
    logger.info("正在获取初始化 FECU 令牌...")
    fecu_token = await get_fecu_token()
    if not fecu_token:
        raise Exception("无法获取 FECU 令牌，爬虫任务终止")

    # 2. 获取专题链接
    topic_links = await fetch_all_topic_links(
        fecu_token=fecu_token,
        use_proxy=use_proxy,
        proxy_list=proxy_list,
        max_pages=max_pages,
        is_incremental=is_incremental,
    )

    if not topic_links:
        logger.warning("未获取到任何专题链接")
        return {"count": 0, "links": []}

    # 3. 爬取专题页面获取文章链接
    article_links = await crawl_all_articles_from_topics(topic_links)

    # 4. 最终确保唯一和排序
    unique_links = list(dict.fromkeys(article_links))
    unique_links.sort(
        key=lambda x: (int(x.split("/")[-2]), int(x.split("/")[-1].split(".")[0])),
        reverse=True,
    )

    return prepare_links_result(unique_links, is_incremental)


def get_proxy_list():
    return []


async def main():
    """命令行主函数"""
    LoggerConfig.setup_crawler_logger(
        log_file="ebrun_special_topic_crawler", project_root=project_root
    )

    parser = argparse.ArgumentParser(description="亿邦动力专题页面文章链接获取工具")
    parser.add_argument("--incremental", action="store_true", help="启用增量模式")
    parser.add_argument("--max-pages", type=int, help="限制最大爬取页数")
    args = parser.parse_args()

    logger.info("=== 亿邦动力专题页面爬虫启动 ===")
    mode_str = "增量模式" if args.incremental else "全量模式"
    logger.info(f"配置信息 -> 模式: {mode_str}, 最大页数: {args.max_pages or '无限制'}")

    result = await get_links(
        use_proxy=False, max_pages=args.max_pages, is_incremental=args.incremental
    )

    logger.info(f"任务完成：本次爬取获得 {result['count']} 条新文章链接")
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
