import asyncio
import random
from datetime import datetime
from typing import List, Optional, Dict, Tuple, Any

# 第三方库依赖
import aiohttp
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
)
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# 项目内部配置 (假设这些模块存在于你的项目中)
from config.logger_config import LoggerConfig
from config.crawler_params_config import crawler_params_config
from utils.batch_writer import batch_writer_manager

# 如果 utils.get_available_proxies 不存在，请确保 ProxyManager.fetch_and_fill_pool 中的导入路径正确

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)

# 固定浏览器配置
BASE_BROWSER_CONFIG_ARGS = [
    "--disable-gpu",
    "--disable-images",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


# ==========================================
# 1. 代理管理模块 (修复版)
# ==========================================
class ProxyManager:
    """代理管理器，支持自动维护与轮换，包含并发限制"""

    def __init__(self):
        self.proxy_queue = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def fetch_and_fill_pool(self):
        """调用工具函数获取已验证的新代理"""
        # 动态导入，避免循环引用
        try:
            from utils import get_available_proxies
        except ImportError:
            logger.error("无法导入 utils.get_available_proxies，请检查路径")
            return

        logger.info("[代理池] 正在请求新代理...")
        try:
            # 获取已验证的代理列表（dynamic_ip_util 已验证过）
            proxy_urls = await get_available_proxies()
            if not proxy_urls:
                logger.warning("[代理池] API返回为空")
                return

            # 直接添加到队列（无需重复验证）
            added_count = 0
            for proxy_url in proxy_urls:
                await self.proxy_queue.put(proxy_url)
                added_count += 1

            logger.info(
                f"[代理池] 补充完成，新增可用: {added_count}，当前库存: {self.proxy_queue.qsize()}"
            )

        except Exception as e:
            logger.error(f"[代理池] 刷新异常: {e}")

    async def get_proxy(self) -> str:
        """获取一个可用代理，如果池空了自动刷新"""
        async with self._lock:
            if self.proxy_queue.empty():
                await self.fetch_and_fill_pool()

            if self.proxy_queue.empty():
                logger.warning("[代理池] 暂时耗尽，等待 5 秒...")
                await asyncio.sleep(5)
                # 递归重试 (注意：如果网络一直不通可能会深层递归，生产环境可加最大深度限制)
                return await self.get_proxy()

            # 取出代理
            proxy = await self.proxy_queue.get()
            return proxy


class ProgressTracker:
    """全局进度追踪器 (线程安全)"""

    def __init__(self, total):
        self.total = total
        self.current = 0
        self._lock = asyncio.Lock()

    async def increment(self):
        async with self._lock:
            self.current += 1
            return self.current

    def get_progress_str(self, current):
        percent = (current / self.total) * 100 if self.total > 0 else 0
        return f"[进度: {current}/{self.total} | {percent:.1f}%]"


# ==========================================
# 2. 核心爬取逻辑 (修复版)
# ==========================================
async def crawl_urls(
    urls: List[str],
    target_elements: Optional[List[str]] = None,
    file_name: Optional[str] = None,
    batch_size: Optional[int] = None,
    flush_interval: Optional[int] = None,
    progress_callback=None,
    memory_optimization_threshold: int = 1000,
    cleaning_config: Optional[Dict] = None,
):
    """
    批量爬取URL列表，使用抢单模式（Work Stealing）提升并发效率。
    已修复无限重试死循环和队列竞态条件问题。
    """
    if not urls:
        logger.warning("URL列表为空，跳过爬取")
        return {"success_count": 0, "error_count": 0, "crawled_data": [], "errors": []}

    urls_count = len(urls)

    # --- 参数初始化 ---
    if batch_size is None:
        batch_size = crawler_params_config.get_batch_size(urls_count)
    if flush_interval is None:
        flush_interval = crawler_params_config.get_flush_interval(urls_count)

    # 获取代理配置
    use_dynamic_proxy = crawler_params_config.use_dynamic_proxy()
    proxy_settings = crawler_params_config.get_proxy_settings()
    max_consecutive_failures = proxy_settings.get("max_consecutive_failures", 3)
    # 单个URL最大重试次数 (防止无限死循环)
    max_url_retries = 3
    page_timeout = proxy_settings.get("page_timeout", 15000)

    logger.info(
        f"开始批量爬取，共 {urls_count} 个URL，批量写入大小: {batch_size}, 刷新间隔: {flush_interval}秒"
    )
    logger.info(f"动态代理: {'启用' if use_dynamic_proxy else '禁用'}")

    start_time = datetime.now()

    # --- 爬虫配置 ---
    markdown_generator = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(
            threshold=0.48, threshold_type="fixed", min_word_threshold=0
        )
    )

    run_config_kwargs = {
        "cache_mode": CacheMode.BYPASS,
        "markdown_generator": markdown_generator,
        "excluded_tags": ["img"],
        "page_timeout": page_timeout,
    }

    if target_elements is not None:
        run_config_kwargs["target_elements"] = target_elements

    run_config = CrawlerRunConfig(**run_config_kwargs)

    # --- 批量写入器 ---
    batch_writer = None
    if file_name:
        max_buffer_size = min(200, max(50, urls_count // 10))
        batch_writer = await batch_writer_manager.get_writer(
            file_name=file_name,
            batch_size=batch_size,
            flush_interval=flush_interval,
            max_buffer_size=max_buffer_size,
            cleaning_config=cleaning_config,
        )
        logger.info(f"批量写入器已初始化，文件: {file_name}")

    # --- 进度与队列 ---
    progress_tracker = ProgressTracker(urls_count)

    # 修复点：队列存储元组 (url, retry_count)
    task_queue = asyncio.Queue()
    for url in urls:
        await task_queue.put((url, 0))

    # 动态并发数
    max_crawlers = crawler_params_config.get_max_crawlers(urls_count)
    max_crawlers = min(max_crawlers, urls_count)
    logger.info(f"设置最大并发爬虫实例数: {max_crawlers}")

    # --- 代理初始化 ---
    proxy_manager = None
    if use_dynamic_proxy:
        proxy_manager = ProxyManager()
        await proxy_manager.fetch_and_fill_pool()
        if proxy_manager.proxy_queue.qsize() == 0:
            logger.warning("动态代理池为空，将不使用代理")

    # --- 数据存储 ---
    crawled_count = 0
    errors = []
    should_store_all_data = urls_count <= memory_optimization_threshold

    if should_store_all_data:
        crawled_data = []
    else:
        crawled_data = None
        logger.info(f"启用内存优化模式，不保存完整数据到内存")

    # ==========================================
    # Worker 逻辑
    # ==========================================
    async def worker_process(worker_id: int):
        nonlocal crawled_count
        consecutive_failures = 0  # 代理连续失败计数

        # 初始获取代理
        current_proxy = None
        if use_dynamic_proxy and proxy_manager:
            try:
                current_proxy = await proxy_manager.get_proxy()
                logger.info(f"[Worker-{worker_id}] 🟢 就绪 | 初始代理: {current_proxy}")
            except Exception as e:
                logger.warning(f"[Worker-{worker_id}] 获取代理失败: {e}")

        # Worker 主循环
        while True:
            # 1. 代理轮换检查
            if (
                consecutive_failures >= max_consecutive_failures
                and use_dynamic_proxy
                and proxy_manager
            ):
                logger.info(f"[Worker-{worker_id}] 🔄 代理质量差，正在更换...")
                try:
                    current_proxy = await proxy_manager.get_proxy()
                    consecutive_failures = 0
                except Exception as e:
                    logger.error(f"[Worker-{worker_id}] 更换代理失败: {e}")
                    consecutive_failures = 0  # 重置以免死循环获取

            # 2. 浏览器配置
            browser_config_kwargs = {
                "headless": True,
                "text_mode": True,
                "light_mode": True,
                "extra_args": BASE_BROWSER_CONFIG_ARGS,
            }
            if current_proxy:
                browser_config_kwargs["proxy"] = current_proxy

            browser_config = BrowserConfig(**browser_config_kwargs)

            try:
                # 3. 启动浏览器会话
                async with AsyncWebCrawler(config=browser_config) as crawler:

                    # 内层循环：处理任务
                    while True:
                        # 代理连续失败检查
                        if consecutive_failures >= max_consecutive_failures:
                            break  # 跳出内层循环 -> 更换代理

                        # >>> 修复点：鲁棒的队列获取逻辑 <<<
                        try:
                            item = task_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            # 队列空时，稍等一下再检查，防止因其他Worker正在重试put导致的竞态退出
                            await asyncio.sleep(1)
                            if task_queue.empty():
                                break  # 确认真的没了，退出内层循环
                            continue

                        # 解析任务
                        if isinstance(item, tuple):
                            url, retry_count = item
                        else:
                            url, retry_count = item, 0  # 兼容旧数据

                        try:
                            # 模拟随机延迟
                            await asyncio.sleep(random.uniform(1.0, 2.5))

                            # 执行爬取
                            result = await crawler.arun(url=url, config=run_config)

                            if result.success:
                                # >>> 成功 <<<
                                fit_markdown = (
                                    getattr(result.markdown, "fit_markdown", None)
                                    or result.markdown
                                )

                                # 内容有效性检查
                                if fit_markdown and len(fit_markdown.strip()) > 50:
                                    consecutive_failures = 0
                                    data = {"url": result.url, "content": fit_markdown}

                                    if batch_writer:
                                        await batch_writer.add(data)
                                    if should_store_all_data:
                                        crawled_data.append(data)
                                    crawled_count += 1

                                    # 成功才增加进度
                                    curr = await progress_tracker.increment()
                                    p_str = progress_tracker.get_progress_str(curr)
                                    logger.info(
                                        f"{p_str} [W-{worker_id}] √ {result.url[:40]}..."
                                    )
                                else:
                                    # 内容无效（视为完成）
                                    errors.append(
                                        {
                                            "url": result.url,
                                            "error": "Content too short/empty",
                                        }
                                    )
                                    curr = await progress_tracker.increment()
                                    p_str = progress_tracker.get_progress_str(curr)
                                    logger.warning(
                                        f"{p_str} [W-{worker_id}] ⊘ 内容无效"
                                    )
                                    consecutive_failures = 0

                                task_queue.task_done()

                            else:
                                # >>> 失败 <<<
                                err_msg = result.error_message or "Unknown"
                                err_lower = err_msg.lower()
                                fatal_keywords = [
                                    "proxy",
                                    "timeout",
                                    "timed out",
                                    "reset",
                                    "closed",
                                    "refused",
                                    "failed",
                                    "net::",
                                    "err_",
                                    "403",
                                    "503",
                                ]
                                is_fatal = any(k in err_lower for k in fatal_keywords)
                                is_404 = "404" in err_msg or result.status_code == 404

                                if is_fatal and not is_404:
                                    # ⚠️ 致命错误：检查重试次数
                                    if retry_count < max_url_retries:
                                        consecutive_failures += 1
                                        logger.warning(
                                            f"[W-{worker_id}] ⚠️ 网络波动(重试 {retry_count+1}/{max_url_retries}): {err_msg[:30]}..."
                                        )
                                        # 放回队列，计数+1
                                        await task_queue.put((url, retry_count + 1))
                                    else:
                                        # 超过重试次数，放弃
                                        logger.error(
                                            f"[W-{worker_id}] ❌ 超过最大重试次数，放弃: {url}"
                                        )
                                        errors.append(
                                            {
                                                "url": url,
                                                "error": f"Max retries: {err_msg}",
                                            }
                                        )
                                        # 放弃也算完成
                                        await progress_tracker.increment()

                                    task_queue.task_done()
                                else:
                                    # 404 等错误：视为完成
                                    errors.append({"url": result.url, "error": err_msg})
                                    curr = await progress_tracker.increment()
                                    p_str = progress_tracker.get_progress_str(curr)
                                    logger.info(
                                        f"{p_str} [W-{worker_id}] × {err_msg[:30]}..."
                                    )
                                    consecutive_failures = 0
                                    task_queue.task_done()

                        except Exception as e_inner:
                            # 异常捕获也需要处理重试逻辑
                            logger.error(f"[Worker-{worker_id}] 未知异常: {e_inner}")
                            if retry_count < max_url_retries:
                                await task_queue.put((url, retry_count + 1))
                            else:
                                errors.append({"url": url, "error": str(e_inner)})
                                await progress_tracker.increment()

                            task_queue.task_done()
                            consecutive_failures += 1

            except Exception as e_session:
                logger.error(f"[Worker-{worker_id}] 浏览器会话崩溃: {e_session}")
                await asyncio.sleep(1)
                consecutive_failures = max_consecutive_failures  # 触发换IP

            # 如果队列确实空了，跳出外层循环
            if task_queue.empty():
                break

        logger.info(f"[Worker-{worker_id}] 🛑 收工")

    # --- 启动所有 Worker ---
    worker_tasks = []
    for i in range(max_crawlers):
        worker_tasks.append(asyncio.create_task(worker_process(i + 1)))

    logger.info(f"🚀 启动 {len(worker_tasks)} 个抢单 Worker")
    await asyncio.gather(*worker_tasks)
    logger.info("所有 Worker 任务已结束。")

    # --- 资源清理 ---
    if batch_writer:
        try:
            await batch_writer.flush()
        except Exception as flush_e:
            logger.error(f"批量写入器刷新失败: {str(flush_e)}")

    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    logger.info(
        f"批量爬取完成: 总耗时 {total_duration:.2f}秒, 成功 {crawled_count} 个, 失败 {len(errors)} 个"
    )

    # 返回结果
    result_dict = {
        "success_count": crawled_count,
        "error_count": len(errors),
        "errors": errors,  # 注意：如果错误太多，建议只返回部分或写文件
    }

    if should_store_all_data:
        result_dict["crawled_data"] = crawled_data
    else:
        result_dict["crawled_data"] = None
        result_dict["memory_optimized"] = True

    return result_dict
