"""
SQLite 数据库操作模块
用于管理任务数据的持久化存储
实现了连接池机制，连接健康检查和自动重连功能
从达梦数据库迁移而来，保持相同的对外接口
"""

import asyncio
import os
import sqlite3
import threading
import time
import traceback
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Dict, List, Optional

from config.logger_config import LoggerConfig

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)


async def init_database_connection_pool(
    host: str = "localhost",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
    log_sql: bool = False,
    pool_size: Optional[int] = None,
):
    """
    初始化全局数据库连接池

    Args:
        host: 未使用（兼容旧接口）
        port: 未使用（兼容旧接口）
        user: 未使用（兼容旧接口）
        password: 未使用（兼容旧接口）
        database: SQLite 数据库文件路径，为空则使用默认路径
        log_sql: 是否记录SQL日志
        pool_size: 连接池大小，默认None表示使用默认值
    """
    try:
        manager = get_db_manager(
            host, port, user, password, database, log_sql, pool_size
        )
        await manager.connect()
        db_path = manager.db_path or "默认路径"
        logger.info(f"SQLite 数据库连接池初始化成功: {db_path}")
        return True
    except Exception as e:
        logger.error(f"SQLite 数据库连接池初始化失败: {str(e)}")
        return False


async def cleanup_database_resources():
    """清理数据库资源"""
    close_connection_pool()
    logger.info("SQLite 数据库资源清理完成")


class DatabaseConnection:
    """数据库连接封装类，用于连接池管理"""

    def __init__(self, connection, pool, last_used=None):
        self.connection = connection
        self.pool = pool
        self.last_used = last_used or time.time()
        self.in_use = False
        self.is_valid = True

    def update_last_used(self):
        """更新最后使用时间"""
        self.last_used = time.time()

    def is_expired(self, max_lifetime=3600):
        """检查连接是否过期"""
        return time.time() - self.last_used > max_lifetime

    def is_healthy(self):
        """检查连接是否健康"""
        if not self.connection or self.is_valid is False:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except Exception:
            self.is_valid = False
            return False

    def close(self):
        """关闭连接"""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.is_valid = False


