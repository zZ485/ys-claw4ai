import asyncio
import importlib
import os
import random
import string
import sys
import traceback
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from config.crawler_params_config import crawler_params_config
from config.logger_config import LoggerConfig
from config.target_elements_config import TargetElementsConfig
from config.path_config import default_path_config
from config.knowledge_base_config import KnowledgeBaseConfig
from utils.crawler_utils import crawl_urls
from utils.db_manager import get_db_manager
from utils.knowledge_base_uploader import upload_document_to_knowledge_base

logger = LoggerConfig.get_logger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""

    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 正在执行
    SUCCESS = "success"  # 执行成功
    FAILED = "failed"  # 执行失败
    CANCELLED = "cancelled"  # 已取消


class Task:
    """任务类"""

    def __init__(
        self,
        task_id: str,
        collection_template: str,
        task_name: str,
        is_incremental: int,
        knowledge_base_name: str = "",
        knowledge_base_id: str = "",
        cleaning_config: dict = {
            "source": 1,  # 0表示关闭，1表示开启
            "image_source": 1,  # 0表示关闭，1表示开启
            "author": 1,  # 0表示关闭，1表示开启
        },  # 清洗配置，默认全部开启
        skip_knowledge_import: bool = False,  # 是否跳过知识库导入
    ):
        self.task_id = task_id
        self.collection_template = collection_template  # 采集模板名称
        self.task_name = task_name
        self.is_incremental = is_incremental  # 0-全量采集, 1-增量采集
        self.knowledge_base_name = knowledge_base_name
        self.knowledge_base_id = knowledge_base_id  # 知识库ID
        self.cleaning_config = cleaning_config  # 清洗配置
        self.enable_cleaning = 1
        self.skip_knowledge_import = skip_knowledge_import  # 是否跳过知识库导入
        self.file_name = task_id
        self.batch_size: int = 10  # 将根据链接数量动态调整
        self.flush_interval: int = 30  # 将根据链接数量动态调整
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.failure_reason: Optional[str] = None
        self.success_count: int = 0
        self.error_count: int = 0
        self.total_links: int = 0
        self.progress: int = 0  # 任务进度百分比(0-100)

    def to_dict(self) -> Dict[str, Any]:
        """将任务转换为字典，适配新表结构"""
        status_value = self.status.value
        return {
            "task_id": self.task_id,
            "collection_template": self.collection_template,
            "task_name": self.task_name,
            "task_type": self.is_incremental,  # 0-全量, 1-增量
            "is_incremental": self.is_incremental,
            "knowledge_base_name": self.knowledge_base_name,
            "knowledge_base_id": self.knowledge_base_id,
            "enable_cleaning": self.enable_cleaning,
            "cleaning_config": self.cleaning_config,
            "task_status": status_value,
            "failure_reason": self.failure_reason,
            "create_time": self.created_at,
            "complete_time": self.completed_at,
            "progress": int(self.progress),
            "total_links": self.total_links,
            "success_count": self.success_count,
            "error_count": self.error_count,
        }


