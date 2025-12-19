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


async def fetch_posts_page(session, after_cursor=None, proxy=None, max_retries=3):
    """获取单页专栏文章数据，增强反爬虫能力"""
    url = "https://d.pai.com.cn/graphql"
    headers = get_random_headers()

    query = """  
    query GetPosts($first: Int = 20, $after: String, $show_mode: PostShowMode, $type: PostType, $category: String, $tag: String) {  
      posts(  
        first: $first  
        after: $after  
        show_mode: $show_mode  
        type: $type  
        term_ids: $category  
        tag_ids: $tag  
      ) {  
        edges {  
          cursor  
          node {  
            ...postListItemFragment  
            user { name nickname image __typename }  
            team { slug name avatar __typename }  
            tags { name slug __typename }  
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
        "operationName": "GetPosts",
        "variables": {
            "first": 20,
            "category": "5",
            "show_mode": "Zhuanlan",
            "after": after_cursor,
        },
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
                    logger.error(f"GraphQL 请求失败，状态码: {response.status}")
                    if attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"请求发生异常: {str(e)} (第 {attempt + 1} 次重试)")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)

    return None


async def fetch_all_posts_urls(use_proxy=False, proxy_list=None, is_incremental=False):
    """
    获取所有专栏文章，返回完整URL列表
    """
    all_urls = []
    after_cursor = None
    page_count = 0

    # 如果是增量模式，先获取最新链接
    latest_link = None
    if is_incremental:
        latest_link = await get_latest_link_from_db()
        if latest_link:
            logger.info(f"增量模式启动：数据库中最新链接为 {latest_link}")
        else:
            logger.info("增量模式启动：未找到最新链接记录，将进行全量爬取")

    proxies = proxy_list if (use_proxy and proxy_list) else []
    connector = aiohttp.TCPConnector(verify_ssl=False) if proxies else None

    async with aiohttp.ClientSession(connector=connector) as session:
        should_continue = True
        while should_continue:
            logger.info(f"正在获取第 {page_count + 1} 页数据...")

            current_proxy = random.choice(proxies) if proxies else None
            if current_proxy:
                logger.debug(f"使用代理: {current_proxy}")

            data = await fetch_posts_page(session, after_cursor, current_proxy)

            if not data:
                logger.warning(f"第 {page_count + 1} 页未能获取到有效数据，停止采集")
                break

            posts_data = data.get("data", {}).get("posts", {})
            edges = posts_data.get("edges", [])
            page_info = posts_data.get("pageInfo", {})

            if not edges:
                logger.info("当前页面无文章数据，采集结束")
                break

            # 提取本页文章
            page_urls = []
            for edge in edges:
                node = edge.get("node", {})
                url_path = node.get("url", "")
                if url_path:
                    full_url = f"https://www.pai.com.cn{url_path}"
                    page_urls.append(full_url)

            # 增量判断
            if is_incremental and latest_link:
                if latest_link in page_urls:
                    logger.info(f"匹配到最新链接，增量采集触发停止条件")
                    # 截取该链接之前的所有新链接
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

            # 检查下一页
            if should_continue and page_info.get("hasNextPage"):
                after_cursor = page_info.get("endCursor")
                page_count += 1
                await random_delay()
            else:
                if not page_info.get("hasNextPage"):
                    logger.info("已触达最后一页数据")
                should_continue = False

    logger.info(f"采集阶段结束，共获取到 {len(all_urls)} 条潜在新文章 URL")
    return all_urls


def get_proxy_list():
    """示例代理列表"""
    return []


async def get_links(use_proxy=False, proxy_list=None, is_incremental=False):
    """
    获取商电报专栏文章URL列表对外接口
    """
    if use_proxy and not proxy_list:
        proxy_list = get_proxy_list()
        if not proxy_list:
            logger.warning("未配置有效代理，切换回直连模式")
            use_proxy = False

    # 获取所有URL
    all_urls = await fetch_all_posts_urls(
        use_proxy=use_proxy,
        proxy_list=proxy_list,
        is_incremental=is_incremental,
    )

    # 有序去重
    unique_links = list(dict.fromkeys(all_urls))

    # 返回符合格式的结果
    return prepare_links_result(unique_links, is_incremental)


async def main():
    """命令行入口函数"""
    # 初始化日志配置
    LoggerConfig.setup_crawler_logger(
        log_file="pai_column_crawler", project_root=project_root
    )

    parser = argparse.ArgumentParser(description="商电报专栏文章获取工具")
    parser.add_argument(
        "--incremental", action="store_true", help="启用增量模式（只获取新文章）"
    )

    args = parser.parse_args()

    logger.info("=== 商电报b2b文章爬虫启动 ===")
    mode = "增量模式" if args.incremental else "全量模式"
    logger.info(f"爬取模式: {mode}")

    result = await get_links(use_proxy=False, is_incremental=args.incremental)

    logger.info(f"任务结束 [{mode}]：总共获取到 {result['count']} 个链接")

    # 打印前 10 条结果到日志
    for i, link in enumerate(result["links"][:10], 1):
        logger.info(f"  {i}. {link}")

    if len(result["links"]) > 10:
        logger.info(f"  ... 及其余 {len(result['links']) - 10} 条链接")

    return result


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("用户手动中断了采集任务")
    except Exception as e:
        logger.exception(f"采集任务执行过程中发生严重错误: {e}")
