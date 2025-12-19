"""
达梦数据库操作模块
用于管理任务数据的持久化存储
实现了连接池机制，连接健康检查和自动重连功能
"""

import asyncio
import traceback
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Union
from contextlib import asynccontextmanager
from queue import Queue, Empty
from config.logger_config import LoggerConfig

# 获取日志记录器
logger = LoggerConfig.get_logger(__name__)

try:
    import dmPython

    # 尝试获取版本信息，dmPython可能没有__version__属性
    version = getattr(dmPython, "__version__", "未知版本")
    logger.info(f"已加载达梦数据库Python驱动，版本: {version}")
    DM_DRIVER_AVAILABLE = True
except ImportError:
    DM_DRIVER_AVAILABLE = False
    logger.warning(
        "dmPython驱动未安装，请安装达梦数据库Python驱动: pip install dmPython"
    )


async def init_database_connection_pool(
    host: str = "localhost",
    port: int = 5236,
    user: str = "",
    password: str = "",
    database: str = "",
    log_sql: bool = False,
    pool_size: Optional[int] = None,
):
    """
    初始化全局数据库连接池

    Args:
        host: 数据库主机地址
        port: 数据库端口
        user: 用户名
        password: 密码
        database: 数据库名称
        log_sql: 是否记录SQL日志
        pool_size: 连接池大小，默认None表示使用默认值
    """
    try:
        manager = get_db_manager(
            host, port, user, password, database, log_sql, pool_size
        )
        await manager.connect()  # 这会初始化连接池
        logger.info(f"数据库连接池初始化成功: {host}:{port}/{database}")
        return True
    except Exception as e:
        logger.error(f"数据库连接池初始化失败: {str(e)}")
        return False


async def cleanup_database_resources():
    """清理数据库资源"""
    close_connection_pool()
    logger.info("数据库资源清理完成")


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
        except:
            self.is_valid = False
            return False

    def close(self):
        """关闭连接"""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
            self.is_valid = False


class ConnectionPool:
    """数据库连接池"""

    def __init__(
        self,
        min_connections=2,
        max_connections=10,
        connection_timeout=30,
        max_lifetime=3600,
        health_check_interval=300,
    ):
        """
        初始化连接池

        Args:
            min_connections: 最小连接数
            max_connections: 最大连接数
            connection_timeout: 连接超时时间(秒)
            max_lifetime: 连接最大存活时间(秒)
            health_check_interval: 健康检查间隔(秒)
        """
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

        # 连接参数
        self.host = None
        self.port = None
        self.user = None
        self.password = None
        self.database = None

        # 健康检查线程
        self._health_check_thread = None

    def configure(self, host, port, user, password, database):
        """配置数据库连接参数"""
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def _create_connection(self):
        """创建新连接"""
        try:
            # 尝试使用最简单的连接方式
            connection = dmPython.connect(
                user=self.user,
                password=self.password,
                server=self.host,
                port=self.port,
            )
            return DatabaseConnection(connection, self)
        except Exception as e:
            logger.error(f"创建数据库连接失败: {str(e)}")
            raise

    def _initialize_pool(self):
        """初始化连接池，创建最小连接数"""
        if not self.host or not self.user:
            raise ValueError("数据库连接参数未配置")

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
        logger.info(f"数据库连接池已启动，初始连接数: {self.min_connections}")

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
                time.sleep(30)  # 出错后等待30秒再重试

    def _perform_health_check(self):
        """执行健康检查"""
        with self._lock:
            # 检查所有连接的健康状态
            for conn in list(self._all_connections):
                if not conn.in_use and not conn.is_healthy():
                    logger.warning("发现不健康的连接，将其移除")
                    self._remove_connection(conn)

            # 确保连接数不低于最小值
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

    @asynccontextmanager
    async def get_connection(self):
        """获取数据库连接"""
        if self._closed:
            raise RuntimeError("连接池已关闭")

        conn = None
        try:
            # 尝试从池中获取连接
            try:
                conn = self._pool.get(timeout=self.connection_timeout)
            except Empty:
                # 如果池为空，尝试创建新连接
                if self._connection_count < self.max_connections:
                    with self._lock:
                        if self._connection_count < self.max_connections:
                            conn = self._create_connection()
                            self._all_connections.append(conn)
                            self._connection_count += 1

                # 如果还是没有连接，等待一段时间再试
                if not conn:
                    logger.warning("连接池已满，等待可用连接")
                    conn = self._pool.get(timeout=self.connection_timeout)

            # 检查连接是否有效，如果无效则创建新连接
            if conn and (conn.is_expired(self.max_lifetime) or not conn.is_healthy()):
                self._remove_connection(conn)
                with self._lock:
                    if self._connection_count < self.max_connections:
                        conn = self._create_connection()
                        self._all_connections.append(conn)
                        self._connection_count += 1
                    else:
                        # 连接池已满，等待一个可用连接
                        conn = self._pool.get(timeout=self.connection_timeout)

            conn.in_use = True
            conn.update_last_used()

            yield conn.connection

        except Exception as e:
            logger.error(f"获取或使用连接失败: {str(e)}")
            if conn:
                conn.is_valid = False
            raise
        finally:
            if conn:
                conn.in_use = False
                try:
                    self._pool.put(conn, timeout=5)
                except:
                    # 如果无法放回池中，可能池已关闭
                    logger.warning("无法将连接放回池中，可能池已关闭")

    def close(self):
        """关闭连接池"""
        self._closed = True

        # 关闭所有连接
        for conn in self._all_connections:
            conn.close()

        self._all_connections.clear()
        self._connection_count = 0

        # 清空队列
        while not self._pool.empty():
            try:
                self._pool.get_nowait()
            except Empty:
                break

        logger.info("数据库连接池已关闭")

    async def disconnect(self):
        """断开数据库连接（异步版本）"""
        self.close()


