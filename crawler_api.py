import asyncio
import aiofiles  # 用于异步文件操作
import importlib
import sys
import os
import traceback
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from config.target_elements_config import TargetElementsConfig
from config.display_names_config import ConfigDisplayNames
from config.logger_config import LoggerConfig
from config.db_config import get_db_config, validate_db_config
from config.path_config import PathConfig, default_path_config
from config.crawler_params_config import crawler_params_config
from utils.crawler_utils import crawl_urls
from utils.task_manager import task_manager

# 使用LoggerConfig设置日志，添加日期到日志文件名
project_root = os.path.dirname(os.path.abspath(__file__))
LoggerConfig.setup_crawler_logger(
    log_file="crawler_api", project_root=project_root, use_date=True
)
logger = LoggerConfig.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时的处理
    # logger.info("Crawl4AI API 服务启动")
    yield
    # 关闭时的处理
    # logger.info("Crawl4AI API 服务关闭中...")
    # 尝试执行清理操作，但不阻塞关闭过程
    try:
        await cleanup_on_shutdown()
    except Exception as e:
        logger.error(f"执行清理操作时发生异常: {str(e)}")


app = FastAPI(
    title="Crawl4AI API",
    description="一个用于网页内容爬取的API服务，支持多种目标网站的配置和动态加载配置",
    lifespan=lifespan,
)

# 添加CORS中间件以支持跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，可根据需要调整为特定域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)


# class CrawlerRequest(BaseModel):
#     url: str
#     target_elements: Optional[List[str]] = None
#     excluded_tags: Optional[List[str]] = None
#     target_config: Optional[str] = None
#     file_name: Optional[str] = None  # 新增字段，用于保存爬取结果到文件
#     batch_size: int = 10  # 批量写入大小，默认10条
#     flush_interval: int = 30  # 刷新间隔(秒)，默认30秒


class CollectRequest(BaseModel):
    target: str  # 目标配置，如 shanghai_cross_border_association_news
    task_name: str  # 任务名称
    is_incremental: int = 0  # 是否增量，1表示增量采集，0表示全量采集
    knowledge_base_name: str  # 知识库名称
    knowledge_base_id: str  # 知识库ID（必须提供）
    force_upload_by_id: bool = False  # 是否强制使用ID上传且不检查一致性
    cleaning_config: dict = {
        "source": 1,  # 0表示关闭，1表示开启
        "image_source": 1,  # 0表示关闭，1表示开启
        "author": 1,  # 0表示关闭，1表示开启
    }  # 清洗配置，默认全部开启


# class ScriptRequest(BaseModel):
#     pyName: str


class DownloadRequest(BaseModel):
    file_name: str


class TaskStatusRequest(BaseModel):
    task_id: str


class TaskListRequest(BaseModel):
    page: int = 1  # 页码，从1开始，默认为1
    page_size: int = 10  # 每页大小，默认为10
    # 模糊匹配条件
    task_id: Optional[str] = None  # 任务编号（模糊匹配）
    task_name: Optional[str] = None  # 任务名称（模糊匹配）
    # 时间段查询条件
    start_time: Optional[str] = None  # 开始时间（格式：YYYY-MM-DD）
    end_time: Optional[str] = None  # 结束时间（格式：YYYY-MM-DD）
    # 等值匹配条件
    collection_template: Optional[str] = None  # 采集模板（等值匹配）
    task_type: Optional[int] = None  # 任务类型（0-全量，1-增量）（等值匹配）
    task_status: Optional[str] = None  # 任务状态（等值匹配）
    knowledge_base_name: Optional[str] = None  # 知识库（等值匹配）


def build_response(code: int, message: str = "", data: dict = None):
    return {"code": code, "message": message, "data": data or {}}


# @app.post("/crawl")
# async def crawl_website(request: CrawlerRequest):
#     try:
#         # 检查是否使用了预设配置
#         target_elements = None
#         if request.target_config:
#             # 使用预设配置
#         target_elements = TargetElementsConfig.get_config(request.target_config)
#             if target_elements is None:
#                 return build_response(
#                     code=400,
#                     message=f"无效的目标配置: {request.target_config}"
#                 )
#         elif request.target_elements is not None:
#             # 使用用户提供的配置
#             target_elements = request.target_elements

