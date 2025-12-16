import os
import sys

# 添加项目根目录到系统路径，以便导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入增量爬取辅助模块
from utils.incremental_crawler import filter_links_for_crawl, prepare_links_result
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
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."
        )
        page = await context.new_page()

        print("正在访问页面获取FECU令牌...")
        await page.goto("https://www.ebrun.com/newest/", wait_until="networkidle")
        await page.wait_for_timeout(1000)  # 确保JS执行完毕

        # 捕获请求以获取FECU令牌
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
            await page.click(
                "#app > main > div.ebrun-global-content > section.main-module > div.button-group > a"
            )
            await page.wait_for_timeout(1000)
        except Exception as e:
            print(f"点击按钮时出错: {e}")
            pass

        await browser.close()
        return captured_token


async def load_fecu_token(filename="fecu_token.txt"):
    """从文件加载FECU令牌"""
    try:
        with open(filename, "r") as f:
            token = f.read().strip()
            return token
    except FileNotFoundError:
        return None


async def random_delay():
    """随机延时，避免请求过于规律"""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)


async def fetch_page(session, page_num, proxy=None, max_retries=3, fecu_token=None):
    """
    模拟亿邦动力网站的分页请求，增强反爬虫能力
    """
    # 必须提供FECU令牌
    if not fecu_token:
        raise ValueError("必须提供FECU令牌")

    # print(f"使用FECU令牌: {fecu_token[:50]}...")

    # 基础URL
    base_url = f"https://www.ebrun.com/zl/more/{{page}}?date=&FECU={fecu_token}"

    # 构建完整URL
    url = base_url.format(page=page_num)

    # 获取随机请求头
    headers = get_random_headers()

    # 实现重试机制
    for attempt in range(max_retries):
        try:
            # 随机延时
            if attempt > 0:
                await random_delay()

            print(f"\n=== 第 {page_num} 页 ===")
            if attempt > 0:
                print(f"第 {attempt + 1} 次尝试")
            if proxy:
                print(f"使用代理: {proxy}")

            # 发送GET请求
            async with session.get(
                url, headers=headers, proxy=proxy, timeout=10
            ) as response:
                if response.status == 200:
                    print(f"响应状态: 成功 (200)")

                    # 尝试解析JSON响应
                    try:
                        data = await response.json()
                        print(f"响应数据类型: JSON")
                        return data
                    except:
                        print(f"响应数据类型: 非JSON")
                        return None
                elif response.status in [429, 503]:  # 请求过于频繁或服务不可用
                    retry_after = random.uniform(3, 8) * (attempt + 1)  # 指数退避
                    print(
                        f"遇到 {response.status} 错误，等待 {retry_after:.2f} 秒后重试 (第 {attempt + 1} 次)"
                    )
                    await asyncio.sleep(retry_after)
                else:
                    print(f"响应状态: 失败 ({response.status})")
                    if attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(1)

        except aiohttp.ClientError as e:
            print(f"请求异常: {str(e)}，第 {attempt + 1} 次尝试")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)
        except Exception as e:
            print(f"其他异常: {str(e)}，第 {attempt + 1} 次尝试")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)

    return None


def extract_news_img_links(html_content):
    """
    从HTML内容中提取.news-img > a中的链接地址
    """
    links = []

    if not html_content:
        return links

    # 使用BeautifulSoup解析HTML
    soup = BeautifulSoup(html_content, "html.parser")

    # 查找所有class为"news-img"的div
    news_img_divs = soup.find_all("div", class_="news-img")

    for div in news_img_divs:
        # 在每个div中查找a标签
        a_tag = div.find("a")
        if a_tag and a_tag.has_attr("href"):
            # 获取href属性值
            href = a_tag["href"]

            # 处理相对URL
            if href.startswith("/"):
                href = f"https://www.ebrun.com{href}"

            links.append(href)

    return links


