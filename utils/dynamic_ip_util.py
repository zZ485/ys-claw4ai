"""动态代理IP获取和验证工具"""

import asyncio
import aiohttp
import logging
import sys
from pathlib import Path
from typing import List, Dict

# 添加项目根目录到 sys.path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.logger_config import LoggerConfig
from config.crawler_params_config import crawler_params_config

logger = LoggerConfig.get_logger(__name__)


async def check_proxy_valid(
    session: aiohttp.ClientSession, ip: str, port: int, timeout: int = 10
) -> Dict:
    """
    检测单个代理IP的有效性

    Args:
        session: aiohttp会话
        ip: 代理IP地址
        port: 代理端口
        timeout: 超时时间(秒)，默认10秒

    Returns:
        包含IP、端口和有效性的字典
    """
    proxy_url = f"http://{ip}:{port}"
    result = {"ip": ip, "port": port, "valid": False, "error": None}

    try:
        # 使用百度首页测试代理是否可用
        async with session.get(
            "http://www.baidu.com",
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            if response.status == 200:
                # 读取响应内容，确保能正常获取页面
                content = await response.text()
                # 检查是否包含百度的关键词，确保代理真正可用
                if "百度" in content or "Baidu" in content:
                    result["valid"] = True
                    logger.info(f"代理IP {ip}:{port} 验证成功")
                else:
                    result["error"] = "响应内容异常"
                    logger.warning(f"代理IP {ip}:{port} 验证失败: {result['error']}")
            else:
                result["error"] = f"HTTP状态码: {response.status}"
                logger.warning(f"代理IP {ip}:{port} 验证失败: {result['error']}")
    except asyncio.TimeoutError:
        result["error"] = "连接超时"
        logger.warning(f"代理IP {ip}:{port} 验证失败: 连接超时")
    except aiohttp.ClientError as e:
        result["error"] = str(e)
        logger.warning(f"代理IP {ip}:{port} 验证失败: {str(e)}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"代理IP {ip}:{port} 验证出错: {str(e)}")

    return result


async def check_proxies_batch(
    proxies: List[Dict], max_concurrent: int = 10, timeout: int = 5
) -> List[Dict]:
    """
    批量检测代理IP的有效性

    Args:
        proxies: 代理IP列表,每个元素包含ip和port
        max_concurrent: 最大并发数
        timeout: 超时时间(秒)

    Returns:
        包含验证结果的列表
    """
    results = []

    # 创建限制并发量的信号量
    semaphore = asyncio.Semaphore(max_concurrent)

    async def check_with_semaphore(session, ip, port):
        async with semaphore:
            return await check_proxy_valid(session, ip, port, timeout)

    async with aiohttp.ClientSession() as session:
        tasks = [
            check_with_semaphore(session, proxy["ip"], proxy["port"])
            for proxy in proxies
        ]
        results = await asyncio.gather(*tasks)

    return results


async def get_dynamic_proxy() -> List[Dict]:
    """
    获取动态代理IP并验证有效性

    Returns:
        可用的代理IP列表,每个元素包含ip和port
    """
    try:
        # 从配置获取API URL和验证超时时间
        proxy_settings = crawler_params_config.get_proxy_settings()
        proxy_api_url = proxy_settings.get("proxy_api_url", "")
        proxy_check_timeout = proxy_settings.get("proxy_check_timeout", 5)
        max_concurrent_validation = proxy_settings.get("max_concurrent_validation", 50)

        if not proxy_api_url:
            logger.error("代理API URL未配置")
            return []

        # 调用API获取代理IP
        async with aiohttp.ClientSession() as session:
            async with session.get(
                proxy_api_url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    logger.error(f"获取代理IP失败,HTTP状态码: {response.status}")
                    return []

                data = await response.json()

                # 检查API响应
                if data.get("code") != "10001":
                    logger.error(f"获取代理IP失败: {data.get('msg', '未知错误')}")
                    return []

                proxy_list = data.get("data", {}).get("proxy_list", [])
                if not proxy_list:
                    logger.warning("API返回的代理列表为空")
                    return []

                logger.info(f"成功获取 {len(proxy_list)} 个代理IP,开始验证...")

                # 批量验证代理IP（使用配置的超时时间和并发数）
                validation_results = await check_proxies_batch(
                    proxy_list,
                    max_concurrent=max_concurrent_validation,
                    timeout=proxy_check_timeout,
                )

                # 筛选出有效的代理IP
                valid_proxies = [
                    {"ip": r["ip"], "port": r["port"]}
                    for r in validation_results
                    if r["valid"]
                ]

                logger.info(
                    f"验证完成,可用代理IP数量: {len(valid_proxies)}/{len(proxy_list)}"
                )

                return valid_proxies

    except asyncio.TimeoutError:
        logger.error("获取代理IP超时")
        return []
    except aiohttp.ClientError as e:
        logger.error(f"获取代理IP时网络错误: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"获取代理IP时发生异常: {str(e)}")
        return []


def get_proxy_url(proxy: Dict) -> str:
    """
    将代理IP字典转换为代理URL字符串

    Args:
        proxy: 包含ip和port的字典

    Returns:
        代理URL字符串,格式为 http://ip:port
    """
    return f"http://{proxy['ip']}:{proxy['port']}"


def format_proxies_for_crawl4ai(valid_proxies: List[Dict]) -> List[str]:
    """
    将可用的代理IP列表格式化为crawl4ai可用的格式

    Args:
        valid_proxies: 可用的代理IP列表

    Returns:
        代理URL字符串列表
    """
    return [get_proxy_url(proxy) for proxy in valid_proxies]


# 便捷函数
async def get_available_proxies() -> List[str]:
    """
    获取可用的代理IP列表(crawl4ai格式)

    Returns:
        代理URL字符串列表,格式为 http://ip:port
    """
    valid_proxies = await get_dynamic_proxy()
    return format_proxies_for_crawl4ai(valid_proxies)


if __name__ == "__main__":
    # 测试代码
    async def main():
        print("开始获取动态代理IP...")
        proxies = await get_dynamic_proxy()
        print(f"\n可用代理IP列表:")
        for proxy in proxies:
            print(f"  {proxy['ip']}:{proxy['port']}")

        print(f"\n代理URL列表:")
        proxy_urls = format_proxies_for_crawl4ai(proxies)
        for url in proxy_urls:
            print(f"  {url}")

    asyncio.run(main())