#         # 调用爬虫工具函数
#         result = await crawl_single_url(
#             url=request.url,
#             target_elements=target_elements,
#             excluded_tags=request.excluded_tags,
#             file_name=request.file_name,
#             batch_size=request.batch_size,
#             flush_interval=request.flush_interval
#         )

#         if result["success"]:
#             return build_response(
#                 code=200,
#                 data={"content": result["content"]}
#             )
#         else:
#             return build_response(
#                 code=500,
#                 message=f"爬取失败: {result['error']}"
#             )

#     except Exception as e:
#         return build_response(
#             code=500,
#             message=f"服务器内部错误: {str(e)}"
#         )


@app.get("/target_configs")
async def get_target_configs():
    """
    获取所有可用的目标元素配置
    """
    try:
        # 从配置文件中获取格式化的配置列表
        formatted_configs = ConfigDisplayNames.get_formatted_configs()

        return build_response(code=200, message="获取配置成功", data=formatted_configs)
    except Exception as e:
        return build_response(code=500, message=f"获取配置失败: {str(e)}")


class ReloadConfigRequest(BaseModel):
    config_type: str  # 配置类型：display_names, target_elements, path, logger 或 all


# @app.post("/reload_config")
# async def reload_config(request: ReloadConfigRequest):
#     """
#     统一的配置重新加载接口

#     允许在运行时重新加载指定类型的配置，无需重启服务

#     参数:
#     - config_type: 配置类型
#       - "display_names": 显示名称配置
#       - "target_elements": 目标元素配置
#       - "path": 路径配置
#       - "logger": 日志配置
#       - "all": 重新加载所有配置
#     """
#     try:
#         results = {}

#         # 根据配置类型决定重新加载哪些配置
#         if request.config_type in ["display_names", "all"]:
#             display_config = ConfigDisplayNames.reload_config()
#             results["display_names"] = {"success": True, "count": len(display_config)}

#         if request.config_type in ["target_elements", "all"]:
#             target_config = TargetElementsConfig.reload_config()
#             results["target_elements"] = {"success": True, "count": len(target_config)}

#         if request.config_type in ["path", "all"]:
#             path_config = PathConfig.reload_config()
#             results["path"] = {"success": True, "config_keys": list(path_config.keys())}

#         if request.config_type in ["logger", "all"]:
#             logger_config = LoggerConfig.reload_config()
#             results["logger"] = {
#                 "success": True,
#                 "config_keys": list(logger_config.keys()),
#             }

#         if request.config_type in ["crawler_params", "all"]:
#             crawler_params = crawler_params_config.reload_config()
#             results["crawler_params"] = {
#                 "success": True,
#                 "chunk_size": crawler_params.get("crawler_config", {}).get(
#                     "chunk_size", 8
#                 ),
#             }

#         # 检查配置类型是否有效
#         if request.config_type not in [
#             "display_names",
#             "target_elements",
#             "path",
#             "logger",
#             "crawler_params",
#             "all",
#         ]:
#             return build_response(
#                 code=400,
#                 message=f"无效的配置类型: {request.config_type}。支持的类型: display_names, target_elements, path, logger, crawler_params, all",
#             )

#         return build_response(
#             code=200,
#             message="配置重新加载成功",
#             data={"config_type": request.config_type, "results": results},
#         )

#     except Exception as e:
#         return build_response(code=500, message=f"重新加载配置失败: {str(e)}")