async def fetch_all_links(max_pages=5, use_proxy=False, proxy_list=None):
    """
    获取多页链接，返回完整URL列表
    增强反爬虫能力：支持代理、随机延时、请求头轮换、FECU令牌自动更新
    """
    all_links = []
    page_count = 0

    # 准备代理列表
    proxies = []
    if use_proxy and proxy_list:
        proxies = proxy_list

    # 如果使用代理，创建带connector的session
    connector = (
        aiohttp.TCPConnector(verify_ssl=False) if use_proxy and proxy_list else None
    )

    # 每次都获取新的FECU令牌
    print("获取FECU令牌...")
    fecu_token = await get_fecu_token()
    if not fecu_token:
        raise Exception("无法获取FECU令牌，爬虫终止")

    async with aiohttp.ClientSession(connector=connector) as session:
        # 记录尝试获取FECU令牌的次数
        fecu_retry_count = 0
        max_fecu_retries = 3

        while page_count < max_pages:
            page_num = page_count + 1
            print(f"正在获取第 {page_num} 页")

            # 随机选择代理（如果启用）
            current_proxy = random.choice(proxies) if proxies else None

            data = await fetch_page(
                session, page_num, current_proxy, fecu_token=fecu_token
            )

            if not data:
                print("无法获取数据，可能遇到反爬虫限制")

                # 检查是否已经尝试了足够次数
                fecu_retry_count += 1
                if fecu_retry_count >= max_fecu_retries:
                    raise Exception(
                        f"尝试{max_fecu_retries}次获取FECU令牌仍失败，爬虫终止"
                    )

                # 尝试刷新FECU令牌
                print(f"尝试刷新FECU令牌 (第{fecu_retry_count}次)...")
                fecu_token = await get_fecu_token()
                if fecu_token:
                    print("FECU令牌已刷新，重试当前页面...")
                    # 使用新令牌重试
                    data = await fetch_page(
                        session, page_num, current_proxy, fecu_token=fecu_token
                    )
                    if not data:
                        print("刷新FECU令牌后仍无法获取数据")
                        continue  # 继续尝试下一页
                else:
                    print("无法获取新的FECU令牌")
                    if fecu_retry_count >= max_fecu_retries:
                        raise Exception(
                            f"尝试{max_fecu_retries}次获取FECU令牌仍失败，爬虫终止"
                        )

            if data and data.get("code") == 200200:
                # 重置FECU重试计数器
                fecu_retry_count = 0

                # 从JSON数据中获取HTML内容
                html_content = data.get("data", {}).get("html", "")

                if html_content:
                    # 提取链接
                    page_links = extract_news_img_links(html_content)
                    all_links.extend(page_links)

                    print(f"本页提取到 {len(page_links)} 个链接")
            elif data:
                print(f"获取数据失败，响应代码: {data.get('code')}")

            page_count += 1

            # 随机延时，避免请求过于规律
            if page_count < max_pages:
                await random_delay()

    print(f"共获取 {len(all_links)} 条链接")
    return all_links


def get_proxy_list():
    """
    示例代理列表，实际使用时需要替换为有效的代理
    格式: ["http://ip:port", "http://ip2:port2", ...]
    """
    return [
        # 示例代理，需要替换为真实有效的代理
        # "http://127.0.0.1:7890",
        # "http://127.0.0.1:1080",
    ]


async def get_links(
    use_proxy=False, proxy_list=None, max_pages=2, is_incremental=False
):
    """
    获取亿邦动力网商业趋势文章URL列表，可供外部调用

    参数:
        use_proxy: 是否使用代理，默认为False
        proxy_list: 代理IP列表，格式为["http://ip:port", "http://ip2:port2", ...]
        max_pages: 最大爬取页数，默认为2

    返回:
        dict: 包含links键的字典，符合任务管理器期望的格式
            {
                "links": list,    # URL列表
                "code": int,      # 状态码
                "msg": str,       # 状态信息
                "count": int      # 链接总数
            }
    """
    # 如果使用代理但没有提供代理列表，则使用默认代理列表
    if use_proxy and not proxy_list:
        proxy_list = get_proxy_list()
        if not proxy_list:
            print("警告：未配置有效代理，将不使用代理")
            use_proxy = False

    # 获取所有URL
    all_links = await fetch_all_links(
        max_pages=max_pages, use_proxy=use_proxy, proxy_list=proxy_list
    )

    # 去重（虽然理论上不会有重复，但确保数据的唯一性）
    unique_links = list(set(all_links))

    unique_links.sort(key=lambda x: x.split("/")[-1].split(".")[0], reverse=True)

    # 使用增量爬取辅助模块过滤链接
    filtered_links = await filter_links_for_crawl(unique_links, is_incremental)

    # 返回符合任务管理器期望的格式
    return prepare_links_result(filtered_links, is_incremental)


async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    # 配置选项
    use_proxy = False  # 是否使用代理
    max_pages = 2  # 最大页数

    print("=== 亿邦动力网商业趋势文章爬虫 ===")
    print(f"最大页面数: {max_pages}")
    print(f"使用代理: {'是' if use_proxy else '否'}")
    print("开始爬取...")

    result = await get_links(use_proxy=use_proxy, max_pages=max_pages)

    # 打印结果
    mode = "增量模式" if result.get("is_incremental") else "全量模式"
    print(f"{mode}：总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result["links"], 1):
        print(f"{i}. {link}")

    # # 可选：将结果保存到文件
    # save_to_file = input("\n是否将结果保存到文件? (y/n): ").lower() == 'y'
    # if save_to_file:
    #     filename = f"ebrun_business_trends_links_{int(time.time())}.txt"
    #     with open(filename, 'w', encoding='utf-8') as f:
    #         f.write("\n".join(result['links']))
    #     print(f"结果已保存到 {filename}")

    return result


if __name__ == "__main__":
    asyncio.run(main())
