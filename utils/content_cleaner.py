import re
from typing import Dict, Any, Optional
from config.logger_config import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class ContentCleaner:
    """内容清洗工具类，用于按照配置清洗文章内容"""

    def __init__(self, cleaning_config: Optional[Dict[str, Any]] = None):
        """
        初始化内容清洗器

        Args:
            cleaning_config: 清洗配置，格式为 {
                "source": 0/1,      # 0表示不清洗，1表示清洗
                "image_source": 0/1,# 0表示不清洗，1表示清洗
                "author": 0/1       # 0表示不清洗，1表示清洗
            }
        """
        self.cleaning_config = cleaning_config or {
            "source": 1,  # 默认清洗来源信息
            "image_source": 1,  # 默认清洗图源信息
            "author": 1,  # 默认清洗作者信息
        }

        # 定义各种清洗模式的正则表达式模式
        self.patterns = {
            "source": [
                r"文章来源：[^\n]+",
                r"注：文章来源[^\n]+",
                r"来源：[^\n]+",
                r"本文来自：[^\n]+",
                r"来源：[^\n]+热线",
                r"本文为作者独立观点，[^。\n]+。",
                r"（本文为作者独立观点，[^。\n]+。）",
                r"[\(（]?本文为作者独立观点，[^。\n]+。[）\)]?",
            ],
            "image_source": [
                r"图源：[^\n]+",
                r"图片来源：[^\n]+",
                r"图片来自：[^\n]+",
            ],
            "author": [
                r"作者：[^\n]+",
                r"文/[^\n]+",
                r"撰文：[^\n]+",
                r"记者[^\n]+",
            ],
        }

    def clean_content(self, content: str) -> str:
        """
        按照配置清洗内容

        Args:
            content: 原始内容

        Returns:
            str: 清洗后的内容
        """
        if not content or not isinstance(content, str):
            return content

        cleaned_content = content

        # 根据配置清洗各种信息
        for category, enabled in self.cleaning_config.items():
            if enabled == 1 and category in self.patterns:
                for pattern in self.patterns[category]:
                    # 使用re.DOTALL使.匹配包括换行符在内的所有字符
                    cleaned_content = re.sub(
                        pattern, "", cleaned_content, flags=re.MULTILINE | re.DOTALL
                    )

        # 清理多余的空行
        cleaned_content = re.sub(r"\n\s*\n", "\n\n", cleaned_content)

        # 清理开头和结尾的空白
        cleaned_content = cleaned_content.strip()

        return cleaned_content

    def should_clean_category(self, category: str) -> bool:
        """
        检查是否应该清洗某个类别

        Args:
            category: 类别名称 ("source", "image_source", "author")

        Returns:
            bool: 是否应该清洗
        """
        return self.cleaning_config.get(category, 0) == 1


def create_cleaner_from_config(
    cleaning_config: Optional[Dict[str, Any]] = None,
) -> ContentCleaner:
    """
    从配置创建内容清洗器

    Args:
        cleaning_config: 清洗配置

    Returns:
        ContentCleaner: 内容清洗器实例
    """
    return ContentCleaner(cleaning_config)