@app.post("/collect")
async def collect_data(request: CollectRequest):
    """
    采集数据接口：创建异步采集任务，立即返回任务ID
    """
    logger.info(
        f"收到数据采集请求: target={request.target}, task_name={request.task_name}, is_incremental={request.is_incremental}, knowledge_base_name={request.knowledge_base_name}, knowledge_base_id={request.knowledge_base_id}, force_upload_by_id={request.force_upload_by_id}"
    )

    try:
        # 检查knowledge_base_id是否为空
        if not request.knowledge_base_id or not request.knowledge_base_id.strip():
            return build_response(code=400, message="knowledge_base_id不能为空")

        # 知识库一致性检查（除非强制上传）
        if not request.force_upload_by_id:
            # 如果提供了知识库ID，则需要检查与之前任务的一致性
            try:
                from utils.db_manager import get_db_manager

                db_config = get_db_config()
                db_manager = get_db_manager(
                    host=db_config.get("host", "localhost"),
                    port=db_config.get("port", 5236),
                    user=db_config.get("user", ""),
                    password=db_config.get("password", ""),
                    database=db_config.get("database", ""),
                    log_sql=db_config.get("log_sql", False),
                )

                # 获取该模板最近一次任务
                latest_task = await db_manager.get_latest_task_by_template(
                    request.target
                )
                if latest_task and latest_task.get("knowledge_base_id"):
                    # 检查知识库ID是否一致
                    if latest_task["knowledge_base_id"] != request.knowledge_base_id:
                        # 使用知识库名称而不是ID显示错误信息
                        old_kb_name = latest_task.get(
                            "knowledge_base_name", "未知知识库"
                        )
                        new_kb_name = request.knowledge_base_name or "未知知识库"
                        error_msg = f"该模板上次导入「{old_kb_name}」，本次导入「{new_kb_name}」，请确认！"
                        logger.warning(f"知识库ID不一致: {error_msg}")
                        return build_response(code=401, message=error_msg)
            except Exception as e:
                logger.error(f"检查知识库一致性时发生错误: {str(e)}")
                # 发生错误时不阻止任务创建，仅记录日志

        # 获取数据库配置
        try:
            db_config = get_db_config()
            # logger.info(f"获取数据库配置成功: {db_config.get('host', 'N/A')}:{db_config.get('port', 'N/A')}")
        except Exception as e:
            logger.error(f"获取数据库配置失败: {str(e)}")
            db_config = None

        # 使用任务管理器创建任务，传入数据库配置
        task_id = await task_manager.create_task(
            target=request.target,
            task_name=request.task_name,
            is_incremental=request.is_incremental,
            db_config=db_config,
            knowledge_base_name=request.knowledge_base_name,
            knowledge_base_id=request.knowledge_base_id,
            cleaning_config=request.cleaning_config,
        )

        logger.info(
            f"已创建采集任务: {task_id}, 任务名称: {request.task_name}, 任务类型: {'增量采集' if request.is_incremental == 1 else '全量采集'}"
        )

        # 立即返回任务创建成功响应
        return build_response(
            code=200,
            message="采集任务创建成功，正在后台执行",
            data={
                "task_id": task_id,
                "target": request.target,
                "task_name": request.task_name,
                "is_incremental": request.is_incremental,
                "knowledge_base_name": request.knowledge_base_name,
                "knowledge_base_id": request.knowledge_base_id,
                "force_upload_by_id": request.force_upload_by_id,
                "cleaning_config": request.cleaning_config,
                "file_name": task_id,
            },
        )

    except ValueError as e:
        # 验证失败等已知错误
        logger.warning(f"创建任务失败: {str(e)}")
        return build_response(code=400, message=str(e))

    except Exception as e:
        # 其他异常
        logger.error(f"创建任务异常: {str(e)}")
        logger.error(f"异常堆栈: {traceback.format_exc()}")
        return build_response(code=500, message=f"创建采集任务失败: {str(e)}")


# @app.get("/files")
# async def list_files():
#     """
#     列出results目录下所有可下载的文件
#     """
#     try:
#         # 确保结果目录存在
#         default_path_config.ensure_results_dir_exists()

#         results_dir = default_path_config.get_results_dir()

#         # 获取目录下所有文件
#         files = []
#         if os.path.exists(results_dir):
#             for file_name in os.listdir(results_dir):
#                 file_path = os.path.join(results_dir, file_name)
#                 if os.path.isfile(file_path) and file_name.endswith('.txt'):
#                     # 获取文件大小和修改时间
#                     stat = os.stat(file_path)
#                     files.append({
#                         "file_name": file_name,
#                         "file_size": stat.st_size,
#                         "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
#                     })

#         # 按修改时间降序排序
#         files.sort(key=lambda x: x['modified_time'], reverse=True)

#         return build_response(
#             code=200,
#             message="获取文件列表成功",
#             data={"files": files}
#         )

#     except Exception as e:
#         logger.error(f"获取文件列表异常: {str(e)}")
#         return build_response(
#             code=500,
#             message=f"获取文件列表错误: {str(e)}"
#         )


@app.post("/download")
async def download_file(request: DownloadRequest):
    """
    下载指定文件名的文件
    """
    try:
        file_name = request.file_name

        # 获取文件完整路径
        file_path = default_path_config.get_output_file_path(file_name)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return build_response(code=404, message=f"文件不存在: {file_name}")

        # 返回文件内容
        return FileResponse(path=file_path, filename=file_name, media_type="text/plain")

    except Exception as e:
        logger.error(f"下载文件异常: {str(e)}")
        return build_response(code=500, message=f"下载文件错误: {str(e)}")