class ConnectionPool:
    """SQLite 数据库连接池"""

    def __init__(
        self,
        min_connections=2,
        max_connections=10,
        connection_timeout=30,
        max_lifetime=3600,
        health_check_interval=300,
    ):
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.connection_timeout = connection_timeout
        self.max_lifetime = max_lifetime
        self.health_check_interval = health_check_interval

        self._pool = Queue()
        self._all_connections = []
        self._connection_count = 0
        self._lock = threading.Lock()
        self._closed = False

        # SQLite 数据库文件路径
        self.db_path = None

        # 当前获取的连接（上下文管理器用）
        self._acquired_conn: DatabaseConnection | None = None

        # 健康检查线程
        self._health_check_thread = None

    def configure(self, db_path):
        """配置 SQLite 数据库路径"""
        self.db_path = db_path

    def _create_connection(self):
        """创建新连接"""
        if not self.db_path:
            raise ValueError("SQLite 数据库路径未配置")
        try:
            # 启用 WAL 模式以提高并发读写性能
            connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.row_factory = sqlite3.Row
            return DatabaseConnection(connection, self)
        except Exception as e:
            logger.error(f"创建 SQLite 连接失败: {str(e)}")
            raise

    def _initialize_pool(self):
        """初始化连接池，创建最小连接数"""
        if not self.db_path:
            raise ValueError("SQLite 数据库路径未配置")

        for _ in range(self.min_connections):
            try:
                conn = self._create_connection()
                self._pool.put(conn)
                self._all_connections.append(conn)
                self._connection_count += 1
            except Exception as e:
                logger.error(f"初始化连接池失败: {str(e)}")
                raise

    def start(self):
        """启动连接池"""
        self._initialize_pool()
        self._start_health_check()
        logger.info(f"SQLite 连接池已启动，初始连接数: {self.min_connections}")

    def _start_health_check(self):
        """启动健康检查线程"""
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop, daemon=True
        )
        self._health_check_thread.start()

    def _health_check_loop(self):
        """健康检查循环"""
        while not self._closed:
            try:
                self._perform_health_check()
                time.sleep(self.health_check_interval)
            except Exception as e:
                logger.error(f"连接池健康检查异常: {str(e)}")
                time.sleep(30)

    def _perform_health_check(self):
        """执行健康检查"""
        with self._lock:
            for conn in list(self._all_connections):
                if not conn.in_use and not conn.is_healthy():
                    logger.warning("发现不健康的 SQLite 连接，将其移除")
                    self._remove_connection(conn)

            active_connections = len([c for c in self._all_connections if c.is_valid])
            if active_connections < self.min_connections:
                needed = self.min_connections - active_connections
                logger.info(f"创建 {needed} 个新连接以满足最小连接数")
                for _ in range(needed):
                    try:
                        conn = self._create_connection()
                        self._pool.put(conn)
                        self._all_connections.append(conn)
                        self._connection_count += 1
                    except Exception as e:
                        logger.error(f"创建新连接失败: {str(e)}")

    def _remove_connection(self, conn):
        """从连接池中移除连接"""
        try:
            conn.close()
            if conn in self._all_connections:
                self._all_connections.remove(conn)
                self._connection_count -= 1
        except Exception as e:
            logger.error(f"移除连接失败: {str(e)}")

    async def __aenter__(self):
        """异步上下文管理器入口：获取连接"""
        return self._acquired_conn.connection

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口：归还连接"""
        conn = getattr(self, '_acquired_conn', None)
        if conn:
            conn.in_use = False
            try:
                self._pool.put(conn, timeout=5)
            except Exception:
                logger.warning("无法将连接放回池中，可能池已关闭")
            if exc_type:
                conn.is_valid = False
                logger.error(f"使用连接时发生错误: {exc_val}")
        self._acquired_conn = None
        return False

    def get_connection(self):
        """获取数据库连接（返回异步上下文管理器）"""
        if self._closed:
            raise RuntimeError("连接池已关闭")
        # 重新获取连接并返回 self 作为上下文管理器
        self._acquired_conn = self._acquire_connection()
        return self

    def _acquire_connection(self) -> DatabaseConnection:
        """从连接池获取一个可用连接"""
        if self._closed:
            raise RuntimeError("连接池已关闭")

        conn = None
        try:
            conn = self._pool.get(timeout=self.connection_timeout)
        except Empty:
            if self._connection_count < self.max_connections:
                with self._lock:
                    if self._connection_count < self.max_connections:
                        conn = self._create_connection()
                        self._all_connections.append(conn)
                        self._connection_count += 1

            if not conn:
                logger.warning("连接池已满，等待可用连接")
                conn = self._pool.get(timeout=self.connection_timeout)

        if conn and (conn.is_expired(self.max_lifetime) or not conn.is_healthy()):
            self._remove_connection(conn)
            with self._lock:
                if self._connection_count < self.max_connections:
                    conn = self._create_connection()
                    self._all_connections.append(conn)
                    self._connection_count += 1
                else:
                    conn = self._pool.get(timeout=self.connection_timeout)

        conn.in_use = True
        conn.update_last_used()
        return conn

    def close(self):
        """关闭连接池"""
        self._closed = True

        for conn in self._all_connections:
            conn.close()

        self._all_connections.clear()
        self._connection_count = 0

        while not self._pool.empty():
            try:
                self._pool.get_nowait()
            except Empty:
                break

        logger.info("SQLite 连接池已关闭")

    async def disconnect(self):
        """断开数据库连接（异步版本）"""
        self.close()


class DatabaseManager:
    """SQLite 数据库管理器（保持与达梦版本相同的对外接口）"""

    _pool = None
    _pool_lock = threading.Lock()

    def __init__(
        self,
        host: str = "localhost",
        port: int = 0,
        user: str = "",
        password: str = "",
        database: str = "",
        log_sql: bool = False,
        pool_size: Optional[int] = None,
    ):
        """
        初始化数据库连接参数

        Args:
            host: 未使用（兼容旧接口）
            port: 未使用（兼容旧接口）
            user: 未使用（兼容旧接口）
            password: 未使用（兼容旧接口）
            database: SQLite 数据库文件路径，为空则使用默认路径
            log_sql: 是否记录SQL日志
            pool_size: 连接池大小
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.log_sql = log_sql

        # 确定 SQLite 数据库文件路径
        self.db_path = self._resolve_db_path(database)

        # 初始化连接池
        self._init_pool(pool_size)

    def _resolve_db_path(self, database: str) -> str:
        """解析数据库文件路径"""
        if database and database != "SYSDBA" and not database.upper().startswith("SYSDBA"):
            # 如果指定了有效的数据库名/路径
            if os.path.isabs(database):
                return database
            # 相对路径：基于项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_dir = os.path.join(project_root, "data")
            os.makedirs(db_dir, exist_ok=True)
            # 如果路径以 .db 结尾直接使用，否则加上 .db 后缀
            if database.endswith(".db"):
                return os.path.join(db_dir, database)
            return os.path.join(db_dir, f"{database}.db")
        else:
            # 默认路径：项目根目录/data/crawler.db
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_dir = os.path.join(project_root, "data")
            os.makedirs(db_dir, exist_ok=True)
            return os.path.join(db_dir, "crawler.db")

    def _init_pool(self, pool_size):
        """初始化连接池"""
        with DatabaseManager._pool_lock:
            if DatabaseManager._pool is None:
                min_conn = 2
                max_conn = 10
                if pool_size:
                    min_conn = max(1, pool_size // 2)
                    max_conn = pool_size

                DatabaseManager._pool = ConnectionPool(
                    min_connections=min_conn,
                    max_connections=max_conn,
                    connection_timeout=30,
                    max_lifetime=3600,
                    health_check_interval=300,
                )
                DatabaseManager._pool.configure(self.db_path)
                DatabaseManager._pool.start()

    @property
    def pool(self):
        """获取连接池"""
        return DatabaseManager._pool

    async def connect(self):
        """连接到 SQLite 数据库（兼容旧版本接口）"""
        if not self.pool or self.pool._closed:
            logger.warning("连接池不可用，尝试重新初始化")
            self._init_pool(None)

        # 自动初始化表结构
        await self._ensure_tables()

        logger.info(f"SQLite 数据库连接池已就绪: {self.db_path}")
        return True

    async def _ensure_tables(self):
        """确保数据库表存在，不存在则自动创建"""
        try:
            # 检查 collection_task 表是否存在
            result = await self.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_task'"
            )
            if not result:
                logger.info("collection_task 表不存在，自动创建...")
                await self._create_tables()

            # 检查 collected_links 表是否存在
            result = await self.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='collected_links'"
            )
            if not result:
                logger.info("collected_links 表不存在，自动创建...")
                await self._create_tables()
        except Exception as e:
            logger.error(f"检查/创建表失败: {str(e)}")
            raise

    async def _create_tables(self):
        """创建数据库表"""
        create_task_sql = """
        CREATE TABLE IF NOT EXISTS collection_task (
            task_id TEXT PRIMARY KEY,
            task_name TEXT NOT NULL,
            task_status TEXT NOT NULL,
            collection_template TEXT NOT NULL,
            task_type INTEGER NOT NULL CHECK (task_type IN (0, 1)),
            knowledge_base_name TEXT NOT NULL,
            knowledge_base_id TEXT NOT NULL,
            cleaning_config TEXT,
            failure_reason TEXT,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            complete_time TIMESTAMP,
            progress INTEGER DEFAULT 0 NOT NULL CHECK (progress BETWEEN 0 AND 100),
            total_links INTEGER DEFAULT 0 NOT NULL,
            success_count INTEGER DEFAULT 0 NOT NULL,
            error_count INTEGER DEFAULT 0 NOT NULL
        )
        """

        create_links_sql = """
        CREATE TABLE IF NOT EXISTS collected_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_template TEXT NOT NULL,
            url TEXT NOT NULL,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
        """

        # 创建索引
        create_index_sql = """
        CREATE INDEX IF NOT EXISTS idx_collection_task_template
        ON collection_task(collection_template)
        """

        create_index_sql2 = """
        CREATE INDEX IF NOT EXISTS idx_collection_task_status
        ON collection_task(task_status)
        """

        create_index_sql3 = """
        CREATE INDEX IF NOT EXISTS idx_collected_links_template
        ON collected_links(collection_template)
        """

        await self.execute_update(create_task_sql)
        await self.execute_update(create_links_sql)
        await self.execute_update(create_index_sql)
        await self.execute_update(create_index_sql2)
        await self.execute_update(create_index_sql3)
        logger.info("数据库表创建完成")

    async def disconnect(self):
        """断开数据库连接"""
        logger.info("SQLite 数据库连接管理器已断开")

    async def execute_query(
        self, sql: str, params: tuple = None
    ) -> List[Dict[str, Any]]:
        """
        执行查询SQL语句

        Args:
            sql: SQL查询语句
            params: SQL参数

        Returns:
            查询结果列表
        """
        if self.log_sql:
            logger.info(f"执行查询SQL: {sql}")
            logger.info(f"查询参数: {params or '无'}")

        try:
            async with self.pool.get_connection() as conn:
                result = await self._async_execute_query(conn, sql, params)
                return result
        except Exception as e:
            logger.error(f"执行查询SQL失败: {sql}, 错误: {str(e)}")
            raise

    async def _async_execute_query(
        self, conn, sql: str, params: tuple = None
    ) -> List[Dict[str, Any]]:
        """异步执行查询（使用连接池）"""
        loop = asyncio.get_event_loop()

        def _execute():
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or ())
                columns = [desc[0] for desc in cursor.description]
                result = []
                for row in cursor.fetchall():
                    row_dict = {}
                    for i, col in enumerate(columns):
                        # SQLite 列名统一用小写，兼容应用层代码
                        row_dict[col.lower()] = row[i]
                    result.append(row_dict)
                return result
            finally:
                cursor.close()

        return await loop.run_in_executor(None, _execute)

    async def execute_update(self, sql: str, params: tuple = None) -> int:
        """
        执行更新SQL语句（INSERT, UPDATE, DELETE）

        Args:
            sql: SQL更新语句
            params: SQL参数

        Returns:
            受影响的行数
        """
        if self.log_sql:
            logger.info(f"执行更新SQL: {sql}")
            logger.info(f"更新参数: {params or '无'}")

        try:
            async with self.pool.get_connection() as conn:
                result = await self._async_execute_update(conn, sql, params)
                return result
        except Exception as e:
            logger.error(f"执行更新SQL失败: {sql}, 错误: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def _async_execute_update(self, conn, sql: str, params: tuple = None) -> int:
        """异步执行更新（使用连接池）"""
        loop = asyncio.get_event_loop()

        def _execute():
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or ())
                conn.commit()
                return cursor.rowcount
            except Exception as e:
                conn.rollback()
                raise
            finally:
                cursor.close()

        return await loop.run_in_executor(None, _execute)

    async def save_task(self, task_data: Dict[str, Any]) -> bool:
        """
        保存任务信息到数据库

        Args:
            task_data: 任务信息字典

        Returns:
            是否保存成功
        """
        try:
            sql = """
            INSERT INTO collection_task (
                task_id, task_name, task_status, collection_template, 
                task_type, knowledge_base_name, knowledge_base_id, cleaning_config,
                failure_reason, create_time, complete_time, progress, total_links, 
                success_count, error_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            cleaning_config = task_data.get(
                "cleaning_config", {"source": 1, "image_source": 1, "author": 1}
            )
            if isinstance(cleaning_config, dict):
                import json
                cleaning_config_str = json.dumps(cleaning_config)
            else:
                cleaning_config_str = str(cleaning_config)

            params = (
                task_data.get("task_id"),
                task_data.get("task_name"),
                task_data.get("task_status", task_data.get("status", "pending")),
                task_data.get("collection_template", task_data.get("target")),
                int(task_data.get("task_type", task_data.get("is_incremental", 0))),
                task_data.get("knowledge_base_name", ""),
                task_data.get("knowledge_base_id", ""),
                cleaning_config_str,
                task_data.get("failure_reason"),
                task_data.get("create_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                task_data.get("complete_time"),
                int(task_data.get("progress", 0)),
                int(task_data.get("total_links", 0)),
                int(task_data.get("success_count", 0)),
                int(task_data.get("error_count", 0)),
            )

            await self.execute_update(sql, params)
            logger.info(f"任务信息已保存到数据库: {task_data.get('task_id')}")
            return True
        except Exception as e:
            logger.error(f"保存任务信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def update_task(self, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        更新任务信息到数据库

        Args:
            task_id: 任务ID
            task_data: 任务信息字典

        Returns:
            是否更新成功
        """
        try:
            sql = """
            UPDATE collection_task SET
                task_name = ?,
                task_status = ?,
                collection_template = ?,
                task_type = ?,
                knowledge_base_name = ?,
                knowledge_base_id = ?, 
                cleaning_config = ?,
                failure_reason = ?,
                complete_time = ?,
                progress = ?,
                total_links = ?,
                success_count = ?,
                error_count = ?
            WHERE task_id = ?
            """

            cleaning_config = task_data.get(
                "cleaning_config", {"source": 1, "image_source": 1, "author": 1}
            )
            if isinstance(cleaning_config, dict):
                import json
                cleaning_config_str = json.dumps(cleaning_config)
            else:
                cleaning_config_str = str(cleaning_config)

            # 处理时间字段：确保是字符串格式
            complete_time = task_data.get("complete_time")
            if complete_time and hasattr(complete_time, "strftime"):
                complete_time = complete_time.strftime("%Y-%m-%d %H:%M:%S")

            params = (
                task_data.get("task_name"),
                task_data.get("task_status", task_data.get("status", "pending")),
                task_data.get("collection_template", task_data.get("target")),
                int(task_data.get("task_type", task_data.get("is_incremental", 0))),
                task_data.get("knowledge_base_name", ""),
                task_data.get("knowledge_base_id", ""),
                cleaning_config_str,
                task_data.get("failure_reason"),
                complete_time,
                int(task_data.get("progress", 0)),
                int(task_data.get("total_links", 0)),
                int(task_data.get("success_count", 0)),
                int(task_data.get("error_count", 0)),
                task_id,
            )

            rows_affected = await self.execute_update(sql, params)
            if rows_affected > 0:
                return True
            else:
                logger.warning(f"未找到要更新的任务: {task_id}")
                return False
        except Exception as e:
            logger.error(f"更新任务信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        从数据库获取任务信息

        Args:
            task_id: 任务ID

        Returns:
            任务信息字典，如果不存在则返回None
        """
        try:
            sql = "SELECT * FROM collection_task WHERE task_id = ?"
            results = await self.execute_query(sql, (task_id,))

            if results:
                return self._map_db_task_to_app(results[0])
            return None
        except Exception as e:
            logger.error(f"获取任务信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _map_db_task_to_app(self, db_task: Dict[str, Any]) -> Dict[str, Any]:
        """将数据库任务记录映射为应用层任务对象"""
        # SQLite 列名已统一为小写，直接取值即可
        create_time = db_task.get("create_time")
        complete_time = db_task.get("complete_time")

        # 确保任务类型为整数
        task_type = int(db_task.get("task_type", 0))

        # 处理清洗配置
        cleaning_config = db_task.get(
            "cleaning_config", '{"source": 1, "image_source": 1, "author": 1}'
        )
        if isinstance(cleaning_config, str):
            try:
                import json
                cleaning_config = json.loads(cleaning_config)
            except (json.JSONDecodeError, TypeError):
                cleaning_config = {"source": 1, "image_source": 1, "author": 1}

        # 处理时间字段格式化
        if create_time and not isinstance(create_time, str):
            create_time = create_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(create_time, "strftime") else str(create_time)
        if complete_time and not isinstance(complete_time, str):
            complete_time = complete_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(complete_time, "strftime") else str(complete_time)

        return {
            "task_id": db_task.get("task_id"),
            "task_name": db_task.get("task_name"),
            "task_status": db_task.get("task_status"),
            "collection_template": db_task.get("collection_template"),
            "task_type": task_type,
            "is_incremental": task_type == 1,
            "knowledge_base_name": db_task.get("knowledge_base_name", ""),
            "knowledge_base_id": db_task.get("knowledge_base_id", ""),
            "cleaning_config": cleaning_config,
            "failure_reason": db_task.get("failure_reason"),
            "create_time": create_time,
            "complete_time": complete_time,
            "progress": int(db_task.get("progress", 0)),
            "total_links": int(db_task.get("total_links", 0)),
            "success_count": int(db_task.get("success_count", 0)),
            "error_count": int(db_task.get("error_count", 0)),
        }

    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        """
        从数据库获取所有任务信息

        Returns:
            所有任务信息列表
        """
        try:
            sql = "SELECT * FROM collection_task ORDER BY create_time DESC"
            results = await self.execute_query(sql)
            return [self._map_db_task_to_app(db_task) for db_task in results]
        except Exception as e:
            logger.error(f"获取所有任务信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    async def get_tasks_with_pagination(
        self,
        page: int = 1,
        page_size: int = 10,
        query_conditions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        分页获取任务信息，支持条件查询

        Args:
            page: 页码，从1开始
            page_size: 每页大小，默认10条
            query_conditions: 查询条件字典

        Returns:
            包含分页信息和任务列表的字典
        """
        try:
            if not await self.is_connected():
                await self.connect()

            if query_conditions is None:
                query_conditions = {}

            offset = (page - 1) * page_size

            where_conditions = []
            count_where_conditions = []
            params = []
            count_params = []

            # 模糊匹配条件
            if query_conditions.get("task_id_like"):
                where_conditions.append("task_id LIKE ?")
                count_where_conditions.append("task_id LIKE ?")
                params.append(f"%{query_conditions['task_id_like']}%")
                count_params.append(f"%{query_conditions['task_id_like']}%")

            if query_conditions.get("task_name_like"):
                where_conditions.append("task_name LIKE ?")
                count_where_conditions.append("task_name LIKE ?")
                params.append(f"%{query_conditions['task_name_like']}%")
                count_params.append(f"%{query_conditions['task_name_like']}%")

            # 时间段查询条件
            if query_conditions.get("start_time"):
                where_conditions.append("complete_time >= ?")
                count_where_conditions.append("complete_time >= ?")
                params.append(query_conditions["start_time"])
                count_params.append(query_conditions["start_time"])

            if query_conditions.get("end_time"):
                where_conditions.append("complete_time <= ?")
                count_where_conditions.append("complete_time <= ?")
                params.append(query_conditions["end_time"])
                count_params.append(query_conditions["end_time"])

            # 等值匹配条件
            if query_conditions.get("collection_template"):
                where_conditions.append("collection_template = ?")
                count_where_conditions.append("collection_template = ?")
                params.append(query_conditions["collection_template"])
                count_params.append(query_conditions["collection_template"])

            if query_conditions.get("task_type") is not None:
                where_conditions.append("task_type = ?")
                count_where_conditions.append("task_type = ?")
                params.append(query_conditions["task_type"])
                count_params.append(query_conditions["task_type"])

            if query_conditions.get("task_status"):
                where_conditions.append("task_status = ?")
                count_where_conditions.append("task_status = ?")
                params.append(query_conditions["task_status"])
                count_params.append(query_conditions["task_status"])

            if query_conditions.get("knowledge_base_name"):
                where_conditions.append("knowledge_base_name = ?")
                count_where_conditions.append("knowledge_base_name = ?")
                params.append(query_conditions["knowledge_base_name"])
                count_params.append(query_conditions["knowledge_base_name"])

            where_clause = (
                " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            )
            count_where_clause = (
                " WHERE " + " AND ".join(count_where_conditions)
                if count_where_conditions
                else ""
            )

            # 获取总数
            count_sql = f"SELECT COUNT(*) as total FROM collection_task{count_where_clause}"
            count_result = await self.execute_query(
                count_sql, tuple(count_params) if count_params else None
            )
            total = count_result[0].get("total", 0) if count_result else 0

            # 获取分页数据
            sql = f"SELECT * FROM collection_task{where_clause} ORDER BY create_time DESC LIMIT ? OFFSET ?"
            final_params = (
                tuple(params + [page_size, offset]) if params else (page_size, offset)
            )
            results = await self.execute_query(sql, final_params)

            tasks = [self._map_db_task_to_app(db_task) for db_task in results]
            total_pages = (total + page_size - 1) // page_size

            return {
                "tasks": tasks,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                },
            }
        except Exception as e:
            logger.error(f"分页获取任务信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "tasks": [],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
            }

    async def is_connected(self) -> bool:
        """检查数据库是否已连接"""
        if not self.pool or self.pool._closed:
            return False
        try:
            async with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return True
        except Exception:
            return False

    async def save_latest_link(self, collection_template: str, url: str) -> bool:
        """
        保存最新链接到数据库

        Args:
            collection_template: 采集模板名称
            url: 最新链接URL

        Returns:
            是否保存成功
        """
        try:
            existing_sql = "SELECT COUNT(*) as count FROM collected_links WHERE collection_template = ?"
            result = await self.execute_query(existing_sql, (collection_template,))

            count = result[0].get("count", 0) if result else 0

            if count > 0:
                update_sql = "UPDATE collected_links SET url = ?, create_time = CURRENT_TIMESTAMP WHERE collection_template = ?"
                await self.execute_update(update_sql, (url, collection_template))
                logger.info(f"已更新最新链接: {collection_template} -> {url}")
            else:
                insert_sql = "INSERT INTO collected_links (collection_template, url, create_time) VALUES (?, ?, CURRENT_TIMESTAMP)"
                await self.execute_update(insert_sql, (collection_template, url))
                logger.info(f"已插入最新链接: {collection_template} -> {url}")

            return True
        except Exception as e:
            logger.error(f"保存最新链接失败: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def get_latest_link(self, collection_template: str) -> Optional[str]:
        """
        获取指定模板的最新链接

        Args:
            collection_template: 采集模板名称

        Returns:
            最新链接URL，如果不存在则返回None
        """
        try:
            sql = "SELECT url FROM collected_links WHERE collection_template = ? ORDER BY create_time DESC LIMIT 1"
            results = await self.execute_query(sql, (collection_template,))

            if results:
                return results[0].get("url")
            return None
        except Exception as e:
            logger.error(f"获取最新链接失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    async def get_latest_task_by_template(
        self, collection_template: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取指定模板的最新任务

        Args:
            collection_template: 采集模板名称

        Returns:
            最新任务信息，如果不存在则返回None
        """
        try:
            sql = """SELECT * FROM collection_task 
                     WHERE collection_template = ? 
                     ORDER BY create_time DESC 
                     LIMIT 1"""
            results = await self.execute_query(sql, (collection_template,))

            if results:
                return self._map_db_task_to_app(results[0])
            return None
        except Exception as e:
            logger.error(f"获取最新任务失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None


# 全局数据库管理器实例
db_manager = None
_manager_lock = threading.Lock()


def get_db_manager(
    host: str = "localhost",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
    log_sql: bool = False,
    pool_size: Optional[int] = None,
) -> DatabaseManager:
    """
    获取全局数据库管理器实例（单例模式）

    Args:
        host: 未使用（兼容旧接口）
        port: 未使用（兼容旧接口）
        user: 未使用（兼容旧接口）
        password: 未使用（兼容旧接口）
        database: SQLite 数据库文件路径
        log_sql: 是否记录SQL日志
        pool_size: 连接池大小

    Returns:
        数据库管理器实例
    """
    global db_manager

    with _manager_lock:
        if db_manager is None:
            db_manager = DatabaseManager(
                host, port, user, password, database, log_sql, pool_size
            )
        return db_manager


def close_connection_pool():
    """关闭全局连接池"""
    global db_manager

    with _manager_lock:
        if db_manager and db_manager.pool:
            db_manager.pool.close()
            db_manager = None
            logger.info("全局 SQLite 连接池已关闭")
