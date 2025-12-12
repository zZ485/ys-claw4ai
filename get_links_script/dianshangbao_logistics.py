import asyncio
import aiohttp
import json
import random
import time
from typing import List, Optional, Dict

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
    windows_version = random.choice(["10.0", "11.0"])
    
    headers = {
        "accept": random.choice(["*/*", "application/json", "application/json, text/plain, */*"]),
        "accept-language": random.choice([
            "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "zh-CN,zh;q=0.9,en;q=0.8"
        ]),
        "content-type": "application/json",
        "referrer": random.choice([
            "https://www.pai.com.cn/",
            "https://d.pai.com.cn/",
            "https://pai.com.cn/"
        ]),
        "sec-ch-ua": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
        "sec-fetch-dest": random.choice(["empty", "cors"]),
        "sec-fetch-mode": "cors",
        "sec-fetch-site": random.choice(["same-site", "same-origin"]),
        "user-agent": user_agent,
        "priority": random.choice(["u=1, i", "u=0"])
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
            user {
              name
              nickname
              image
              __typename
            }
            team {
              slug
              name
              avatar
              __typename
            }
            tags {
              name
              slug
              __typename
            }
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
      id
      title
      slug
      summary
      url
      cover_image
      publish_status
      view_count
      status
      status_desc
      created_at
      published_at
      publish_at_diff_humans
      deleted_at
      __typename
    }
    
    fragment replayPageInfoFragment on PageInfo {
      endCursor
      count
      currentPage
      hasNextPage
      hasPreviousPage
      lastPage
      startCursor
      total
      __typename
    }
    """
    
    payload = {
        "operationName": "GetPosts",
        "variables": {
            "first": 20,  # 固定每次请求数量
            "category": "2",
            "show_mode": "Zhuanlan",
            "after": after_cursor
        },
        "query": query
    }
    
    # 实现重试机制
    for attempt in range(max_retries):
        try:
            # 随机延时
            if attempt > 0:
                await random_delay()
                
            async with session.post(url, headers=headers, json=payload, proxy=proxy) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status in [429, 503]:  # 请求过于频繁或服务不可用
                    retry_after = random.uniform(3, 8) * (attempt + 1)  # 指数退避
                    print(f"遇到 {response.status} 错误，等待 {retry_after:.2f} 秒后重试 (第 {attempt + 1} 次)")
                    await asyncio.sleep(retry_after)
                else:
                    print(f"请求失败，状态码: {response.status}")
                    if attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"请求异常: {str(e)}，第 {attempt + 1} 次尝试")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)
    
    return None

async def fetch_all_posts_urls(max_pages=5, use_proxy=False, proxy_list=None):
    """
    获取多页专栏文章，返回完整URL列表
    增强反爬虫能力：支持代理、随机延时、请求头轮换
    """
    all_urls = []
    after_cursor = None
    page_count = 0
    
    # 准备代理列表
    proxies = []
    if use_proxy and proxy_list:
        proxies = proxy_list
    
    # 如果使用代理，创建带connector的session
    connector = aiohttp.TCPConnector(verify_ssl=False) if use_proxy and proxy_list else None
    
    async with aiohttp.ClientSession(connector=connector) as session:
        while page_count < max_pages:
            print(f"正在获取第 {page_count + 1} 页")
            
            # 随机选择代理（如果启用）
            current_proxy = random.choice(proxies) if proxies else None
            if current_proxy:
                print(f"使用代理: {current_proxy}")
            
            data = await fetch_posts_page(session, after_cursor, current_proxy)
            
            if not data:
                print("无法获取数据，可能遇到反爬虫限制")
                break
                
            posts = data.get("data", {}).get("posts", {})
            edges = posts.get("edges", [])
            page_info = posts.get("pageInfo", {})
            
            # 提取本页文章的完整URL
            for edge in edges:
                node = edge.get("node", {})
                url_path = node.get("url", "")
                if url_path:
                    # 拼接完整URL
                    full_url = f"https://www.pai.com.cn{url_path}"
                    all_urls.append(full_url)
            
            # 检查是否还有下一页
            if not page_info.get("hasNextPage"):
                print("已到达最后一页")
                break
                
            # 更新游标，用于请求下一页
            after_cursor = page_info.get("endCursor")
            page_count += 1
            
            # 随机延时，避免请求过于规律
            await random_delay()
    
    print(f"共获取 {len(all_urls)} 条专栏文章URL")
    return all_urls

# 示例代理列表（实际使用时需要替换为有效代理）
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
    获取商电报专栏文章URL列表，可供外部调用
    
    参数:
        use_proxy: 是否使用代理，默认为False
        proxy_list: 代理IP列表，格式为["http://ip:port", "http://ip2:port2", ...]
        max_pages: 最大爬取页数，默认为5
        
    返回:
        dict: 包含count和links的字典
            {
                "count": int,     # 链接总数
                "links": list     # URL列表
            }
    """
    # 如果使用代理但没有提供代理列表，则使用默认代理列表
    if use_proxy and not proxy_list:
        proxy_list = get_proxy_list()
        if not proxy_list:
            print("警告：未配置有效代理，将不使用代理")
            use_proxy = False
    
    # 获取所有URL
    all_urls = await fetch_all_posts_urls(max_pages=max_pages, use_proxy=use_proxy, proxy_list=proxy_list)
    
    # 去重（虽然理论上不会有重复，但确保数据的唯一性）
    unique_urls = list(set(all_urls))
    
    return {
        "count": len(unique_urls),
        "links": unique_urls
    }

async def main():
    """命令行运行时的主函数，打印结果到控制台"""
    # 配置选项
    use_proxy = False  # 是否使用代理
    max_pages = 2  # 最大页数
    
    print("=== 商电报专栏文章爬虫 ===")
    print(f"最大页面数: {max_pages}")
    print(f"使用代理: {'是' if use_proxy else '否'}")
    print("开始爬取...")
    
    result = await get_links(use_proxy=use_proxy, max_pages=max_pages)
    
    print(f"\n总共获取到 {result['count']} 个链接:")
    for i, link in enumerate(result['links'], 1):
        print(f"{i}. {link}")
    
    # 可选：将结果保存到文件
    save_to_file = input("\n是否将结果保存到文件? (y/n): ").lower() == 'y'
    if save_to_file:
        filename = f"dianshangbao_retail_links_{int(time.time())}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("\n".join(result['links']))
        print(f"结果已保存到 {filename}")

if __name__ == "__main__":
    asyncio.run(main())
