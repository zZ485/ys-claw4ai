import aiofiles  # 用于异步文件操作
import asyncio
import os
import logging
from datetime import datetime
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from config.logger_config import LoggerConfig
from config.path_config import default_path_config
from config.crawler_params_config import crawler_params_config
from utils.batch_writer import batch_writer_manager


# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


# 固定浏览器配置
DEFAULT_BROWSER_CONFIG = BrowserConfig(
    # headless=True,
    # verbose=False,
    text_mode=True,
    user_agent_mode="random",
)


async def build_crawler_config(target_elements):
    """构建爬虫配置"""
    # 构建 markdown generator（固定配置）
    markdown_generator = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(
            threshold=0.48, threshold_type="fixed", min_word_threshold=0
        )
    )

    # 构建 run_config 基础参数
    run_config_kwargs = {
        "cache_mode": CacheMode.BYPASS,  # 禁用缓存
        "markdown_generator": markdown_generator,  # markdown generator
        "excluded_tags": ["img"],  # 排除的标签
        # "exclude_social_media_links": True, # 排除社交媒体链接
        # "remove_overlay_elements": True, # 移除覆盖元素
        # "simulate_user": True, # 模拟用户
        # "override_navigator": True, # 覆盖浏览器信息
        # "exclude_external_images": True, # 排除外部图片
    }

    # 如果有 target_elements，则加入配置
    if target_elements is not None:
        run_config_kwargs["target_elements"] = target_elements

    return CrawlerRunConfig(**run_config_kwargs)


