import asyncio
import aiohttp
import json
import random
import time
from bs4 import BeautifulSoup
from typing import List, Optional, Dict
import re

def get_random_user_agent():
    """随机获取User-Agent"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    ]
    return random.choice(user_agents)

def get_random_headers():
    """获取随机请求头"""
    user_agent = get_random_user_agent()
    chrome_version = random.choice(["143", "142", "141"])
    
    headers = {
        "accept": random.choice(["*/*", "application/json", "application/json, text/plain, */*"]),
        "accept-language": random.choice([
            "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "zh-CN,zh;q=0.9,en;q=0.8"
        ]),
        "sec-ch-ua": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
        "sec-fetch-dest": random.choice(["empty", "cors"]),
        "sec-fetch-mode": "cors",
        "sec-fetch-site": random.choice(["same-site", "same-origin"]),
        "x-requested-with": "XMLHttpRequest",
        "user-agent": user_agent,
        "referer": "https://www.ebrun.com/businessnews/"
    }
    return headers

async def random_delay():
    """随机延时，避免请求过于规律"""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)

async def get_fecu_token(session, proxy=None):
    """
    获取最新的FECU token
    通过访问主页面，从JavaScript中提取FECU参数
    """
    main_url = "https://www.ebrun.com/businessnews/"
    
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.ebrun.com/"
    }
    
    try:
        print("正在获取FECU token...")
        async with session.get(main_url, headers=headers, proxy=proxy, timeout=10) as response:
            if response.status == 200:
                html_content = await response.text()
                
                # 方法1：从JavaScript中提取FECU参数
                # 查找包含FECU的JavaScript代码
                fecu_patterns = [
                    r'FECU=([a-zA-Z0-9+/=]+)',  # 直接匹配FECU=xxxx
                    r'"FECU":"([a-zA-Z0-9+/=]+)"',  # 匹配"FECU":"xxxx"
                    r"FECU:\s*'([a-zA-Z0-9+/=]+)'",  # 匹配FECU: 'xxxx'
                ]
                
                for pattern in fecu_patterns:
                    matches = re.findall(pattern, html_content)
                    if matches:
                        fecu_token = matches[0]
                        print(f"成功获取FECU token: {fecu_token[:50]}...")
                        return fecu_token
                
                # 方法2：从URL参数中提取
                url_pattern = r'/more/\d+\?[^"\']*FECU=([a-zA-Z0-9+/=]+)'
                matches = re.findall(url_pattern, html_content)
                if matches:
                    fecu_token = matches[0]
                    print(f"从URL中获取FECU token: {fecu_token[:50]}...")
                    return fecu_token
                
                print("未找到FECU token，使用默认值")
                return None
            else:
                print(f"获取主页失败: {response.status}")
                return None
    except Exception as e:
        print(f"获取FECU token异常: {str(e)}")
        return None

async def fetch_page(session, page_num, fecu_token=None, proxy=None, max_retries=3):
    """
    模拟亿邦动力网站的分页请求，动态获取FECU参数
    """
    # 如果未提供FECU token，尝试获取
    if not fecu_token:
        fecu_token = await get_fecu_token(session, proxy)
    
    # 如果仍然没有FECU token，使用一个默认值（可能会失败）
    if not fecu_token:
        fecu_token = "cAfvyknUXRcsx1hY1nV1qj0k%2BR2DyRDc2ioDLUIeHKv70F7cs78g91rOG3RWOlxT7vv3BtPgdytiuqamtPQIz8avC84TuAbKIcIQwCu0ciOlymDbDYe8%2BPqqAzJEghWkSb6vECtWxpNVRzkOtuD8vh%2B9lf%2BTG%2Bw2%2BjWxinKquWke8qCTx%2B9%2Bx9Cu78MKYZdhe7"
        print("使用默认FECU token")
    
    # 构建URL，包含动态的FECU参数
    base_url = f"https://www.ebrun.com/businessnews/more/{{page}}?date=&FECU={fecu_token}"
    
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
            async with session.get(url, headers=headers, proxy=proxy, timeout=10) as response:
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
                    print(f"遇到 {response.status} 错误，等待 {retry_after:.2f} 秒后重试 (第 {attempt + 1} 次)")
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
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 查找所有class为"news-img"的div
    news_img_divs = soup.find_all('div', class_='news-img')
    
    for div in news_img_divs:
        # 在每个div中查找a标签
        a_tag = div.find('a')
        if a_tag and a_tag.has_attr('href'):
            # 获取href属性值
            href = a_tag['href']
            
            # 处理相对URL
            if href.startswith('/'):
                href = f"https://www.ebrun.com{href}"
            
            links.append(href)
    
    return links

async def fetch_all_links(max_pages=5, use_proxy=False, proxy_list=None):
    """
    获取多页链接，返回完整URL列表
    增强反爬虫能力：支持代理、随机延时、请求头轮换、动态FECU
    """
    all_links = []
    page_count = 0
    
    # 准备代理列表
    proxies = []
    if use_proxy and proxy_list:
        proxies = proxy_list
    
    # 如果使用代理，创建带connector的session
    connector = aiohttp.TCPConnector(verify_ssl=False) if use_proxy and proxy_list else None
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # 首先获取一个有效的FECU token
        fecu_token = await get_fecu_token(session, random.choice(proxies) if proxies else None)
        
        while page_count < max_pages:
            page_num = page_count + 1
            print(f"正在获取第 {page_num} 页")
            
            # 随机选择代理（如果启用）
            current_proxy = random.choice(proxies) if proxies else None
            
            data = await fetch_page(session, page_num, fecu_token, current_proxy)
            
            if not data:
                print("无法获取数据，可能遇到反爬虫限制")
                # 尝试重新获取FECU token
                fecu_token = await get_fecu_token(session, current_proxy)
                continue
                
            if data.get('code') == 200200:
                # 从JSON数据中获取HTML内容
                html_content = data.get('data', {}).get('html', '')
                
                if html_content:
                    # 提取链接
                    page_links = extract_news_img_links(html_content)
                    all_links.extend(page_links)
                    
                    print(f"本页提取到 {len(page_links)} 个链接")
            
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

async def get_links(use_proxy=False, proxy_list=None, max_pages=2):
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
    all_links = await fetch_all_links(max_pages=max_pages, use_proxy=use_proxy, proxy_list=proxy_list)
    
    # 去重（虽然理论上不会有重复，但确保数据的唯一性）
    unique_links = list(set(all_links))
    
    # 返回符合任务管理器期望的格式
    return {
        "links": unique_links,
        "count": len(unique_links)
    }

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
    
    print(f"\n总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result['links'], 1):
        print(f"{i}. {link}")
    
    return result

if __name__ == "__main__":
    asyncio.run(main())