# @app.get("/task/{task_id}")
# async def get_task_status(task_id: str):
#     """
#     获取指定任务的执行状态
#     """
#     try:
#         task_info = await task_manager.get_task_status(task_id)

#         if not task_info:
#             return build_response(
#                 code=404,
#                 message=f"任务不存在: {task_id}"
#             )

#         return build_response(
#             code=200,
#             message="获取任务状态成功",
#             data=task_info
#         )

#     except Exception as e:
#         logger.error(f"获取任务状态异常: {str(e)}")
#         return build_response(
#             code=500,
#             message=f"获取任务状态失败: {str(e)}"
#         )


@app.post("/tasks")
async def get_tasks_with_pagination(request: TaskListRequest):
    """
    分页获取任务列表（支持条件查询）
    """
    try:
        # 验证页码和页大小
        if request.page < 1:
            return build_response(code=400, message="页码必须大于0")
        if request.page_size < 1 or request.page_size > 100:
            return build_response(code=400, message="每页大小必须在1-100之间")

        # 构建查询条件
        query_conditions = {}

        # 模糊匹配条件
        if request.task_id:
            query_conditions["task_id_like"] = request.task_id
        if request.task_name:
            query_conditions["task_name_like"] = request.task_name

        # 时间段查询条件
        if request.start_time:
            query_conditions["start_time"] = request.start_time
        if request.end_time:
            query_conditions["end_time"] = request.end_time

        # 等值匹配条件
        if request.collection_template:
            query_conditions["collection_template"] = request.collection_template
        if request.task_type is not None:
            query_conditions["task_type"] = request.task_type
        if request.task_status:
            query_conditions["task_status"] = request.task_status
        if request.knowledge_base_name:
            query_conditions["knowledge_base_name"] = request.knowledge_base_name

        result = await task_manager.get_tasks_with_pagination(
            request.page, request.page_size, query_conditions=query_conditions
        )

        return build_response(code=200, message="获取任务列表成功", data=result)

    except Exception as e:
        logger.error(f"获取任务列表异常: {str(e)}")
        return build_response(code=500, message=f"获取任务列表失败: {str(e)}")


# @app.get("/tasks")
# async def get_all_tasks():
#     """
#     获取所有任务的执行状态（不分页）
#     """
#     try:
#         tasks = await task_manager.get_all_tasks()

#         return build_response(
#             code=200,
#             message="获取任务列表成功",
#             data={"tasks": tasks}
#         )

#     except Exception as e:
#         logger.error(f"获取任务列表异常: {str(e)}")
#         return build_response(
#             code=500,
#             message=f"获取任务列表失败: {str(e)}"
#         )

# @app.get("/debug/info")
# async def get_debug_info():
#     """
#     获取调试信息，用于检查系统状态
#     """
#     try:
#         # 检查任务管理器状态
#         task_count = len(task_manager.tasks)
#         db_connected = task_manager.db_manager is not None

#         # 检查数据库连接
#         db_status = "未连接"
#         if db_connected:
#             db_status = "已连接" if await task_manager.db_manager.is_connected() else "已断开"

#         # 获取数据库中的任务数量
#         db_task_count = 0
#         if db_connected and await task_manager.db_manager.is_connected():
#             try:
#                 count_sql = "SELECT COUNT(*) as total FROM collection_task"
#                 count_result = await task_manager.db_manager.execute_query(count_sql)
#                 db_task_count = count_result[0]["total"] if count_result else 0
#             except Exception as e:
#                 logger.error(f"获取数据库任务数量失败: {str(e)}")

#         debug_info = {
#             "task_manager": {
#                 "task_count": task_count,
#                 "db_manager_exists": db_connected,
#                 "db_status": db_status
#             },
#             "database": {
#                 "task_count": db_task_count
#             }
#         }

#         return build_response(
#             code=200,
#             message="获取调试信息成功",
#             data=debug_info
#         )

#     except Exception as e:
#         logger.error(f"获取调试信息异常: {str(e)}")
#         return build_response(
#             code=500,
#             message=f"获取调试信息失败: {str(e)}"
#         )

