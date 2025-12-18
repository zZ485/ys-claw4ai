import os
import requests
import aiofiles
import aiohttp
from typing import Optional, Dict, Any
from config.logger_config import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


async def upload_document_to_knowledge_base(
    file_path: str,
    dataset_id: str,
    api_base_url: str = "http://192.168.9.47:8000",
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    上传文档到知识库

    Args:
        file_path: 要上传的文件路径
        dataset_id: 数据集ID (知识库名称)
        api_base_url: 知识库API基础URL
        timeout: 上传超时时间(秒)

    Returns:
        Dict: 上传结果，包含success状态和message或error信息
    """
    if not os.path.exists(file_path):
        error_msg = f"文件不存在: {file_path}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

    # 构建上传URL
    upload_url = f"{api_base_url.rstrip('/')}/api/v1/datasets/{dataset_id}/documents"

    try:
        # 使用aiohttp进行异步文件上传
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            data = aiohttp.FormData()

            # 异步读取文件并添加到表单数据
            async with aiofiles.open(file_path, "rb") as f:
                file_content = await f.read()
                # 获取文件名
                file_name = os.path.basename(file_path)
                # 添加文件到表单，使用files字段名
                data.add_field(
                    "files", file_content, filename=file_name, content_type="text/plain"
                )

            logger.info(f"开始上传文件 {file_name} 到数据集 {dataset_id}")

            # 发送POST请求
            async with session.post(upload_url, data=data) as response:
                response_text = await response.text()

                if response.status == 200:
                    logger.info(f"文件 {file_name} 上传成功")
                    return {
                        "success": True,
                        "message": f"文件 {file_name} 上传成功",
                        "response": response_text,
                    }
                else:
                    error_msg = (
                        f"上传失败，状态码: {response.status}, 响应: {response_text}"
                    )
                    logger.error(error_msg)
                    return {"success": False, "error": error_msg}

    except aiohttp.ClientError as e:
        error_msg = f"网络请求错误: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"上传过程中发生异常: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}


async def check_knowledge_base_connection(
    api_base_url: str = "http://192.168.9.47:8000",
) -> Dict[str, Any]:
    """
    检查知识库API连接状态

    Args:
        api_base_url: 知识库API基础URL

    Returns:
        Dict: 连接状态检查结果
    """
    try:
        # 使用aiohttp进行异步请求
        async with aiohttp.ClientSession() as session:
            # 尝试访问API根路径或健康检查端点
            health_url = f"{api_base_url.rstrip('/')}/health"

            async with session.get(health_url) as response:
                if response.status == 200:
                    return {"success": True, "message": "知识库API连接正常"}
                else:
                    return {
                        "success": False,
                        "error": f"API响应异常，状态码: {response.status}",
                    }

    except aiohttp.ClientError as e:
        error_msg = f"连接知识库API失败: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"检查连接状态时发生异常: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