async def crawl_urls(
    urls,
    target_elements=None,
    file_name=None,
    batch_size=10,
    flush_interval=30,
    progress_callback=None,
    memory_optimization_threshold=1000,
    cleaning_config=None,
):
    """批量爬取URL列表，使用arun_many提升并发效率，每个爬虫实例处理8条链接

    Args:
        urls: 要爬取的URL列表
        target_elements: 目标元素配置
        file_name: 可选，保存结果的文件名
        batch_size: 批量写入大小，默认10条
        flush_interval: 刷新间隔(秒)，默认30秒
        progress_callback: 可选，进度回调函数，接收(completed, total)参数
        memory_optimization_threshold: 内存优化阈值，超过此数量的URL将不保存全部数据到内存
        cleaning_config: 清洗配置，格式为 {"source": 0/1, "image_source": 0/1, "author": 0/1}

    Returns:
        dict: 包含爬取结果的字典，大规模爬取时crawled_data为None以节省内存
    """
    if not urls:
        logger.warning("URL列表为空，跳过爬取")
        return {"success_count": 0, "error_count": 0, "crawled_data": [], "errors": []}

    logger.info(
        f"开始批量爬取，共 {len(urls)} 个URL，批量写入大小: {batch_size}, 刷新间隔: {flush_interval}秒"
    )
    start_time = datetime.now()

    run_config = await build_crawler_config(target_elements)
    logger.info(f"爬虫配置已构建: target_elements={target_elements}")

    # 初始化批量写入器（如果需要保存到文件）
    batch_writer = None
    if file_name:
        # 根据URL数量动态调整缓冲区大小
        max_buffer_size = min(200, max(50, len(urls) // 10))
        batch_writer = await batch_writer_manager.get_writer(
            file_name=file_name,
            batch_size=batch_size,
            flush_interval=flush_interval,
            max_buffer_size=max_buffer_size,
            cleaning_config=cleaning_config,  # 传递清洗配置
        )
        logger.info(
            f"批量写入器已初始化，批量大小: {batch_size}, 刷新间隔: {flush_interval}秒, 最大缓冲区: {max_buffer_size}条"
        )

    # 从配置中获取每个爬虫实例处理的URL数量
    chunk_size = crawler_params_config.get_chunk_size()
    url_chunks = [urls[i : i + chunk_size] for i in range(0, len(urls), chunk_size)]
    # logger.info(f"已将URL分成 {len(url_chunks)} 组，每组最多 {chunk_size} 个URL")

    # 初始化结果变量 - 使用计数器而非列表来节省内存
    crawled_count = 0
    errors = []
    completed_count = 0
    # 连续空白内容计数器
    consecutive_empty_count = 0
    max_consecutive_empty = 10
    # 全局停止标志
    should_stop = False

    # 使用传入的内存优化阈值
    should_store_all_data = len(urls) <= memory_optimization_threshold

    # 仅在需要时创建数据列表用于返回
    if should_store_all_data:
        crawled_data = []
    else:
        crawled_data = None
        logger.info(
            f"URL数量({len(urls)})超过阈值({memory_optimization_threshold})，启用内存优化模式，不会在内存中保存所有爬取数据"
        )

    # 根据URL数量动态设置并发爬虫实例的数量
    urls_count = len(urls)
    max_crawlers = crawler_params_config.get_max_crawlers(urls_count)

    # 确保最大并发数不超过URL组数，避免创建过多实例
    max_crawlers = min(max_crawlers, len(url_chunks))

    # 对于大规模爬取，进一步减少并发度以降低内存压力
    if not should_store_all_data:
        max_crawlers = min(max_crawlers, 4)  # 大规模爬取时最多4个并发实例
        logger.info(f"大规模爬取模式下，已将并发爬虫实例数限制为: {max_crawlers}")

    semaphore = asyncio.Semaphore(max_crawlers)
    logger.info(f"设置最大并发爬虫实例数: {max_crawlers}, 总URL组数: {len(url_chunks)}")

    logger.info(f"准备使用上下文管理器模式创建爬虫实例，最大并发数: {max_crawlers}")

    async def process_chunk(chunk, chunk_index):
        """处理一个URL块，为每个块创建独立的爬虫实例"""
        nonlocal completed_count, crawled_count, consecutive_empty_count, should_stop

        # 检查是否应该停止处理
        if should_stop:
            logger.info(f"检测到停止标志，跳过处理第 {chunk_index + 1} 组URL")
            return

        async with semaphore:
            # logger.info(
            #     f"开始处理第 {chunk_index + 1}/{len(url_chunks)} 组URL，包含 {len(chunk)} 个URL"
            # )
            chunk_start_time = datetime.now()

            try:
                # 再次检查是否应该停止处理
                if should_stop:
                    logger.info(
                        f"检测到停止标志，跳过创建爬虫实例处理第 {chunk_index + 1} 组URL"
                    )
                    return

                # 使用上下文管理器创建爬虫实例，确保正确初始化和清理
                async with AsyncWebCrawler(config=DEFAULT_BROWSER_CONFIG) as crawler:
                    # logger.info(f"第 {chunk_index + 1} 组URL的爬虫实例已创建并启动")

                    try:
                        # 使用非流式模式获取所有结果
                        results = await crawler.arun_many(
                            urls=chunk, config=run_config, stream=False
                        )

                        # 处理结果
                        for result in results:
                            if result.success:
                                fit_markdown = (
                                    getattr(result.markdown, "fit_markdown", None)
                                    or result.markdown
                                )

                                # 检查内容是否为空，如果为空则视为失败
                                if not fit_markdown or len(fit_markdown.strip()) <= 0:
                                    consecutive_empty_count += 1
                                    error_data = {
                                        "url": result.url,
                                        "error": "爬取内容为空",
                                    }
                                    errors.append(error_data)
                                    logger.warning(
                                        f"URL爬取失败（内容为空）: {result.url}, 连续空白次数: {consecutive_empty_count}"
                                    )

                                    # 检查是否超过最大连续空白次数
                                    if consecutive_empty_count >= max_consecutive_empty:
                                        error_data = {
                                            "url": "系统",
                                            "error": f"连续{consecutive_empty_count}次获取到空白内容，页面结构可能发生变化，无法获取内容",
                                        }
                                        errors.append(error_data)
                                        logger.error(
                                            f"连续{consecutive_empty_count}次获取到空白内容，结束爬取任务"
                                        )
                                        # 设置停止标志
                                        should_stop = True
                                        return
                                else:
                                    data = {"url": result.url, "content": fit_markdown}

                                    # 检查内容长度，如果内容小于等于50个字符则视为无效
                                    if len(fit_markdown.strip()) <= 50:
                                        consecutive_empty_count += 1
                                        error_data = {
                                            "url": result.url,
                                            "error": "内容长度不足50个字符",
                                        }
                                        errors.append(error_data)
                                        logger.warning(
                                            f"URL爬取失败（内容不足50个字符）: {result.url}, 内容长度: {len(fit_markdown.strip())}, 连续空白次数: {consecutive_empty_count}"
                                        )

                                        # 检查是否超过最大连续空白次数
                                        if (
                                            consecutive_empty_count
                                            >= max_consecutive_empty
                                        ):
                                            error_data = {
                                                "url": "系统",
                                                "error": f"连续{consecutive_empty_count}次获取到无效内容，页面结构可能发生变化，无法获取内容",
                                            }
                                            errors.append(error_data)
                                            logger.error(
                                                f"连续{consecutive_empty_count}次获取到无效内容，结束爬取任务"
                                            )
                                            # 设置停止标志
                                            should_stop = True
                                            return
                                    else:
                                        # 内容有效，重置连续空白计数器
                                        consecutive_empty_count = 0
                                        # 使用批量写入器写入数据
                                        if batch_writer:
                                            await batch_writer.add(data)

                                        # 仅在需要时将数据添加到内存列表
                                        if should_store_all_data:
                                            crawled_data.append(data)

                                        # 增加成功计数器
                                        crawled_count += 1
                                        # logger.info(f"URL爬取成功: {result.url}, 内容长度: {len(fit_markdown) if fit_markdown else 0}")
                            else:
                                error_data = {
                                    "url": result.url,
                                    "error": result.error_message or "未知错误",
                                }
                                errors.append(error_data)
                                logger.warning(
                                    f"URL爬取失败: {result.url}, 错误: {error_data['error']}"
                                )

                            completed_count += 1

                            # 调用进度回调函数，更新任务进度
                            if progress_callback and callable(progress_callback):
                                progress_callback(completed_count, urls_count)

                    except RuntimeError as rt_e:
                        # 处理RuntimeError，如浏览器/页面已关闭的情况
                        logger.error(
                            f"第 {chunk_index + 1} 组URL的arun_many调用失败(RuntimeError): {str(rt_e)}"
                        )
                        # 如果是浏览器或页面已关闭的错误，设置停止标志
                        if "closed" in str(rt_e).lower():
                            should_stop = True
                            logger.warning("检测到浏览器/页面已关闭，停止所有后续任务")

                        for url in chunk:
                            error_data = {
                                "url": url,
                                "error": f"批量爬取失败(RuntimeError): {str(rt_e)}",
                            }
                            errors.append(error_data)
                            completed_count += 1

                            # 调用进度回调函数，更新任务进度
                            if progress_callback and callable(progress_callback):
                                progress_callback(completed_count, urls_count)

                    except asyncio.CancelledError:
                        # 处理异步取消
                        logger.info(f"第 {chunk_index + 1} 组URL爬取任务被取消")
                        should_stop = True
                        for url in chunk:
                            error_data = {
                                "url": url,
                                "error": "任务被取消",
                            }
                            errors.append(error_data)
                            completed_count += 1

                            # 调用进度回调函数，更新任务进度
                            if progress_callback and callable(progress_callback):
                                progress_callback(completed_count, urls_count)
                        return

                    except Exception as inner_e:
                        # 如果arun_many本身失败，记录所有URL为失败
                        logger.error(
                            f"第 {chunk_index + 1} 组URL的arun_many调用失败: {str(inner_e)}"
                        )
                        for url in chunk:
                            error_data = {
                                "url": url,
                                "error": f"批量爬取失败: {str(inner_e)}",
                            }
                            errors.append(error_data)
                            completed_count += 1

                            # 调用进度回调函数，更新任务进度
                            if progress_callback and callable(progress_callback):
                                progress_callback(completed_count, urls_count)

                chunk_end_time = datetime.now()
                chunk_duration = (chunk_end_time - chunk_start_time).total_seconds()
                logger.info(
                    f"第 {chunk_index + 1} 组URL处理完成，耗时: {chunk_duration:.2f}秒"
                )

            except RuntimeError as rt_e:
                # 处理RuntimeError，如浏览器/页面已关闭的情况
                logger.error(
                    f"第 {chunk_index + 1} 组URL处理失败(RuntimeError): {str(rt_e)}"
                )
                # 如果是浏览器或页面已关闭的错误，设置停止标志
                if "closed" in str(rt_e).lower():
                    should_stop = True
                    logger.warning("检测到浏览器/页面已关闭，停止所有后续任务")

                for url in chunk:
                    error_data = {
                        "url": url,
                        "error": f"爬虫实例失败(RuntimeError): {str(rt_e)}",
                    }
                    errors.append(error_data)
                    completed_count += 1

                    # 调用进度回调函数，更新任务进度
                    if progress_callback and callable(progress_callback):
                        progress_callback(completed_count, urls_count)

            except asyncio.CancelledError:
                # 处理异步取消
                logger.info(f"第 {chunk_index + 1} 组URL爬取任务被取消")
                should_stop = True
                for url in chunk:
                    error_data = {
                        "url": url,
                        "error": "任务被取消",
                    }
                    errors.append(error_data)
                    completed_count += 1

                    # 调用进度回调函数，更新任务进度
                    if progress_callback and callable(progress_callback):
                        progress_callback(completed_count, urls_count)
                return
            except Exception as e:
                # 如果创建爬虫实例或处理整个块时发生异常，记录所有URL为失败
                logger.error(f"第 {chunk_index + 1} 组URL处理失败: {str(e)}")
                for url in chunk:
                    error_data = {"url": url, "error": f"爬虫实例失败: {str(e)}"}
                    errors.append(error_data)
                    completed_count += 1

                    # 调用进度回调函数，更新任务进度
                    if progress_callback and callable(progress_callback):
                        progress_callback(completed_count, urls_count)

    # 创建任务列表，并使用信号量控制并发
    tasks = []
    for i, chunk in enumerate(url_chunks):
        task = asyncio.create_task(process_chunk(chunk, i))
        tasks.append(task)

    try:
        # 等待所有任务完成，处理可能的异常
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # 设置停止标志，防止新任务继续执行
        should_stop = True
        # logger.info("所有URL组处理完成")

    # 刷新批量写入器中剩余的数据
    if batch_writer:
        try:
            await batch_writer.flush()
            # logger.info("批量写入器刷新完成")
        except Exception as flush_e:
            logger.error(f"批量写入器刷新失败: {str(flush_e)}")

    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    logger.info(
        f"批量爬取完成: 总耗时 {total_duration:.2f}秒, 成功 {crawled_count} 个, 失败 {len(errors)} 个"
    )

    # # 注意：URL内容已通过批量写入器保存到文件
    # if file_name:
    #     logger.info(f"所有成功爬取的URL内容已保存到文件: {file_name}")

    # 根据是否存储所有数据返回不同的结果
    if should_store_all_data:
        # 小规模爬取，返回完整数据
        return {
            "success_count": len(crawled_data),
            "error_count": len(errors),
            "crawled_data": crawled_data,
            "errors": errors,
        }
    else:
        # 大规模爬取，不返回实际数据以节省内存，仅返回统计信息
        return {
            "success_count": crawled_count,
            "error_count": len(errors),
            "crawled_data": None,  # 数据已写入文件，不返回到内存
            "errors": errors,
            "memory_optimized": True,  # 标识已使用内存优化
            "data_saved_to_file": file_name is not None,
        }