class DatabaseManager:
    """达梦数据库管理器"""

    _pool = None
    _pool_lock = threading.Lock()

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5236,
        user: str = "",
        password: str = "",
        database: str = "",
        log_sql: bool = False,
        pool_size: Optional[int] = None,
    ):
        """
        初始化数据库连接参数

        Args:
            host: 数据库主机地址
            port: 数据库端口
            user: 用户名
            password: 密码
            database: 数据库名称
            log_sql: 是否记录SQL日志
            pool_size: 连接池大小，默认None表示使用默认值
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.log_sql = log_sql

        # 初始化连接池
        self._init_pool(pool_size)

    def _init_pool(self, pool_size):
        """初始化连接池"""
        with DatabaseManager._pool_lock:
            if DatabaseManager._pool is None:
                # 根据传入参数设置连接池大小
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
                DatabaseManager._pool.configure(
                    self.host, self.port, self.user, self.password, self.database
                )
                DatabaseManager._pool.start()

    @property
    def pool(self):
        """获取连接池"""
        return DatabaseManager._pool

    async def connect(self):
        """连接到达梦数据库（兼容旧版本接口）"""
        # 连接池已在初始化时启动，这里不需要做任何操作
        if not DM_DRIVER_AVAILABLE:
            raise ImportError("dmPython驱动未安装，请安装达梦数据库Python驱动")

        # 检查连接池是否可用
        if not self.pool or self.pool._closed:
            logger.warning("连接池不可用，尝试重新初始化")
            self._init_pool(None)

        logger.info(
            f"数据库连接池已就绪，准备执行操作: {self.host}:{self.port}/{self.database}"
        )
        return True

    async def disconnect(self):
        """断开数据库连接"""
        # 这里我们不做任何操作，因为连接池是全局共享的
        # 连接池将在程序退出时关闭
        logger.info("数据库连接管理器已断开")

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
        if not DM_DRIVER_AVAILABLE:
            raise ImportError("dmPython驱动未安装，请安装达梦数据库Python驱动")

        # 根据配置决定是否打印SQL语句
        if self.log_sql:
            logger.info(f"执行查询SQL: {sql}")
            if params:
                logger.info(f"查询参数: {params}")
            else:
                logger.info("查询参数: 无")

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
                    # 处理达梦返回的字段名大小写问题
                    row_dict = {}
                    for i, col in enumerate(columns):
                        # 优先使用小写字段名，兼容应用层代码
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
        if not DM_DRIVER_AVAILABLE:
            raise ImportError("dmPython驱动未安装，请安装达梦数据库Python驱动")

        # 根据配置决定是否打印SQL语句
        if self.log_sql:
            logger.info(f"执行更新SQL: {sql}")
            if params:
                logger.info(f"更新参数: {params}")
            else:
                logger.info("更新参数: 无")

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

            # 将清洗配置字典转换为JSON字符串
            cleaning_config = task_data.get(
                "cleaning_config", {"source": 1, "image_source": 1, "author": 1}
            )
            if isinstance(cleaning_config, dict):
                import json

                cleaning_config_str = json.dumps(cleaning_config)
            else:
                cleaning_config_str = str(cleaning_config)

            # 准备参数，确保类型正确
            params = (
                task_data.get("task_id"),
                task_data.get("task_name"),
                task_data.get(
                    "task_status", task_data.get("status", "pending")
                ),  # 优先使用task_status，其次status，最后默认pending
                task_data.get(
                    "collection_template", task_data.get("target")
                ),  # 使用collection_template
                (
                    int(task_data.get("task_type", task_data.get("is_incremental", 0)))
                ),  # 0-全量, 1-增量，转换为整数，优先使用task_type
                task_data.get("knowledge_base_name", ""),  # 知识库名称
                task_data.get("knowledge_base_id", ""),  # 知识库ID，默认空字符串
                cleaning_config_str,  # 清洗配置JSON字符串
                task_data.get("failure_reason"),  # 失败原因
                task_data.get("create_time", datetime.now()),  # 创建时间
                task_data.get("complete_time"),  # 完成时间
                int(task_data.get("progress", 0)),  # 任务进度，确保是整数
                int(task_data.get("total_links", 0)),  # 总链接数
                int(task_data.get("success_count", 0)),  # 成功数量
                int(task_data.get("error_count", 0)),  # 失败数量
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

            # 将清洗配置字典转换为JSON字符串
            cleaning_config = task_data.get(
                "cleaning_config", {"source": 1, "image_source": 1, "author": 1}
            )
            if isinstance(cleaning_config, dict):
                import json

                cleaning_config_str = json.dumps(cleaning_config)
            else:
                cleaning_config_str = str(cleaning_config)

            # 准备参数
            params = (
                task_data.get("task_name"),
                task_data.get("task_status", task_data.get("status", "pending")),
                task_data.get("collection_template", task_data.get("target")),
                int(
                    task_data.get("task_type", task_data.get("is_incremental", 0))
                ),  # 转换为整数，优先使用task_type
                task_data.get("knowledge_base_name", ""),
                task_data.get("knowledge_base_id", ""),  # 知识库ID
                cleaning_config_str,  # 清洗配置JSON字符串
                task_data.get("failure_reason"),
                task_data.get("complete_time"),
                int(task_data.get("progress", 0)),
                int(task_data.get("total_links", 0)),
                int(task_data.get("success_count", 0)),
                int(task_data.get("error_count", 0)),
                task_id,
            )

            rows_affected = await self.execute_update(sql, params)
            if rows_affected > 0:
                # logger.info(f"任务信息已更新到数据库: {task_id}")
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
                # 将数据库字段映射到应用字段
                db_task = results[0]
                return self._map_db_task_to_app(db_task)
            return None
        except Exception as e:
            logger.error(f"获取任务信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _map_db_task_to_app(self, db_task: Dict[str, Any]) -> Dict[str, Any]:
        """将数据库任务记录映射为应用层任务对象"""
        # 处理时间字段格式化
        create_time = db_task.get("create_time") or db_task.get("CREATE_TIME")
        complete_time = db_task.get("complete_time") or db_task.get("COMPLETE_TIME")

        # 确保任务类型为整数
        task_type = int(db_task.get("task_type", db_task.get("TASK_TYPE", 0)))

        # 处理清洗配置，从JSON字符串转换为字典
        cleaning_config = db_task.get("cleaning_config") or db_task.get(
            "CLEANING_CONFIG", '{"source": 1, "image_source": 1, "author": 1}'
        )
        if isinstance(cleaning_config, str):
            try:
                import json

                cleaning_config = json.loads(cleaning_config)
            except (json.JSONDecodeError, TypeError):
                # 如果解析失败，使用默认配置
                cleaning_config = {"source": 1, "image_source": 1, "author": 1}

        return {
            "task_id": db_task.get("task_id") or db_task.get("TASK_ID"),
            "task_name": db_task.get("task_name") or db_task.get("TASK_NAME"),
            "task_status": db_task.get("task_status") or db_task.get("TASK_STATUS"),
            "collection_template": db_task.get("collection_template")
            or db_task.get("COLLECTION_TEMPLATE"),
            "task_type": task_type,  # 添加task_type字段
            "is_incremental": task_type == 1,  # 1-增量采集, 0-全量采集
            "knowledge_base_name": db_task.get("knowledge_base_name")
            or db_task.get("KNOWLEDGE_BASE_NAME"),
            "knowledge_base_id": db_task.get("knowledge_base_id")
            or db_task.get("KNOWLEDGE_BASE_ID", ""),  # 知识库ID
            "cleaning_config": cleaning_config,  # 清洗配置字典
            "failure_reason": db_task.get("failure_reason")
            or db_task.get("FAILURE_REASON"),
            "create_time": (
                create_time.strftime("%Y-%m-%d %H:%M:%S") if create_time else None
            ),
            "complete_time": (
                complete_time.strftime("%Y-%m-%d %H:%M:%S") if complete_time else None
            ),
            "progress": int(db_task.get("progress", db_task.get("PROGRESS", 0))),
            "total_links": int(
                db_task.get("total_links", db_task.get("TOTAL_LINKS", 0))
            ),
            "success_count": int(
                db_task.get("success_count", db_task.get("SUCCESS_COUNT", 0))
            ),
            "error_count": int(
                db_task.get("error_count", db_task.get("ERROR_COUNT", 0))
            ),
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

            tasks = []
            for db_task in results:
                tasks.append(self._map_db_task_to_app(db_task))

            return tasks
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
                - 模糊匹配字段: task_id_like, task_name_like
                - 时间段查询字段: start_time, end_time (格式: YYYY-MM-DD)
                - 等值匹配字段: collection_template, task_type, task_status, knowledge_base_name

        Returns:
            包含分页信息和任务列表的字典
        """
        try:
            if not await self.is_connected():
                await self.connect()

            # 如果没有提供查询条件，初始化为空字典
            if query_conditions is None:
                query_conditions = {}

            # 计算偏移量
            offset = (page - 1) * page_size

            # 构建WHERE条件和参数
            where_conditions = []
            count_where_conditions = []
            params = []
            count_params = []

            # 处理模糊匹配条件
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

            # 处理时间段查询条件
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

            # 处理等值匹配条件
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

            # 构建SQL语句
            where_clause = (
                " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            )
            count_where_clause = (
                " WHERE " + " AND ".join(count_where_conditions)
                if count_where_conditions
                else ""
            )

            # 获取总数
            count_sql = (
                f"SELECT COUNT(*) as total FROM collection_task{count_where_clause}"
            )
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

            # 计算总页数
            total_pages = (total + page_size - 1) // page_size  # 向上取整

            result = {
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

            # logger.info(
            #     f"分页查询结果: 返回 {len(tasks)} 条任务, 总数: {total}, 总页数: {total_pages}"
            # )
            return result
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

        # 尝试获取一个连接来检查是否可用
        try:
            async with self.pool.get_connection() as conn:
                # 简单执行一个查询来验证连接
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return True
        except:
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
            # 检查是否存在该模板的记录
            existing_sql = "SELECT COUNT(*) as count FROM collected_links WHERE collection_template = ?"
            result = await self.execute_query(existing_sql, (collection_template,))

            count = result[0].get("count", 0) if result else 0

            if count > 0:
                # 如果存在，则更新
                update_sql = "UPDATE collected_links SET url = ?, create_time = CURRENT_TIMESTAMP WHERE collection_template = ?"
                await self.execute_update(update_sql, (url, collection_template))
                logger.info(f"已更新最新链接: {collection_template} -> {url}")
            else:
                # 如果不存在，则插入
                insert_sql = """
                INSERT INTO collected_links (collection_template, url, create_time) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """
                await self.execute_update(insert_sql, (collection_template, url))
                logger.info(f"已插入最新链接: {collection_template} -> {url}")

            return True
        except Exception as e:
            logger.error(f"保存最新链接失败: {str(e)}")
            logger.error(traceback.format_exc())
            # 回退到兼容模式（如果达梦版本不支持CURRENT_TIMESTAMP）
            try:
                if "无效的列名[CREATE_TIME]" in str(e) or "列[CREATE_TIME]无效" in str(
                    e
                ):
                    logger.warning("回退到兼容模式保存最新链接")
                    if count > 0:
                        update_sql = "UPDATE collected_links SET url = ? WHERE collection_template = ?"
                        await self.execute_update(
                            update_sql, (url, collection_template)
                        )
                    else:
                        insert_sql = "INSERT INTO collected_links (collection_template, url) VALUES (?, ?)"
                        await self.execute_update(
                            insert_sql, (collection_template, url)
                        )
                    return True
            except Exception as fallback_e:
                logger.error(f"兼容模式保存最新链接也失败: {str(fallback_e)}")
                return False
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
                url = results[0].get("url")
                # logger.info(f"从数据库获取到最新链接: {collection_template} -> {url}")
                return url
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
    port: int = 5236,
    user: str = "",
    password: str = "",
    database: str = "",
    log_sql: bool = False,
    pool_size: Optional[int] = None,
) -> DatabaseManager:
    """
    获取全局数据库管理器实例（单例模式）

    Args:
        host: 数据库主机地址
        port: 数据库端口
        user: 用户名
        password: 密码
        database: 数据库名称
        log_sql: 是否记录SQL日志
        pool_size: 连接池大小，默认None表示使用默认值

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
            logger.info("全局数据库连接池已关闭")
