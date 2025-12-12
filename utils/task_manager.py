import asyncio
import uuid
import sys
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from config.logger_config import LoggerConfig
from utils.crawler_utils import crawl_urls
from config.target_elements_config import TargetElementsConfig
from config.crawler_params_config import crawler_params_config
import importlib
import random
import string

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 正在执行
    SUCCESS = "success"  # 执行成功
    FAILED = "failed"    # 执行失败
    CANCELLED = "cancelled"  # 已取消


class Task:
    """任务类"""
    def __init__(self, task_id: str, target: str, task_name: str, is_incremental: int):
        self.task_id = task_id
        self.target = target
        # file_name 使用 task_id
        self.file_name = task_id
        # 这些字段由前端传递
        self.task_name = task_name  # 任务名称
        self.is_incremental = is_incremental  # 是否增量，0表示全量，1表示增量
        # 这些字段将在获取链接后动态设置
        self.batch_size: int = 10  # 批量写入大小，将根据链接数量动态调整
        self.flush_interval: int = 30  # 刷新间隔，将根据链接数量动态调整
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        # 只保存统计信息，不保存完整的爬取结果，避免内存问题
        self.success_count: int = 0
        self.error_count: int = 0
        self.total_links: int = 0
        self.progress: int = 0  # 任务进度百分比
        
    def to_dict(self) -> Dict[str, Any]:
        """将任务转换为字典"""
        return {
            "task_id": self.task_id,
            "target": self.target,
            "file_name": self.file_name,
            "task_name": self.task_name,
            "is_incremental": self.is_incremental,
            "status": self.status.value,
            "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "started_at": self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else None,
            "completed_at": self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
            "error_message": self.error_message,
            "progress": self.progress,
            "total_links": self.total_links,
            "success_count": self.success_count,
            "error_count": self.error_count
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
        if not self._initialized:
            self.tasks: Dict[str, Task] = {}
            self.max_completed_tasks = 5  # 最多保留的已完成任务数量
            self.task_queue = []  # 任务队列，保存等待执行的任务ID
            self.is_task_running = False  # 当前是否有任务正在执行
            self._initialized = True
            logger.info("任务管理器初始化完成")
    
    async def create_task(self, target: str, task_name: str, is_incremental: int) -> str:
        """
        创建新任务并添加到队列中，按照先来后到的顺序执行
        
        Args:
            target: 目标配置
            task_name: 任务名称
            is_incremental: 是否增量，0表示全量，1表示增量
            
        Returns:
            str: 任务ID
        """
        # 验证target是否有效
        configs = TargetElementsConfig.get_all_configs()
        if target not in configs:
            raise ValueError(f"无效的目标配置: {target}")
        
        # 生成任务ID：年月日时分秒+随机4位大小写字母
        now = datetime.now()
        time_str = now.strftime('%Y%m%d%H%M%S')
        random_str = ''.join(random.choices(string.ascii_letters, k=4))
        task_id = time_str + random_str
        
        # 创建任务
        task = Task(task_id, target, task_name, is_incremental)
        self.tasks[task_id] = task
        
        # 将任务添加到队列中
        self.task_queue.append(task_id)
        # logger.info(f"已创建任务并添加到队列: {task_id}, target: {target}, task_name={task_name}, is_incremental={is_incremental}")
        
        # 如果当前没有任务在执行，则启动队列处理
        if not self.is_task_running:
            asyncio.create_task(self._process_queue())
        
        return task_id
    
    async def _process_queue(self):
        """处理任务队列，按先来后到的顺序执行任务"""
        if self.is_task_running or not self.task_queue:
            return
            
        self.is_task_running = True
        # logger.info("开始处理任务队列")
        
        while self.task_queue:
            # 从队列头部取出任务（先来后到）
            task_id = self.task_queue.pop(0)
            task = self.tasks.get(task_id)
            
            if not task:
                logger.warning(f"队列中的任务 {task_id} 不存在，跳过")
                continue
                
            if task.status != TaskStatus.PENDING:
                logger.warning(f"任务 {task_id} 状态不是 PENDING，跳过执行")
                continue
                
            # 执行任务
            await self._execute_task(task)
            
        # 队列处理完毕
        self.is_task_running = False
        # logger.info("任务队列处理完毕")
    
    async def _execute_task(self, task: Task):
        """在后台执行任务"""
        try:
            # 更新任务状态为运行中
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            logger.info(f"开始执行任务: {task.task_id}")
            
            # 获取链接列表
            target = task.target
            
            # 直接使用target作为脚本名
            script_name = target
            
            # 确保脚本名以.py结尾
            if not script_name.endswith('.py'):
                script_name = f"{script_name}.py"
            
            # 验证脚本是否存在
            import os
            # 获取脚本目录路径
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script_path = os.path.join(project_root, "get_links_script", script_name)
            if not os.path.exists(script_path):
                raise FileNotFoundError(f"脚本 {script_name} 不存在于 get_links_script 目录中")
            
            # 动态导入模块并调用get_links方法
            module_name = script_name[:-3] if script_name.endswith('.py') else script_name
            # 确保get_links_script目录可以作为一个包被导入
            get_links_script_path = os.path.join(project_root, "get_links_script")
            if get_links_script_path not in sys.path:
                sys.path.insert(0, get_links_script_path)
            
            # 从get_links_script目录导入模块
            try:
                module = importlib.import_module(module_name)
                logger.info(f"成功导入模块: {module_name}")
            except ImportError as e:
                # 如果直接导入失败，尝试作为子模块导入
                try:
                    module = importlib.import_module(f"get_links_script.{module_name}")
                    logger.info(f"成功导入子模块: get_links_script.{module_name}")
                except ImportError as inner_e:
                    logger.error(f"导入模块失败: {module_name}, 错误: {str(e)}, 子模块错误: {str(inner_e)}")
                    raise ImportError(f"无法导入模块 {module_name}: {str(e)}")
            
            if not hasattr(module, 'get_links'):
                raise AttributeError(f"脚本 {script_name} 缺少 get_links 方法")
            
            # 调用get_links方法获取链接列表
            get_links_func = getattr(module, 'get_links')
            links_result = await get_links_func()
            
            # 处理不同的返回格式
            links = None
            if isinstance(links_result, list):
                links = links_result
            elif isinstance(links_result, dict) and 'links' in links_result:
                links = links_result['links']
            
            if not links:
                raise ValueError(f"脚本 {script_name} 返回了空的链接列表")
            
            # 更新进度和总链接数
            progress_settings = crawler_params_config.get_progress_settings()
            task.progress = progress_settings.get("progress_after_fetch", 20)  # 获取链接完成
            task.total_links = len(links)
            
            # 根据链接数量动态设置任务参数
            links_count = len(links)
            
            # 从配置中获取动态参数
            task.batch_size = crawler_params_config.get_batch_size(links_count)
            task.flush_interval = crawler_params_config.get_flush_interval(links_count)
            
            logger.info(f"任务 {task.task_id} 动态参数设置完成: task_name={task.task_name}, "
                       f"is_incremental={task.is_incremental}, batch_size={task.batch_size}, "
                       f"flush_interval={task.flush_interval}, links_count={links_count}")
            
            # 调用爬虫工具函数批量爬取所有链接，并提供进度回调函数
            configs = TargetElementsConfig.get_all_configs()
            
            # 从配置中获取进度设置
            progress_settings = crawler_params_config.get_progress_settings()
            progress_after_fetch = progress_settings.get("progress_after_fetch", 20)
            progress_after_crawl = progress_settings.get("progress_after_crawl", 90)
            
            # 创建进度回调函数，每完成一个链接更新进度
            def progress_callback(completed, total):
                if total > 0:
                    # 每个链接完成的进度增量 = (爬取完成进度 - 获取链接进度) / 总链接数
                    progress_range = progress_after_crawl - progress_after_fetch
                    progress_per_link = progress_range / total
                    # 当前进度 = 获取链接进度 + 已完成链接数 * 每个链接的进度增量
                    task.progress = min(progress_after_crawl, progress_after_fetch + int(completed * progress_per_link))
            
            result = await crawl_urls(
                urls=links,
                target_elements=configs[target],
                file_name=task.file_name,
                batch_size=task.batch_size,
                flush_interval=task.flush_interval,
                progress_callback=progress_callback  # 传递进度回调函数
            )
            
            # 更新统计信息，不保存完整结果
            progress_settings = crawler_params_config.get_progress_settings()
            task.progress = progress_settings.get("progress_after_crawl", 90)  # 爬取完成
            task.success_count = result['success_count']
            task.error_count = result['error_count']
            
            # 任务完成
            task.status = TaskStatus.SUCCESS
            task.progress = progress_settings.get("progress_complete", 100)
            task.completed_at = datetime.now()
            
            logger.info(f"任务执行成功: {task.task_id}, 成功 {result['success_count']} 个, 失败 {result['error_count']} 个")
            
            # 清理过多的已完成任务
            self._cleanup_completed_tasks()
            
        except Exception as e:
            # 任务失败
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.now()
            logger.error(f"任务执行失败: {task.task_id}, 错误: {str(e)}")
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            Dict: 任务状态信息，如果任务不存在则返回None
        """
        task = self.tasks.get(task_id)
        return task.to_dict() if task else None
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """
        获取所有任务列表，按创建时间排序
        
        Returns:
            List[Dict]: 所有任务信息列表
        """
        # 按创建时间排序（先创建的任务在前）
        sorted_tasks = sorted(self.tasks.values(), key=lambda task: task.created_at)
        return [task.to_dict() for task in sorted_tasks]
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务（对队列中和未开始执行的任务有效）
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        # 如果任务在队列中且状态为PENDING，可以取消
        if task.status == TaskStatus.PENDING:
            # 从队列中移除（如果在队列中）
            if task_id in self.task_queue:
                self.task_queue.remove(task_id)
                
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            logger.info(f"任务已取消: {task_id}")
            return True
        
        return False
    
    def _cleanup_completed_tasks(self):
        """
        清理过多的已完成任务，保留最近的max_completed_tasks个
        """
        # 按完成时间排序，只保留已完成的任务
        completed_tasks = [
            (task_id, task) for task_id, task in self.tasks.items()
            if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        
        # 如果已完成任务超过最大限制，删除最旧的任务
        if len(completed_tasks) > self.max_completed_tasks:
            # 按完成时间排序，最旧的在前
            completed_tasks.sort(key=lambda x: x[1].completed_at or datetime.min)
            
            # 删除最旧的任务
            to_remove = len(completed_tasks) - self.max_completed_tasks
            for i in range(to_remove):
                task_id, _ = completed_tasks[i]
                del self.tasks[task_id]
                logger.info(f"已清理完成的任务: {task_id}")


# 创建全局任务管理器实例
task_manager = TaskManager()