class TaskManager:
    """任务管理器单例类，实现任务队列机制"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TaskManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.tasks: Dict[str, Task] = {}
        self.task_queue = []  # 任务队列，保存等待执行的任务ID
        self.is_task_running = False  # 当前是否有任务正在执行
        self.db_manager = None  # 数据库管理器
        self._initialized = True

        # 尝试初始化数据库管理器
        try:
            from config.db_config import get_db_config

            db_config = get_db_config()
            if db_config:
                self.db_manager = get_db_manager(
                    host=db_config.get("host", "localhost"),
                    port=db_config.get("port", 5236),
                    user=db_config.get("user", ""),
                    password=db_config.get("password", ""),
                    database=db_config.get("database", ""),
                    log_sql=db_config.get("log_sql", False),
                    pool_size=db_config.get("pool_size", 10),  # 添加连接池大小配置
                )
        except Exception as e:
            logger.error(f"数据库管理器初始化失败: {str(e)}")

    async def create_task(
        self,
        target: str,
        task_name: str,
        is_incremental: int,
        knowledge_base_name: str = "",
        knowledge_base_id: str = "",
        cleaning_config: dict = {
            "source": 1,  # 0表示关闭，1表示开启
            "image_source": 1,  # 0表示关闭，1表示开启
            "author": 1,  # 0表示关闭，1表示开启
        },  # 清洗配置，默认全部开启
        db_config: Optional[Dict[str, Any]] = None,
        skip_knowledge_import: bool = False,  # 是否跳过知识库导入
    ) -> str:
        """
        创建新任务并添加到队列中，按照先来后到的顺序执行

        Args:
            target: 采集模板名称（保留原始参数名）
            task_name: 任务名称
            is_incremental: 任务类型，1表示增量采集，0表示全量采集
            knowledge_base_name: 知识库名称
            knowledge_base_id: 知识库ID
            cleaning_config: 清洗配置，格式为 {"source": 0/1, "image_source": 0/1, "author": 0/1}
            db_config: 数据库配置信息（可选，如果提供则初始化数据库连接）

        Returns:
            str: 任务ID
        """
        # 验证target是否有效
        configs = TargetElementsConfig.get_all_configs()
        if target not in configs:
            raise ValueError(f"无效的采集模板: {target}")

        # 初始化数据库连接
        if db_config:
            try:
                if not self.db_manager:
                    self.db_manager = get_db_manager(
                        host=db_config.get("host", "localhost"),
                        port=db_config.get("port", 5236),
                        user=db_config.get("user", ""),
                        password=db_config.get("password", ""),
                        database=db_config.get("database", ""),
                        log_sql=db_config.get("log_sql", False),
                        pool_size=db_config.get("pool_size", 10),  # 添加连接池大小配置
                    )
                # 使用连接池，这里不需要显式连接
                await self.db_manager.connect()
            except Exception as e:
                logger.error(f"数据库连接失败: {str(e)}")
                raise

        # 生成任务ID：年月日时分秒+随机4位大小写字母，保持与原逻辑相同
        now = datetime.now()
        time_str = now.strftime("%Y%m%d%H%M%S")
        random_str = "".join(random.choices(string.ascii_letters, k=4))
        task_id = f"{time_str}{random_str}"

        task = Task(
            task_id=task_id,
            collection_template=target,
            task_name=task_name,
            is_incremental=is_incremental,
            knowledge_base_name=knowledge_base_name,
            knowledge_base_id=knowledge_base_id,
            cleaning_config=cleaning_config,
            skip_knowledge_import=skip_knowledge_import,
        )
        self.tasks[task_id] = task

        # 将任务添加到队列
        self.task_queue.append(task_id)

        # 保存任务信息到数据库
        if self.db_manager:
            try:
                await self.db_manager.save_task(task.to_dict())
                # logger.info(f"任务信息已保存到数据库: {task_id}")
            except Exception as e:
                logger.error(f"保存任务到数据库失败: {str(e)}")

        logger.info(
            f"已创建任务并添加到队列: {task_id}, "
            f"collection_template: {target}, "
            f"task_name={task_name}, "
            f"is_incremental={is_incremental}, "
            f"knowledge_base_name={knowledge_base_name}, "
            f"knowledge_base_id={knowledge_base_id}"
        )

        # 如果没有任务在执行，则启动队列处理
        if not self.is_task_running:
            asyncio.create_task(self._process_queue())

        return task_id

    async def _process_queue(self):
        """处理任务队列，按先来后到的顺序执行任务"""
        if self.is_task_running or not self.task_queue:
            return

        self.is_task_running = True
        # logger.info("开始处理任务队列")

        # 检查是否应该停止处理任务
        shutdown_requested = False

        while self.task_queue and not shutdown_requested:
            task_id = self.task_queue.pop(0)
            task = self.tasks.get(task_id)

            if not task:
                logger.warning(f"队列中的任务 {task_id} 不存在，跳过")
                continue

            if task.status != TaskStatus.PENDING:
                logger.warning(f"任务 {task_id} 状态不是 PENDING，跳过执行")
                continue

            try:
                await self._execute_task(task)
            except asyncio.CancelledError:
                logger.info("任务队列处理被取消")
                shutdown_requested = True
                # 标记剩余任务为已取消
                for remaining_id in self.task_queue:
                    if remaining_id in self.tasks:
                        remaining_task = self.tasks[remaining_id]
                        remaining_task.status = TaskStatus.CANCELLED
                        remaining_task.failure_reason = "服务器关闭，任务被取消"
                        remaining_task.completed_at = datetime.now()
                        logger.info(f"任务 {remaining_id} 已被标记为取消")

                        # 尝试更新数据库，但不阻止关闭流程
                        try:
                            if self.db_manager:
                                await self.db_manager.update_task(
                                    remaining_id, remaining_task.to_dict()
                                )
                        except Exception as e:
                            logger.warning(
                                f"更新取消任务 {remaining_id} 到数据库失败: {str(e)}"
                            )
                break

        self.is_task_running = False
        # logger.info("任务队列处理完毕")

    async def disconnect_db(self):
        """断开数据库连接"""
        try:
            if self.db_manager:
                logger.info("任务管理器数据库连接管理器已断开")
                # 关闭所有正在运行的任务（只标记状态，不进行数据库更新）
                for task_id, task in self.tasks.items():
                    if task.status == TaskStatus.RUNNING:
                        task.status = TaskStatus.CANCELLED
                        task.failure_reason = "服务器关闭，任务被取消"
                        task.completed_at = datetime.now()
                        logger.info(f"任务 {task_id} 已被标记为取消")

                # 断开数据库连接（不调用disconnect方法，直接将引用设为None）
                # 数据库连接池会在全局清理函数中关闭
                self.db_manager = None
                logger.info("任务管理器数据库连接已关闭")
            else:
                logger.info("任务管理器没有活跃的数据库连接")
        except Exception as e:
            logger.error(f"断开任务管理器数据库连接时出错: {str(e)}")

    async def _execute_task(self, task: Task):
        """在后台执行任务"""
        try:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()

            # 创建任务特定的日志记录器
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            task_logger = LoggerConfig.setup_task_logger(task.task_id, project_root)

            logger.info(f"开始执行任务: {task.task_id}")
            task_logger.info(f"任务 {task.task_id} 开始执行")

            if self.db_manager:
                await self.db_manager.update_task(task.task_id, task.to_dict())

            # 使用collection_template获取脚本
            template_name = task.collection_template
            script_name = (
                f"{template_name}.py"
                if not template_name.endswith(".py")
                else template_name
            )

            # 获取脚本路径
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script_path = os.path.join(project_root, "get_links_script", script_name)

            if not os.path.exists(script_path):
                raise FileNotFoundError(
                    f"脚本 {script_name} 不存在于 get_links_script 目录中"
                )

            # 确保脚本目录在导入路径中
            get_links_script_path = os.path.join(project_root, "get_links_script")
            if get_links_script_path not in sys.path:
                sys.path.insert(0, get_links_script_path)

            # 动态导入模块
            module_name = script_name[:-3]
            try:
                module = importlib.import_module(module_name)
            except ImportError as e:
                try:
                    module = importlib.import_module(f"get_links_script.{module_name}")
                except ImportError as inner_e:
                    logger.error(
                        f"导入模块失败: {module_name}, 错误: {str(e)}, "
                        f"子模块错误: {str(inner_e)}"
                    )
                    raise ImportError(f"无法导入模块 {module_name}: {str(e)}")

            if not hasattr(module, "get_links"):
                raise AttributeError(f"脚本 {script_name} 缺少 get_links 方法")

            # 调用get_links方法
            get_links_func = getattr(module, "get_links")
            is_incremental = int(task.is_incremental) == 1  # 1-增量, 0-全量
            logger.info(
                f"任务 {task.task_id} 使用 "
                f"{'增量采集' if is_incremental else '全量采集'} 模式获取链接"
            )
            task_logger.info(
                f"使用 {'增量采集' if is_incremental else '全量采集'} 模式获取链接"
            )

            # 检查函数参数
            import inspect

            sig = inspect.signature(get_links_func)
            call_kwargs = {}

            if "is_incremental" in sig.parameters:
                call_kwargs["is_incremental"] = is_incremental
            if "db_manager" in sig.parameters and self.db_manager:
                call_kwargs["db_manager"] = self.db_manager

            # 调用函数
            if call_kwargs:
                links_result = await get_links_func(**call_kwargs)
            else:
                links_result = await get_links_func()
                if not is_incremental:
                    logger.warning(
                        f"脚本 {script_name} 不支持全量采集模式，将使用增量采集模式"
                    )

            # 处理返回结果
            links = (
                links_result["links"]
                if isinstance(links_result, dict) and "links" in links_result
                else links_result
            )

            if not links:
                raise ValueError(
                    f"脚本 {script_name} 返回了空的链接列表 可能原因：1.获取链接脚本失效 2.增量模式下无新增文章链接"
                )

            # # 保存最新链接
            # if links and self.db_manager:
            #     try:
            #         await self.db_manager.save_latest_link(
            #             task.collection_template, links[0]
            #         )
            #     except Exception as e:
            #         logger.error(f"保存最新链接失败: {str(e)}")

            # 动态设置任务参数
            links_count = len(links)
            progress_settings = crawler_params_config.get_progress_settings()
            memory_settings = crawler_params_config.get_memory_settings()

            task.progress = progress_settings.get("progress_after_fetch", 20)
            task.total_links = links_count
            task.batch_size = crawler_params_config.get_batch_size(links_count)
            task.flush_interval = crawler_params_config.get_flush_interval(links_count)

            logger.info(
                f"任务 {task.task_id} 动态参数设置完成: "
                f"task_name={task.task_name}, "
                f"is_incremental={task.is_incremental}, "
                f"batch_size={task.batch_size}, "
                f"flush_interval={task.flush_interval}, "
                f"links_count={links_count}, "
                f"file_name={task.file_name} (与task_id相同)"
            )
            task_logger.info(
                f"动态参数设置完成: "
                f"task_name={task.task_name}, "
                f"is_incremental={task.is_incremental}, "
                f"batch_size={task.batch_size}, "
                f"flush_interval={task.flush_interval}, "
                f"links_count={links_count}"
            )

            if self.db_manager:
                await self.db_manager.update_task(task.task_id, task.to_dict())

            # 爬取链接
            configs = TargetElementsConfig.get_all_configs()
            progress_after_fetch = progress_settings.get("progress_after_fetch", 20)
            progress_after_crawl = progress_settings.get("progress_after_crawl", 90)

            def progress_callback(completed: int, total: int):
                if total > 0:
                    progress_range = progress_after_crawl - progress_after_fetch
                    progress_per_link = progress_range / total
                    current_progress = progress_after_fetch + int(
                        completed * progress_per_link
                    )
                    task.progress = min(progress_after_crawl, current_progress)

                    # 实时更新数据库中的进度
                    if self.db_manager:
                        asyncio.create_task(
                            self.db_manager.update_task(task.task_id, task.to_dict())
                        )

            target_elements = configs[task.collection_template]

            # 从配置中获取内存优化阈值
            memory_optimization_threshold = memory_settings.get(
                "memory_optimization_threshold", 1000
            )

            task_logger.info(f"开始爬取 {len(links)} 个链接")
            try:
                result = await crawl_urls(
                    urls=links,
                    target_elements=target_elements,
                    file_name=task.file_name,  # 保持原有逻辑，使用file_name
                    batch_size=task.batch_size,
                    flush_interval=task.flush_interval,
                    progress_callback=progress_callback,
                    memory_optimization_threshold=memory_optimization_threshold,  # 使用配置中的内存优化阈值
                    cleaning_config=task.cleaning_config,  # 传递清洗配置
                )
            except asyncio.CancelledError:
                logger.info(f"任务 {task.task_id} 被取消")
                task_logger.info("任务被取消")
                task.status = TaskStatus.CANCELLED
                task.failure_reason = "任务被取消"
                task.completed_at = datetime.now()

                # 尝试更新数据库，但不阻止任务取消流程
                try:
                    if self.db_manager:
                        await self.db_manager.update_task(task.task_id, task.to_dict())
                except Exception as e:
                    logger.warning(
                        f"更新取消任务 {task.task_id} 到数据库失败: {str(e)}"
                    )
                    task_logger.warning(f"更新取消任务到数据库失败: {str(e)}")

                return

            # 更新任务结果
            task.progress = progress_after_crawl
            task.success_count = result["success_count"]
            task.error_count = result["error_count"]
            task.status = TaskStatus.SUCCESS
            task.progress = progress_settings.get("progress_complete", 100)
            task.completed_at = datetime.now()

            logger.info(
                f"任务执行成功: {task.task_id}, "
                f"成功 {result['success_count']} 个, "
                f"失败 {result['error_count']} 个, "
                f"文件保存为: {task.file_name}.txt"
            )
            task_logger.info(
                f"任务执行成功, "
                f"成功 {result['success_count']} 个, "
                f"失败 {result['error_count']} 个, "
                f"文件保存为: {task.file_name}.txt"
            )

            # 只有满足以下所有条件才会上传到知识库：
            # 1. 知识库名称不为空
            # 2. 全局自动上传开关开启
            # 3. 未设置跳过知识库导入（即知识库ID和名称不都为"-1"）
            if (
                task.knowledge_base_name
                and task.knowledge_base_name.strip()
                and KnowledgeBaseConfig.is_auto_upload_enabled()
                and not task.skip_knowledge_import
            ):
                await self._upload_to_knowledge_base(task, task_logger)
                task_logger.info("已上传文档到知识库")
            elif task.skip_knowledge_import:
                task_logger.info("知识库ID和名称均为-1，已跳过知识库导入")
            elif not KnowledgeBaseConfig.is_auto_upload_enabled():
                task_logger.info("全局自动上传开关已关闭，已跳过知识库导入")

            if self.db_manager:
                await self.db_manager.update_task(task.task_id, task.to_dict())

        except asyncio.CancelledError:
            # 处理异步取消
            logger.info(f"任务 {task.task_id} 被取消")
            task.status = TaskStatus.CANCELLED
            task.failure_reason = "任务被取消"
            task.completed_at = datetime.now()

            try:
                task_logger = LoggerConfig.get_logger(f"task_{task.task_id}")
                task_logger.info("任务被取消")
            except:
                pass

            if self.db_manager:
                try:
                    await self.db_manager.update_task(task.task_id, task.to_dict())
                except Exception as e:
                    logger.warning(
                        f"更新取消任务 {task.task_id} 到数据库失败: {str(e)}"
                    )
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.failure_reason = str(e)
            task.completed_at = datetime.now()

            # 获取任务日志记录器（如果存在）
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            task_logger = LoggerConfig.get_logger(f"task_{task.task_id}")

            logger.error(f"任务执行失败: {task.task_id}, 错误: {str(e)}", exc_info=True)
            logger.error(traceback.format_exc())

            try:
                task_logger.error(f"任务执行失败: {str(e)}")
                task_logger.error(traceback.format_exc())
            except:
                # 如果任务日志记录器不可用，忽略错误
                pass

            if self.db_manager:
                await self.db_manager.update_task(task.task_id, task.to_dict())

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            Dict: 任务状态信息，如果任务不存在则返回None
        """
        # 优先从数据库获取
        if self.db_manager:
            try:
                db_task = await self.db_manager.get_task(task_id)
                if db_task:
                    return db_task
            except Exception as e:
                logger.error(f"从数据库获取任务状态失败: {str(e)}")

        # 回退到内存
        task = self.tasks.get(task_id)
        if task:
            return task.to_dict()

        return None

    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        """
        获取所有任务列表，按创建时间排序

        Returns:
            List[Dict]: 所有任务信息列表
        """
        # 优先从数据库获取
        if self.db_manager:
            try:
                return await self.db_manager.get_all_tasks()
            except Exception as e:
                logger.error(f"从数据库获取所有任务失败: {str(e)}")

        # 回退到内存
        sorted_tasks = sorted(
            self.tasks.values(),
            key=lambda task: task.created_at,
            reverse=True,  # 按创建时间倒序
        )
        return [task.to_dict() for task in sorted_tasks]

    async def get_tasks_with_pagination(
        self,
        page: int = 1,
        page_size: int = 10,
        query_conditions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        分页获取任务列表，按创建时间排序，支持条件查询

        Args:
            page: 页码，从1开始，默认为1
            page_size: 每页大小，默认为10
            query_conditions: 查询条件字典
                - 模糊匹配字段: task_id_like, task_name_like, complete_time_like
                - 等值匹配字段: collection_template, task_type, task_status, knowledge_base_name

        Returns:
            Dict: 包含分页信息和任务列表的字典
        """
        # 如果没有提供查询条件，初始化为空字典
        if query_conditions is None:
            query_conditions = {}

        # 优先从数据库获取
        if self.db_manager:
            try:
                return await self.db_manager.get_tasks_with_pagination(
                    page, page_size, query_conditions
                )
            except Exception as e:
                logger.error(f"数据库分页查询失败: {str(e)}")

        # 回退到内存
        sorted_tasks = sorted(
            self.tasks.values(),
            key=lambda task: task.created_at,
            reverse=True,  # 按创建时间倒序
        )
        all_tasks = [task.to_dict() for task in sorted_tasks]

        # 应用过滤条件
        filtered_tasks = all_tasks

        # 模糊匹配条件
        if query_conditions.get("task_id_like"):
            keyword = query_conditions["task_id_like"].lower()
            filtered_tasks = [
                task
                for task in filtered_tasks
                if keyword in task.get("task_id", "").lower()
            ]

        if query_conditions.get("task_name_like"):
            keyword = query_conditions["task_name_like"].lower()
            filtered_tasks = [
                task
                for task in filtered_tasks
                if keyword in task.get("task_name", "").lower()
            ]

        if query_conditions.get("complete_time_like"):
            keyword = query_conditions["complete_time_like"]
            filtered_tasks = [
                task
                for task in filtered_tasks
                if task.get("complete_time") and keyword in task["complete_time"]
            ]

        # 等值匹配条件
        if query_conditions.get("collection_template"):
            template = query_conditions["collection_template"]
            filtered_tasks = [
                task
                for task in filtered_tasks
                if task.get("collection_template") == template
            ]

        if query_conditions.get("task_type") is not None:
            task_type = query_conditions["task_type"]
            filtered_tasks = [
                task for task in filtered_tasks if task.get("task_type") == task_type
            ]

        if query_conditions.get("task_status"):
            status = query_conditions["task_status"]
            filtered_tasks = [
                task for task in filtered_tasks if task.get("task_status") == status
            ]

        if query_conditions.get("knowledge_base_name"):
            kb_name = query_conditions["knowledge_base_name"]
            filtered_tasks = [
                task
                for task in filtered_tasks
                if task.get("knowledge_base_name") == kb_name
            ]

        total = len(filtered_tasks)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "tasks": filtered_tasks[start:end],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }

    # async def cancel_task(self, task_id: str) -> bool:
    #     """
    #     取消任务（对队列中和未开始执行的任务有效）

    #     Args:
    #         task_id: 任务ID

    #     Returns:
    #         bool: 是否成功取消
    #     """
    #     task = self.tasks.get(task_id)
    #     if not task:
    #         return False

    #     if task.status == TaskStatus.PENDING:
    #         if task_id in self.task_queue:
    #             self.task_queue.remove(task_id)

    #         task.status = TaskStatus.CANCELLED
    #         task.completed_at = datetime.now()
    #         task.failure_reason = "任务被用户取消"

    #         if self.db_manager:
    #             await self.db_manager.update_task(task.task_id, task.to_dict())

    #         logger.info(f"任务已取消: {task_id}")
    #         return True

    #     return False

    async def _upload_to_knowledge_base(self, task, task_logger):
        """
        将采集完成的文档上传到知识库

        Args:
            task: 任务对象
            task_logger: 任务日志记录器
        """
        try:
            # 获取文件路径
            file_name = f"{task.file_name}.txt"
            file_path = default_path_config.get_output_file_path(file_name)

            # 检查文件是否存在
            if not os.path.exists(file_path):
                error_msg = f"要上传的文件不存在: {file_path}"
                logger.error(error_msg)
                task_logger.error(error_msg)
                task.failure_reason = f"上传到知识库失败: {error_msg}"
                task.status = TaskStatus.FAILED
                return

            dataset_id = task.knowledge_base_id

            # 检查dataset_id是否为空
            if not dataset_id or not dataset_id.strip():
                error_msg = "知识库ID或名称不能为空"
                logger.error(error_msg)
                task_logger.error(error_msg)
                task.failure_reason = f"上传到知识库失败: {error_msg}"
                return

            # 从配置获取知识库API地址和超时设置
            api_base_url = KnowledgeBaseConfig.get_api_base_url()
            upload_timeout = KnowledgeBaseConfig.get_upload_timeout()

            logger.info(f"开始上传文档 {file_name} 到知识库 {dataset_id}")
            task_logger.info(f"开始上传文档到知识库: {dataset_id}")

            # 调用上传函数，使用知识库ID字段
            upload_result = await upload_document_to_knowledge_base(
                file_path=file_path,
                dataset_id=dataset_id,  # 使用知识库ID
                api_base_url=api_base_url,
                timeout=upload_timeout,
            )

            if upload_result["success"]:
                logger.info(f"文档上传成功: {file_name} -> {dataset_id}")
                task_logger.info(f"文档上传到知识库成功: {dataset_id}")
            else:
                error_msg = f"上传到知识库失败: {upload_result['error']}"
                logger.error(error_msg)
                task_logger.error(error_msg)
                # 注意：这里不修改任务状态为失败，因为采集已经成功完成
                # 只记录错误信息，避免因上传失败导致整个任务失败

        except Exception as e:
            error_msg = f"上传文档到知识库时发生异常: {str(e)}"
            logger.error(error_msg)
            task_logger.error(error_msg)
            # 同样，只记录错误，不修改任务状态

    async def disconnect_db(self):
        """断开数据库连接"""
        # 不需要断开连接，因为连接池是全局共享的
        # 连接池将在应用关闭时关闭
        if self.db_manager:
            logger.info("任务管理器数据库连接管理器已断开")


# 创建全局任务管理器实例
task_manager = TaskManager()