# @app.post("/cancel_task")
# async def cancel_task(request: TaskStatusRequest):
#     """
#     取消任务（仅对未开始执行的任务有效）
#     """
#     try:
#         success = task_manager.cancel_task(request.task_id)

#         if not success:
#             return build_response(
#                 code=400,
#                 message=f"无法取消任务: {request.task_id}（任务不存在或已开始执行）"
#             )

#         return build_response(
#             code=200,
#             message=f"任务已取消: {request.task_id}"
#         )

#     except Exception as e:
#         logger.error(f"取消任务异常: {str(e)}")
#         return build_response(
#             code=500,
#             message=f"取消任务失败: {str(e)}"
#         )

# @app.post("/execute_script")
# async def execute_script(request: ScriptRequest):
#     try:
#         script_name = request.pyName

#         # 确保脚本名以.py结尾
#         if not script_name.endswith('.py'):
#             script_name = f"{script_name}.py"

#         # 验证脚本是否存在
#         script_path = os.path.join(os.path.dirname(__file__), script_name)
#         if not os.path.exists(script_path):
#             return build_response(
#                 code=404,
#                 message=f"脚本 {script_name} 不存在"
#             )

#         # 动态导入模块并调用get_links方法
#         try:
#             # 获取模块名（去掉.py扩展名）
#             module_name = script_name[:-3] if script_name.endswith('.py') else script_name

#             # 动态导入模块
#             module = importlib.import_module(module_name)

#             # 检查模块是否有get_links方法
#             if not hasattr(module, 'get_links'):
#                 return build_response(
#                     code=400,
#                     message=f"脚本 {script_name} 缺少 get_links 方法"
#                 )

#             # 调用get_links方法
#             get_links_func = getattr(module, 'get_links')
#             result = await get_links_func()

#             return build_response(
#                 code=200,
#                 message=f"脚本 {script_name} 执行成功",
#                 data=result
#             )
#         except ImportError as e:
#             return build_response(
#                 code=500,
#                 message=f"无法导入模块 {script_name}: {str(e)}"
#             )

#     except Exception as e:
#         return build_response(
#             code=500,
#             message=f"脚本执行错误: {str(e)}"
#         )


async def cleanup_on_shutdown():
    """服务器关闭时执行清理操作"""
    logger.info("执行服务器关闭清理操作...")
    try:
        # 关闭所有批量写入器，确保数据不丢失
        try:
            from utils.batch_writer import batch_writer_manager

            if hasattr(batch_writer_manager, "close_all"):
                await batch_writer_manager.close_all()
                logger.info("批量写入器已全部关闭")
        except ImportError:
            logger.warning("无法导入批量写入器管理器，跳过清理")
        except Exception as e:
            logger.error(f"关闭批量写入器时发生异常: {str(e)}")

        # 断开数据库连接
        try:
            await task_manager.disconnect_db()
            logger.info("数据库连接已断开")
        except Exception as e:
            logger.error(f"断开数据库连接时发生异常: {str(e)}")

        # 执行其他清理操作...
        logger.info("服务器关闭清理操作完成")
    except Exception as e:
        logger.error(f"执行服务器关闭清理操作时发生异常: {str(e)}")


def setup_signal_handlers():
    """设置信号处理器，确保在异常关闭时执行清理"""
    import signal
    import sys

    def signal_handler(sig, frame):
        logger.info(f"接收到信号 {sig}，准备关闭服务...")
        sys.exit(0)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 终止信号


if __name__ == "__main__":
    # 设置信号处理器
    setup_signal_handlers()

    # print("启动 Crawl4AI API 服务...")
    # print("API 文档地址: http://127.0.0.1:8000/docs")
    # print("运行模式: 单线程模式（所有请求都在主线程处理）")

    try:
        # 启动服务器 - 单线程模式
        uvicorn.run(
            app, host="127.0.0.1", port=8001, log_level="info"  # 直接传递app实例
        )
    except Exception as e:
        logger.error(f"服务器运行异常: {str(e)}")
    finally:
        # 确保在退出前执行清理
        try:
            import asyncio

            # 检查是否有正在运行的事件循环
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    # 在循环中创建清理任务
                    loop.create_task(cleanup_on_shutdown())
            except RuntimeError:
                # 没有正在运行的循环，创建一个新的执行清理
                asyncio.run(cleanup_on_shutdown())
        except Exception as e:
            logger.error(f"设置清理任务失败: {str(e)}")
