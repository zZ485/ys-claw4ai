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
from utils.memory_monitor import memory_monitor

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


# async def crawl_single_url_async(url, run_config, batch_writer=None):
# try:
#     # 为每个URL创建独立的AsyncWebCrawler实例，避免并发冲突
#     async with AsyncWebCrawler(config=DEFAULT_BROWSER_CONFIG) as crawler:
#         result = await crawler.arun(url=url, config=run_config)
#
#         if result.success:
#             fit_markdown = getattr(result.markdown, 'fit_markdown', None) or result.markdown
#             data = {
#                 "url": url,
#                 "content": fit_markdown
#             }
#
#             # 使用批量写入器写入数据（如果提供了batch_writer）
#             if batch_writer:
#                 await batch_writer.add(data)
#
#             return True, data
#         else:
#             error_data = {
#                 "url": url,
#                 "error": result.error_message or '未知错误'
#             }
#             return False, error_data
# except Exception as e:
#     error_data = {
#         "url": url,
#         "error": str(e)
#     }
#     return False, error_data


async def crawl_urls(
    urls,
    target_elements=None,
    file_name=None,
    batch_size=10,
    flush_interval=30,
    progress_callback=None,
    memory_optimization_threshold=1000,
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

    # 记录初始内存使用情况（仅在内存使用率高时记录）
    memory_monitor.log_memory_usage(f"爬取开始，URL数量: {len(urls)}", "warning")

    # 获取内存优化建议
    memory_recommendations = memory_monitor.get_memory_recommendations(len(urls))
    if memory_recommendations.get("enable_memory_optimization", False):
        logger.info(f"已启用内存优化模式: {memory_recommendations}")

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

    # 创建信号量限制并发爬虫实例数
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

    async def process_chunk(chunk, chunk_index):
        """处理一个URL块"""
        nonlocal completed_count, crawled_count

        async with semaphore:
            logger.info(
                f"开始处理第 {chunk_index + 1}/{len(url_chunks)} 组URL，包含 {len(chunk)} 个URL"
            )
            chunk_start_time = datetime.now()

            try:
                # 创建爬虫实例并处理这组URL
                async with AsyncWebCrawler(config=DEFAULT_BROWSER_CONFIG) as crawler:
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
                                    error_data = {
                                        "url": result.url,
                                        "error": "爬取内容为空",
                                    }
                                    errors.append(error_data)
                                    logger.warning(
                                        f"URL爬取失败（内容为空）: {result.url}"
                                    )
                                else:
                                    data = {"url": result.url, "content": fit_markdown}

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

    # 定期检查内存使用情况
    async def monitor_memory_during_crawl():
        """在爬取过程中定期监控内存使用情况"""
        chunk_count = len(url_chunks)
        check_interval = max(1, chunk_count // 10)  # 每处理约10%的块检查一次

        for i in range(0, chunk_count, check_interval):
            await asyncio.sleep(0)  # 让出控制权

            # 检查内存使用是否超过阈值
            if memory_monitor.check_memory_threshold(80.0):
                logger.warning(f"内存使用率过高，已处理 {i}/{chunk_count} 组URL")

            # 记录内存使用情况（仅在内存使用率高时记录）
            if i % (check_interval * 2) == 0 or i >= chunk_count - 1:
                memory_monitor.log_memory_usage(f"爬取进度: {i}/{chunk_count}", "warning")

    # 启动内存监控任务
    memory_task = asyncio.create_task(monitor_memory_during_crawl())

    # 等待所有任务完成，处理可能的异常
    await asyncio.gather(*tasks, return_exceptions=True)

    # 取消内存监控任务
    memory_task.cancel()
    try:
        await memory_task
    except asyncio.CancelledError:
        pass

    # 刷新批量写入器中剩余的数据
    if batch_writer:
        await batch_writer.flush()

    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    # 记录完成时的内存使用情况（仅在内存使用率高时记录）
    memory_monitor.log_memory_usage(f"爬取完成，总耗时: {total_duration:.2f}秒", "warning")

    logger.info(
        f"批量爬取完成: 总耗时 {total_duration:.2f}秒, 成功 {crawled_count} 个, 失败 {len(errors)} 个"
    )

    # 注意：URL内容已通过批量写入器保存到文件
    if file_name:
        logger.info(f"所有成功爬取的URL内容已保存到文件: {file_name}")

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


# async def save_results_to_file(crawled_data, file_name):
#     """将爬取结果保存到文件
#
#     Args:
#         crawled_data: 爬取的数据列表
#         file_name: 保存的文件名
#     """
#     try:
#         # 使用路径配置管理目录和文件路径
#         default_path_config.ensure_results_dir_exists()
#         file_path = default_path_config.get_output_file_path(file_name)
#         # logger.info(f"准备写入文件: {file_path}, 共 {len(crawled_data)} 条数据")

#         # 对crawled_data进行清洗过滤，小于50个字符的数据（不包含url）不写入文件，去除开头结尾的空白字符
#         crawled_data = [item for item in crawled_data if len(item['content']) > 50]
#         crawled_data = [{'url': item['url'], 'content': item['content'].strip()} for item in crawled_data]

#         # 使用aiofiles异步写入文件（追加模式）
#         async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
#             for index, item in enumerate(crawled_data, 1):
#                 await f.write(f"URL: {item['url']}\n")
#                 await f.write(f"{item['content']}\n")
#                 if index % 10 == 0 or index == len(crawled_data):
#                     logger.info(f"已写入 {index}/{len(crawled_data)} 条数据到文件")

#         logger.info(f"文件写入成功: {file_path}")
#     except Exception as file_error:
#         logger.warning(f"异步文件写入失败: {str(file_error)}")
#         # 尝试使用同步写入作为备选方案
#         try:
#             logger.info("尝试使用同步方式写入文件")
#             with open(file_path, "a", encoding="utf-8") as f:
#                 for item in crawled_data:
#                     f.write(f"URL: {item['url']}\n")
#                     f.write(f"{item['content']}\n\n")
#             logger.info(f"同步文件写入成功: {file_path}")
#         except Exception as sync_error:
#             logger.error(f"同步文件写入也失败: {str(sync_error)}")
#             # 如果异步和同步写入都失败，忽略错误，继续返回爬取结果
#             pass


# async def crawl_single_url(url, target_elements=None, excluded_tags=None, file_name=None, batch_size=10, flush_interval=30):
#     """爬取单个URL

#     Args:
#         url: 要爬取的URL
#         target_elements: 可选，目标元素配置
#         excluded_tags: 可选，要排除的标签列表
#         file_name: 可选，保存结果的文件名
#         batch_size: 批量写入大小，默认10条
#         flush_interval: 刷新间隔(秒)，默认30秒

#     Returns:
#         dict: 包含爬取结果的字典
#     """
#     logger.info(f"开始爬取单个URL: {url}")
#     start_time = datetime.now()

#     run_config = await build_crawler_config(target_elements)
#     logger.info(f"爬虫配置已构建: target_elements={target_elements}, excluded_tags={excluded_tags}")

#     # 如果用户传了 excluded_tags 则替换掉默认值
#     if excluded_tags is not None:
#         logger.info(f"使用自定义排除标签: {excluded_tags}")
#         # 重新构建配置以应用 excluded_tags
#         markdown_generator = DefaultMarkdownGenerator(
#             content_filter=PruningContentFilter(
#                 threshold=0.48,
#                 threshold_type="fixed",
#                 min_word_threshold=0
#             )
#         )

#         run_config_kwargs = {
#             "cache_mode": CacheMode.BYPASS,
#             "markdown_generator": markdown_generator,
#             "excluded_tags": excluded_tags,
#             "exclude_social_media_links": True,
#             "remove_overlay_elements": True,
#             "simulate_user": True,
#             "override_navigator": True,
#             "exclude_external_images": True,
#         }

#         if target_elements is not None:
#             run_config_kwargs["target_elements"] = target_elements

#         run_config = CrawlerRunConfig(**run_config_kwargs)

#     logger.info("初始化AsyncWebCrawler...")
#     async with AsyncWebCrawler(config=DEFAULT_BROWSER_CONFIG) as crawler:
#         logger.info(f"开始爬取页面内容: {url}")
#         crawl_start_time = datetime.now()
#         result = await crawler.arun(url=url, config=run_config)
#         crawl_end_time = datetime.now()
#         crawl_duration = (crawl_end_time - crawl_start_time).total_seconds()

#         if not result.success:
#             logger.error(f"URL爬取失败: {url}, 错误: {result.error_message or '未知错误'}")
#             return {
#                 "success": False,
#                 "error": result.error_message or '未知错误'
#             }

#         fit_markdown = getattr(result.markdown, 'fit_markdown', None) or result.markdown
#         content_length = len(fit_markdown) if fit_markdown else 0

#         end_time = datetime.now()
#         total_duration = (end_time - start_time).total_seconds()

#         logger.info(f"URL爬取成功: {url}, 内容长度: {content_length}, 爬取耗时: {crawl_duration:.2f}秒, 总耗时: {total_duration:.2f}秒")

#         # 如果提供了file_name，使用批量写入器写入文件
#         if file_name:
#             logger.info(f"准备保存结果到文件: {file_name}")
#             batch_writer = await batch_writer_manager.get_writer(
#                 file_name=file_name,
#                 batch_size=batch_size,
#                 flush_interval=flush_interval
#             )

#             await batch_writer.add({
#                 "url": url,
#                 "content": fit_markdown
#             })

#             # 对于单个URL，立即刷新
#             await batch_writer.flush()

#         return {
#             "success": True,
#             "content": fit_markdown
#         }
