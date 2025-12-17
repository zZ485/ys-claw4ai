import aiofiles  # 用于异步文件操作
import asyncio
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from config.logger_config import LoggerConfig
from config.path_config import default_path_config
from utils.content_cleaner import create_cleaner_from_config

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


class BatchWriter:
    """
    批量写入工具类，用于优化频繁IO操作
    """

    def __init__(
        self,
        file_name: str,
        batch_size: int = 10,
        flush_interval: int = 30,
        max_buffer_size: int = 200,
        cleaning_config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化批量写入器

        Args:
            file_name: 文件名
            batch_size: 达到此数量时自动写入文件，默认10条
            flush_interval: 达到此时间间隔(秒)时自动写入文件，默认30秒
            max_buffer_size: 缓冲区最大大小，超过此值强制刷新，默认200条
            cleaning_config: 清洗配置，格式为 {"source": 0/1, "image_source": 0/1, "author": 0/1}
        """
        self.file_name = file_name
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_buffer_size = max_buffer_size
        self.cleaning_config = cleaning_config
        self.content_cleaner = create_cleaner_from_config(cleaning_config)
        self.buffer: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._last_flush_time = datetime.now()
        self._flush_task = None
        self._closed = False

    async def add(self, item: Dict[str, Any]):
        """
        添加数据到缓冲区

        Args:
            item: 要添加的数据项，包含url和content
        """
        if self._closed:
            logger.warning("批量写入器已关闭，无法添加新数据")
            return

        async with self._lock:
            self.buffer.append(item)
            logger.debug(f"添加数据到缓冲区，当前缓冲区大小: {len(self.buffer)}")

            # 如果达到批量写入大小或缓冲区最大限制，立即写入
            if (
                len(self.buffer) >= self.batch_size
                or len(self.buffer) >= self.max_buffer_size
            ):
                await self._flush_buffer()
            # 如果这是第一个元素，启动定期写入任务
            elif len(self.buffer) == 1 and self._flush_task is None:
                self._flush_task = asyncio.create_task(self._periodic_flush())

    async def _flush_buffer(self):
        """
        将缓冲区内容写入文件
        """
        if not self.buffer:
            return

        try:
            # 复制缓冲区内容并清空原缓冲区
            items_to_write = self.buffer.copy()
            self.buffer = []
            self._last_flush_time = datetime.now()

            # 写入文件
            await self._write_to_file(items_to_write)
            # logger.info(f"批量写入完成: {len(items_to_write)} 条数据已写入文件 {self.file_name}")
        except Exception as e:
            # 如果写入失败，将数据重新放回缓冲区
            self.buffer = items_to_write + self.buffer
            logger.error(f"批量写入失败: {str(e)}")

    async def _write_to_file(self, items: List[Dict[str, Any]]):
        """
        实际执行文件写入操作

        Args:
            items: 要写入的数据列表
        """
        # 使用路径配置管理目录和文件路径
        default_path_config.ensure_results_dir_exists()
        file_path = default_path_config.get_output_file_path(self.file_name)

        # 对数据进行清洗过滤，内容长度大于50个字符
        filtered_items = []
        for item in items:
            content = item["content"].strip()
            if len(content) > 50:
                # 使用清洗器清洗内容
                if self.content_cleaner:
                    content = self.content_cleaner.clean_content(content)
                filtered_items.append({"url": item["url"], "content": content})

        # 使用aiofiles异步写入文件（追加模式）
        async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
            for item in filtered_items:
                await f.write(f"URL: {item['url']}\n")
                await f.write(f"{item['content']}\n\n")

    async def _periodic_flush(self):
        """
        定期刷新缓冲区到文件
        """
        while not self._closed:
            try:
                await asyncio.sleep(self.flush_interval)

                async with self._lock:
                    # 检查是否需要刷新（基于时间间隔）
                    if (
                        self.buffer
                        and (datetime.now() - self._last_flush_time).seconds
                        >= self.flush_interval
                    ):
                        await self._flush_buffer()
            except asyncio.CancelledError:
                # 任务被取消，正常退出
                break
            except Exception as e:
                logger.error(f"定期刷新任务异常: {str(e)}")

    async def flush(self):
        """
        手动刷新缓冲区到文件
        """
        async with self._lock:
            await self._flush_buffer()

    async def close(self):
        """
        关闭批量写入器，刷新所有剩余数据并停止定期任务
        """
        self._closed = True

        # 取消定期任务
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # 刷新剩余数据
        await self.flush()
        logger.info(f"批量写入器已关闭，所有数据已刷新到文件 {self.file_name}")


class BatchWriterManager:
    """
    批量写入器管理器，用于管理和复用BatchWriter实例
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BatchWriterManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.writers: Dict[str, BatchWriter] = {}
            self._lock = asyncio.Lock()
            self._initialized = True

    async def get_writer(
        self,
        file_name: str,
        batch_size: int = 10,
        flush_interval: int = 30,
        max_buffer_size: int = 200,
        cleaning_config: Optional[Dict[str, Any]] = None,
    ) -> BatchWriter:
        """
        获取或创建BatchWriter实例

        Args:
            file_name: 文件名
            batch_size: 批量写入大小
            flush_interval: 刷新间隔
            max_buffer_size: 缓冲区最大大小
            cleaning_config: 清洗配置，格式为 {"source": 0/1, "image_source": 0/1, "author": 0/1}

        Returns:
            BatchWriter实例
        """
        async with self._lock:
            if file_name not in self.writers:
                self.writers[file_name] = BatchWriter(
                    file_name,
                    batch_size,
                    flush_interval,
                    max_buffer_size,
                    cleaning_config,
                )
                # logger.info(f"创建新的批量写入器: {file_name}")
            return self.writers[file_name]

    async def close_writer(self, file_name: str):
        """
        关闭指定文件名的BatchWriter

        Args:
            file_name: 文件名
        """
        async with self._lock:
            if file_name in self.writers:
                await self.writers[file_name].close()
                del self.writers[file_name]
                logger.info(f"已关闭批量写入器: {file_name}")

    async def close_all(self):
        """
        关闭所有BatchWriter
        """
        async with self._lock:
            for writer in self.writers.values():
                await writer.close()
            self.writers = {}
            logger.info("已关闭所有批量写入器")


# 创建全局批量写入器管理器实例
batch_writer_manager = BatchWriterManager()
