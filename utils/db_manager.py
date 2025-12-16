"""
达梦数据库操作模块
用于管理任务数据的持久化存储
"""

import asyncio
import traceback
from datetime import datetime
from typing import Optional, Dict, List, Any
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


class DatabaseManager:
    """达梦数据库管理器"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5236,
        user: str = "",
        password: str = "",
        database: str = "",
        log_sql: bool = False,
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
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.log_sql = log_sql
        self.connection = None
        self._connected = False

    async def connect(self):
        """连接到达梦数据库"""
        if not DM_DRIVER_AVAILABLE:
            raise ImportError("dmPython驱动未安装，请安装达梦数据库Python驱动")

        if self._connected:
            return

        try:
            # 使用异步线程池执行阻塞的数据库连接操作
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_connect)
            self._connected = True
            logger.info(
                f"成功连接到达梦数据库: {self.host}:{self.port}/{self.database}"
            )
        except Exception as e:
            logger.error(f"连接达梦数据库失败: {str(e)}")
            raise

    def _sync_connect(self):
        """同步连接数据库（在线程池中执行）"""
        try:
            # 检查所有连接参数是否有效
            logger.info(
                f"尝试连接达梦数据库: host={self.host}, port={self.port}, user={self.user}, database={self.database}"
            )

            # 尝试多种连接方式来增加兼容性
            connection_established = False
            last_exception = None

            # 方式1: 标准参数连接，但不指定数据库
            try:
                self.connection = dmPython.connect(
                    user=self.user,
                    password=self.password,
                    server=self.host,
                    port=self.port,
                )
                connection_established = True
                # logger.info("使用标准参数成功连接到达梦数据库（未指定数据库）")
            except Exception as e:
                last_exception = e
                logger.warning(f"标准连接方式(未指定数据库)失败: {str(e)}")

            # 方式2: 标准参数连接，指定数据库
            if not connection_established:
                try:
                    self.connection = dmPython.connect(
                        user=self.user,
                        password=self.password,
                        server=self.host,
                        port=self.port,
                        database=self.database,
                    )
                    connection_established = True
                    logger.info("使用标准参数成功连接到达梦数据库（指定数据库）")
                except Exception as e:
                    last_exception = e
                    logger.warning(f"标准连接方式(指定数据库)失败: {str(e)}")

            # 方式3: 使用DSN字符串（不指定数据库）
            if not connection_established:
                try:
                    dsn = f"dm://{self.user}:{self.password}@{self.host}:{self.port}"
                    self.connection = dmPython.connect(dsn)
                    connection_established = True
                    logger.info("使用DSN方式成功连接到达梦数据库（未指定数据库）")
                except Exception as e:
                    last_exception = e
                    logger.warning(f"DSN连接方式(未指定数据库)失败: {str(e)}")

            # 方式4: 使用DSN字符串（指定数据库）
            if not connection_established:
                try:
                    dsn = f"dm://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
                    self.connection = dmPython.connect(dsn)
                    connection_established = True
                    logger.info("使用DSN方式成功连接到达梦数据库（指定数据库）")
                except Exception as e:
                    last_exception = e
                    logger.warning(f"DSN连接方式(指定数据库)失败: {str(e)}")

            # 方式5: 尝试使用host参数而不是server
            if not connection_established:
                try:
                    self.connection = dmPython.connect(
                        user=self.user,
                        password=self.password,
                        host=self.host,  # 使用host而不是server
                        port=self.port,
                    )
                    connection_established = True
                    logger.info("使用host参数成功连接到达梦数据库")
                except Exception as e:
                    last_exception = e
                    logger.warning(f"使用host参数连接失败: {str(e)}")

            # 方式6: 如果host是localhost，尝试使用127.0.0.1
            if not connection_established and self.host == "localhost":
                try:
                    self.connection = dmPython.connect(
                        user=self.user,
                        password=self.password,
                        server="127.0.0.1",
                        port=self.port,
                    )
                    connection_established = True
                    logger.info("使用127.0.0.1成功连接到达梦数据库")
                except Exception as e:
                    last_exception = e
                    logger.warning(f"使用127.0.0.1连接失败: {str(e)}")

            # 如果所有方式都失败了，抛出最后一个异常
            if not connection_established:
                logger.error(f"所有连接方式都失败了")
                logger.error(f"最后一个错误: {str(last_exception)}")
                raise last_exception

            # 测试连接是否有效
            if self.connection:
                cursor = self.connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                # logger.info("数据库连接验证成功")

        except ImportError as e:
            logger.error(f"dmPython驱动导入失败: {str(e)}")
            logger.error("请确保已正确安装达梦数据库Python驱动: pip install dmPython")
            raise
        except Exception as e:
            logger.error(f"同步连接数据库失败: {str(e)}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error("请检查以下配置是否正确:")
            logger.error(f"  - 主机地址: {self.host}")
            logger.error(f"  - 端口: {self.port}")
            logger.error(f"  - 用户名: {self.user}")
            logger.error(f"  - 数据库名: {self.database}")
            logger.error("请确保达梦数据库服务正在运行，且连接参数正确")
            raise

    async def disconnect(self):
        """断开数据库连接"""
        if self.connection:
            try:
                # 使用异步线程池执行阻塞的数据库关闭操作
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.connection.close)
                self._connected = False
                logger.info("已断开达梦数据库连接")
            except Exception as e:
                logger.error(f"断开数据库连接失败: {str(e)}")
                pass

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
        if not self._connected:
            await self.connect()

        # 根据配置决定是否打印SQL语句
        if self.log_sql:
            logger.info(f"执行查询SQL: {sql}")
            if params:
                logger.info(f"查询参数: {params}")
            else:
                logger.info("查询参数: 无")

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._sync_execute_query, sql, params
            )
            logger.info(f"查询完成，返回 {len(result)} 条记录")
            return result
        except Exception as e:
            logger.error(f"执行查询SQL失败: {sql}, 错误: {str(e)}")
            raise

    def _sync_execute_query(
        self, sql: str, params: tuple = None
    ) -> List[Dict[str, Any]]:
        """同步执行查询（在线程池中执行）"""
        cursor = self.connection.cursor()
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

    async def execute_update(self, sql: str, params: tuple = None) -> int:
        """
        执行更新SQL语句（INSERT, UPDATE, DELETE）

        Args:
            sql: SQL更新语句
            params: SQL参数

        Returns:
            受影响的行数
        """
        if not self._connected:
            await self.connect()

        # 根据配置决定是否打印SQL语句
        if self.log_sql:
            logger.info(f"执行更新SQL: {sql}")
            if params:
                logger.info(f"更新参数: {params}")
            else:
                logger.info("更新参数: 无")

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._sync_execute_update, sql, params
            )
            # logger.info(f"更新完成，影响 {result} 行")
            return result
        except Exception as e:
            logger.error(f"执行更新SQL失败: {sql}, 错误: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def _sync_execute_update(self, sql: str, params: tuple = None) -> int:
        """同步执行更新（在线程池中执行）"""
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params or ())
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

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
                task_type, knowledge_base_name, failure_reason, 
                create_time, complete_time, progress, total_links, 
                success_count, error_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

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
                    1 if task_data.get("is_incremental") else 0
                ),  # 0-全量, 1-增量，转换为整数
                task_data.get("knowledge_base_name", ""),  # 知识库名称
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
                failure_reason = ?,
                complete_time = ?,
                progress = ?,
                total_links = ?,
                success_count = ?,
                error_count = ?
            WHERE task_id = ?
            """

            # 准备参数
            params = (
                task_data.get("task_name"),
                task_data.get("task_status", task_data.get("status", "pending")),
                task_data.get("collection_template", task_data.get("target")),
                1 if task_data.get("is_incremental") else 0,  # 转换为整数
                task_data.get("knowledge_base_name", ""),
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

        return {
            "task_id": db_task.get("task_id") or db_task.get("TASK_ID"),
            "task_name": db_task.get("task_name") or db_task.get("TASK_NAME"),
            "task_status": db_task.get("task_status") or db_task.get("TASK_STATUS"),
            "collection_template": db_task.get("collection_template")
            or db_task.get("COLLECTION_TEMPLATE"),
            "is_incremental": task_type == 1,  # 1-增量采集, 0-全量采集
            "knowledge_base_name": db_task.get("knowledge_base_name")
            or db_task.get("KNOWLEDGE_BASE_NAME"),
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
        self, page: int = 1, page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页获取任务信息

        Args:
            page: 页码，从1开始
            page_size: 每页大小，默认10条

        Returns:
            包含分页信息和任务列表的字典
        """
        try:
            if not self._connected:
                await self.connect()

            # 计算偏移量
            offset = (page - 1) * page_size

            # 获取总数
            count_sql = "SELECT COUNT(*) as total FROM collection_task"
            count_result = await self.execute_query(count_sql)

            total = count_result[0].get("total", 0) if count_result else 0

            # 获取分页数据
            sql = "SELECT * FROM collection_task ORDER BY create_time DESC LIMIT ? OFFSET ?"
            results = await self.execute_query(sql, (page_size, offset))

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

            logger.info(
                f"分页查询结果: 返回 {len(tasks)} 条任务, 总数: {total}, 总页数: {total_pages}"
            )
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
        return self._connected and self.connection is not None

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
                logger.info(f"从数据库获取到最新链接: {collection_template} -> {url}")
                return url
            return None
        except Exception as e:
            logger.error(f"获取最新链接失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None


# 全局数据库管理器实例
db_manager = None


def get_db_manager(
    host: str = "localhost",
    port: int = 5236,
    user: str = "",
    password: str = "",
    database: str = "",
    log_sql: bool = False,
) -> DatabaseManager:
    """
    获取全局数据库管理器实例

    Args:
        host: 数据库主机地址
        port: 数据库端口
        user: 用户名
        password: 密码
        database: 数据库名称
        log_sql: 是否记录SQL日志

    Returns:
        数据库管理器实例
    """
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager(host, port, user, password, database, log_sql)
    return db_manager
