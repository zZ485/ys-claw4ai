import logging
import os
import json
from typing import Optional

# 获取配置文件路径
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logger_config.json")

def load_config():
    """
    从JSON配置文件中加载配置
    
    Returns:
        配置字典，如果加载失败则返回默认配置
    """
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            return config_data.get('logger_settings', {})
    except Exception as e:
        print(f"加载日志配置文件失败: {e}")
        return {
            "default_log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "default_log_level": "INFO",
            "crawler_settings": {
                "log_file": "crawler_api.log",
                "console_output": True,
                "log_level": "INFO"
            }
        }


class LoggerConfig:
    """日志配置类，提供统一的日志配置管理"""
    
    @classmethod
    def setup_basic_logger(
        cls, 
        log_file: Optional[str] = None,
        log_level: int = None,
        log_format: str = None,
        console_output: bool = True
    ) -> None:
        """
        设置基础日志配置
        
        Args:
            log_file: 日志文件路径，如果为None则不写入文件
            log_level: 日志级别
            log_format: 日志格式
            console_output: 是否输出到控制台
        """
        config = load_config()
        
        # 使用参数或默认值
        level = log_level or getattr(logging, config.get('default_log_level', 'INFO'))
        format_str = log_format or config.get('default_log_format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        handlers = []
        
        # 添加文件处理器（如果指定了日志文件）
        if log_file:
            # 确保日志文件目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(logging.Formatter(format_str))
            handlers.append(file_handler)
        
        # 添加控制台处理器（如果需要）
        if console_output:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter(format_str))
            handlers.append(console_handler)
        
        # 配置日志
        logging.basicConfig(
            level=level,
            format=format_str,
            handlers=handlers,
            force=True  # 强制重新配置
        )
    
    @classmethod
    def setup_crawler_logger(
        cls,
        log_file: str = None,
        project_root: Optional[str] = None
    ) -> None:
        """
        设置爬虫项目的日志配置
        
        Args:
            log_file: 日志文件名，如果为None则使用配置文件中的默认值
            project_root: 项目根目录，如果为None则使用当前目录
        """
        config = load_config()
        crawler_config = config.get('crawler_settings', {})
        
        # 使用参数或默认值
        log_file_name = log_file or crawler_config.get('log_file', 'crawler_api.log')
        console_output = crawler_config.get('console_output', True)
        log_level_str = crawler_config.get('log_level', 'INFO')
        
        if project_root:
            log_file_path = os.path.join(project_root, log_file_name)
        else:
            log_file_path = log_file_name
        
        # 将字符串日志级别转换为logging常量
        log_level = getattr(logging, log_level_str, logging.INFO)
        
        cls.setup_basic_logger(
            log_file=log_file_path,
            log_level=log_level,
            log_format=config.get('default_log_format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
            console_output=console_output
        )
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        获取指定名称的日志记录器
        
        Args:
            name: 日志记录器名称
            
        Returns:
            logging.Logger: 日志记录器实例
        """
        return logging.getLogger(name)
    
    @classmethod
    def reload_config(cls) -> dict:
        """
        重新加载配置
        
        Returns:
            最新的配置字典
        """
        return load_config()
    
    @classmethod
    def update_config(cls, config_dict: dict) -> bool:
        """
        更新配置并保存到JSON文件
        
        Args:
            config_dict: 新的配置字典
            
        Returns:
            是否更新成功
        """
        try:
            # 创建完整的数据结构
            data = {"logger_settings": config_dict}
            
            # 写入JSON文件
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"更新日志配置文件失败: {e}")
            return False