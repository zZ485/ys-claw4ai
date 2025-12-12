import os
import json
from typing import Optional

# 获取配置文件路径
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "path_config.json")

def load_config():
    """
    从JSON配置文件中加载配置
    
    Returns:
        配置字典，如果加载失败则返回默认配置
    """
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            return config_data.get('path_settings', {})
    except Exception as e:
        print(f"加载路径配置文件失败: {e}")
        return {
            "default_project_root": "e:/py_project/crawl4ai",
            "default_results_dir": "results"
        }


class PathConfig:
    """路径配置类，提供统一的路径配置管理"""
    
    def __init__(self, project_root: Optional[str] = None):
        """
        初始化路径配置
        
        Args:
            project_root: 项目根目录，如果为None则使用配置文件中的默认值
        """
        config = load_config()
        self.project_root = project_root or config.get('default_project_root', 'e:/py_project/crawl4ai')
        self.default_results_dir = config.get('default_results_dir', 'results')
    
    def get_results_dir(self) -> str:
        """
        获取结果保存目录
        
        Returns:
            str: 结果目录的完整路径
        """
        return os.path.join(self.project_root, self.default_results_dir)
    
    def get_output_file_path(self, file_name: str) -> str:
        """
        获取输出文件的完整路径
        
        Args:
            file_name: 文件名
            
        Returns:
            str: 文件的完整路径
        """
        # 确保文件名以.txt结尾
        output_file_name = file_name
        if not output_file_name.endswith('.txt'):
            output_file_name = f"{output_file_name}.txt"
        
        return os.path.join(self.get_results_dir(), output_file_name)
    
    def ensure_results_dir_exists(self) -> None:
        """确保结果目录存在"""
        results_dir = self.get_results_dir()
        os.makedirs(results_dir, exist_ok=True)
    
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
            data = {"path_settings": config_dict}
            
            # 写入JSON文件
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"更新路径配置文件失败: {e}")
            return False


# 创建默认配置实例
default_path_config = PathConfig()