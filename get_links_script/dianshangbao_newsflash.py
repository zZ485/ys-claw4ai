import os
import sys
import asyncio
import argparse
import aiohttp
import json
import random
import time
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
        "content-type": "application/json",
        "referrer": random.choice(
            ["https://www.pai.com.cn/", "https://d.pai.com.cn/", "https://pai.com.cn/"]
        ),
        "sec-ch-ua": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
        "sec-fetch-dest": random.choice(["empty", "cors"]),
        "sec-fetch-mode": "cors",
        "sec-fetch-site": random.choice(["same-site", "same-origin"]),
        "user-agent": user_agent,
        "priority": random.choice(["u=1, i", "u=0"]),
    }
    return headers


async def random_delay():
    """随机延时，避免请求过于规律"""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)


async def fetch_news_page(session, after_cursor=None, proxy=None, max_retries=3):
    """获取单页新闻数据，增强反爬虫能力"""
    url = "https://d.pai.com.cn/graphql"
    headers = get_random_headers()

    query = """  
    query GetNews($first: Int = 20, $after: String) {  
      posts(first: $first, show_mode: News, after: $after) {  
        edges {  
          cursor  
          node {  
            ...postListItemFragment  
            __typename  
          }  
          __typename  
        }  
        pageInfo {  
          ...replayPageInfoFragment  
          __typename  
        }  
        __typename  
      }  
    }  
      
    fragment postListItemFragment on Post {  
      id title slug summary url cover_image publish_status view_count status status_desc created_at published_at publish_at_diff_humans deleted_at __typename  
    }  
      
    fragment replayPageInfoFragment on PageInfo {  
      endCursor count currentPage hasNextPage hasPreviousPage lastPage startCursor total __typename  
    }  
    """

    payload = {
        "operationName": "GetNews",
        "variables": {"first": 20, "after": after_cursor},
        "query": query,
    }

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                await random_delay()

            async with session.post(
                url, headers=headers, json=payload, proxy=proxy, timeout=15
            ) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status in [429, 503]:
                    retry_after = random.uniform(3, 8) * (attempt + 1)
                    logger.warning(
                        f"遇到 {response.status} 错误，等待 {retry_after:.1f} 秒后重试 (第 {attempt + 1} 次)"
                    )
                    await asyncio.sleep(retry_after)
                else:
                    logger.error(f"新闻列表请求失败，状态码: {response.status}")
                    if attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"请求异常: {str(e)}，第 {attempt + 1} 次尝试")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)

    return None


async def fetch_all_news(use_proxy=False, proxy_list=None, is_incremental=False):
    """
    获取所有新闻，返回完整URL列表
    """
    all_urls = []
    after_cursor = None
    page_count = 0

    # 如果是增量模式，先获取最新链接
    latest_link = None
    if is_incremental:
        latest_link = await get_latest_link_from_db()
        if latest_link:
            logger.info(f"增量模式启动：数据库中最新记录为 {latest_link}")
        else:
            logger.info("增量模式启动：未找到历史记录，将进行全量爬取")

    proxies = proxy_list if (use_proxy and proxy_list) else []
    connector = aiohttp.TCPConnector(verify_ssl=False) if proxies else None

    async with aiohttp.ClientSession(connector=connector) as session:
        should_continue = True
        while should_continue:
            logger.info(f"正在获取第 {page_count + 1} 页新闻数据...")

            current_proxy = random.choice(proxies) if proxies else None
            if current_proxy:
                logger.debug(f"使用代理: {current_proxy}")

            data = await fetch_news_page(session, after_cursor, current_proxy)

            if not data:
                logger.warning(f"第 {page_count + 1} 页未能获取到有效数据，停止采集")
                break

            posts_data = data.get("data", {}).get("posts", {})
            edges = posts_data.get("edges", [])
            page_info = posts_data.get("pageInfo", {})

            if not edges:
                logger.info("当前页无更多文章，采集完成")
                break

            # 提取本页新闻 URL
            page_urls = []
            for edge in edges:
                node = edge.get("node", {})
                url_path = node.get("url", "")
                if url_path:
                    full_url = f"https://www.pai.com.cn{url_path}"
                    page_urls.append(full_url)

            # 增量模式判断
            if is_incremental and latest_link:
                if latest_link in page_urls:
                    logger.info(f"匹配到数据库记录的最新链接，触发增量停止条件")
                    index = page_urls.index(latest_link)
                    all_urls.extend(page_urls[:index])
                    should_continue = False
                else:
                    all_urls.extend(page_urls)
            else:
                all_urls.extend(page_urls)

            logger.info(
                f"第 {page_count + 1} 页处理完成，提取到 {len(page_urls)} 条链接"
            )

            # 检查是否有下一页
            if should_continue and page_info.get("hasNextPage"):
                after_cursor = page_info.get("endCursor")
                page_count += 1
                await random_delay()
            else:
                if not page_info.get("hasNextPage"):
                    logger.info("已触达最后一页")
                should_continue = False

    logger.info(f"新闻采集结束，共获取到 {len(all_urls)} 条新文章链接")
    return all_urls


def get_proxy_list():
    """示例代理列表"""
    return []


async def get_links(use_proxy=False, proxy_list=None, is_incremental=False):
    """外部调用接口"""
    if use_proxy and not proxy_list:
        proxy_list = get_proxy_list()
        if not proxy_list:
            logger.warning("未配置有效代理，将不使用代理")
            use_proxy = False

    # 获取所有URL
    all_urls = await fetch_all_news(
        use_proxy=use_proxy,
        proxy_list=proxy_list,
        is_incremental=is_incremental,
    )

    # 过滤链接（包含去重和数据库比对逻辑）
    filtered_links = await filter_links_for_crawl(all_urls, is_incremental)

    # 返回格式化结果
    return prepare_links_result(filtered_links, is_incremental)


async def main():
    """命令行运行入口"""
    # 初始化日志系统
    LoggerConfig.setup_crawler_logger(
        log_file="pai_news_crawler", project_root=project_root
    )

    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="商电报新闻获取工具")
    parser.add_argument(
        "--incremental", action="store_true", help="启用增量模式（只获取新文章）"
    )

    # 解析命令行参数
    args = parser.parse_args()

    logger.info("=== 商电报新闻快讯爬虫启动 ===")
    mode = "增量模式" if args.incremental else "全量模式"
    logger.info(f"配置模式: {mode}")

    result = await get_links(use_proxy=False, is_incremental=args.incremental)

    # 打印最终结果
    logger.info(f"任务结束 [{mode}]：总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result["links"][:10], 1):
        logger.info(f"  {i}. {link}")

    if len(result["links"]) > 10:
        logger.info(f"  ... 及其余 {len(result['links']) - 10} 条链接")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("用户主动停止了采集任务")
    except Exception as e:
        logger.exception(f"采集任务执行过程中发生严重错误: {e}")
