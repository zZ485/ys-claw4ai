"""
海关总署法规爬取并保存为Excel工具
爬取海关总署法规，按类型分类，并将有效法规保存到Excel文件的不同sheet中
"""

import asyncio
import json
import re
import os
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from bs4 import BeautifulSoup

# 导入项目中的模块
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from get_links_script.customs_regulations import get_links
from config.target_elements_config import TargetElementsConfig
from utils.crawler_utils import build_crawler_config


@dataclass
class RegulationInfo:
    """法规信息数据模型"""

    title: str  # 标题
    document_number: str = ""  # 文号
    publish_date: str = ""  # 发布日期
    effective_date: str = ""  # 实施日期
    status: str = ""  # 效力
    regulation_type: str = ""  # 法规类型
    content: str = ""  # 内容
    url: str = ""  # 原始URL


class CustomsRegulationCrawler:
    """海关总署法规爬虫"""

    def __init__(self):
        """初始化爬虫"""
        self.target_config = TargetElementsConfig()
        self.customs_config = self.target_config.get_config("customs_regulations")
        self.regulation_types = {"部门规章": [], "规范性文件": [], "其他": []}

    async def get_regulation_links(self) -> Dict:
        """获取法规链接列表"""
        try:
            return await get_links()
        except Exception as e:
            print(f"获取法规链接失败: {e}")
            return {"count": 0, "links": []}

    async def crawl_regulations_batch(self, urls: List[str]) -> List[Dict]:
        """批量爬取法规内容，使用单个爬虫实例爬多个链接"""
        if not urls:
            return []

        try:
            # 获取CSS选择器配置
            css_selectors = self.customs_config

            # 构建爬虫配置
            crawler_config = await build_crawler_config(css_selectors)

            # 创建爬虫实例
            from crawl4ai import AsyncWebCrawler, BrowserConfig

            # 设置浏览器配置
            browser_config = BrowserConfig(text_mode=True, user_agent_mode="random")

            # 存储结果
            results = []

            # 使用单个爬虫实例批量爬取
            async with AsyncWebCrawler(config=browser_config) as crawler:
                # 分批处理URL，避免一次处理太多
                batch_size = 8  # 与crawler_utils.py中的chunk_size一致
                url_batches = [
                    urls[i : i + batch_size] for i in range(0, len(urls), batch_size)
                ]

                print(
                    f"使用单个爬虫实例分批爬取 {len(urls)} 个链接，每批 {batch_size} 个"
                )

                for batch_idx, batch in enumerate(url_batches):
                    print(
                        f"正在处理第 {batch_idx + 1}/{len(url_batches)} 批，包含 {len(batch)} 个链接"
                    )

                    # 使用arun_many方法批量爬取
                    batch_results = await crawler.arun_many(
                        urls=batch, config=crawler_config
                    )

                    # 处理每批结果
                    for result in batch_results:
                        if not result.success:
                            print(
                                f"  爬取失败: {result.url}, 错误: {result.error_message}"
                            )
                            results.append(None)
                            continue

                        # 获取内容
                        fit_markdown = (
                            getattr(result.markdown, "fit_markdown", None)
                            or result.markdown
                        )

                        # 解析标题
                        title_match = re.search(r"# ([^\n]+)", fit_markdown)
                        title = title_match.group(1).strip() if title_match else ""

                        # 解析文号
                        doc_no_match = re.search(r"文[号:：]\s*([^\n]+)", fit_markdown)
                        document_number = (
                            doc_no_match.group(1).strip() if doc_no_match else ""
                        )

                        # 解析发布日期
                        pub_date_match = re.search(
                            r"发布[日期:：]\s*([^\n]+)", fit_markdown
                        )
                        publish_date = (
                            pub_date_match.group(1).strip() if pub_date_match else ""
                        )
                        # 清理发布日期，移除可能的"期】"前缀
                        publish_date = re.sub(r"^期】", "", publish_date)

                        # 解析实施日期
                        eff_date_match = re.search(
                            r"实施[日期:：]\s*([^\n]+)", fit_markdown
                        )
                        effective_date = (
                            eff_date_match.group(1).strip() if eff_date_match else ""
                        )

                        # 解析法规类型
                        reg_type_match = re.search(
                            r"(部门规章|规范性文件|其他)", fit_markdown
                        )
                        regulation_type = (
                            reg_type_match.group(1).strip() if reg_type_match else ""
                        )

                        # 解析效力状态
                        status_match = re.search(
                            r"(有效|现行|实施中|失效|废止)", fit_markdown
                        )
                        status = status_match.group(1).strip() if status_match else ""

                        # 构建提取结果
                        extracted_data = {
                            "title": {"content": title},
                            "document_number": {"content": document_number},
                            "publish_date": {"content": publish_date},
                            "effective_date": {"content": effective_date},
                            "status": {"content": status},
                            "regulation_type": {"content": regulation_type},
                            "content": {"content": fit_markdown},
                        }

                        results.append(extracted_data)
                        print(f"  已提取: {title[:50]}...")

            return results

        except Exception as e:
            print(f"批量爬取法规失败: {e}")
            return [None] * len(urls)

    async def crawl_single_regulation(self, url: str) -> Optional[Dict]:
        """爬取单个法规内容"""
        results = await self.crawl_regulations_batch([url])
        return results[0] if results else None

    def parse_regulation_info(self, url: str, data: Dict) -> RegulationInfo:
        """解析法规信息"""
        # 解析标题
        title_data = data.get("title", {})
        if isinstance(title_data, dict):
            title = title_data.get("content", "")
            if not title and "regex" in title_data:
                match = re.search(
                    title_data.get("regex", ""), title_data.get("text", "")
                )
                if match:
                    title = match.group(1) if match.groups() else match.group(0)
        elif isinstance(title_data, str):
            title = title_data
        else:
            title = ""

        # 创建法规对象
        regulation = RegulationInfo(title=title, url=url)

        # 解析文号
        doc_number_data = data.get("document_number", {})
        if isinstance(doc_number_data, dict) and "content" in doc_number_data:
            regulation.document_number = doc_number_data.get("content", "")
        elif isinstance(doc_number_data, str):
            regulation.document_number = doc_number_data

        # 解析发布日期
        pub_date_data = data.get("publish_date", {})
        if isinstance(pub_date_data, dict) and "content" in pub_date_data:
            regulation.publish_date = pub_date_data.get("content", "")
        elif isinstance(pub_date_data, str):
            regulation.publish_date = pub_date_data

        # 解析实施日期
        eff_date_data = data.get("effective_date", {})
        if isinstance(eff_date_data, dict) and "content" in eff_date_data:
            regulation.effective_date = eff_date_data.get("content", "")
        elif isinstance(eff_date_data, str):
            regulation.effective_date = eff_date_data

        # 解析效力
        status_data = data.get("status", {})
        if isinstance(status_data, dict) and "content" in status_data:
            regulation.status = status_data.get("content", "")
        elif isinstance(status_data, str):
            regulation.status = status_data

        # 解析法规类型
        type_data = data.get("regulation_type", {})
        if isinstance(type_data, dict) and "content" in type_data:
            regulation.regulation_type = type_data.get("content", "")
        elif isinstance(type_data, str):
            regulation.regulation_type = type_data

        # 解析内容
        content_data = data.get("content", {})
        if isinstance(content_data, dict) and "content" in content_data:
            regulation.content = content_data.get("content", "")
        elif isinstance(content_data, str):
            regulation.content = content_data

        return regulation

    def filter_valid_regulations(
        self, regulations: List[RegulationInfo]
    ) -> List[RegulationInfo]:
        """按【效力】筛选有效法规"""
        valid_regulations = []
        for regulation in regulations:
            # 如果状态字段包含"有效"、"现行"或"实施中"，认为是有效法规
            if any(
                keyword in regulation.status for keyword in ["有效", "现行", "实施中"]
            ):
                valid_regulations.append(regulation)
        return valid_regulations

    def classify_regulations(
        self, regulations: List[RegulationInfo]
    ) -> Dict[str, List[RegulationInfo]]:
        """按【法规类型】分类法规"""
        classified = {"部门规章": [], "规范性文件": [], "其他": []}

        for regulation in regulations:
            # 根据标题或内容判断法规类型
            reg_type = regulation.regulation_type
            if not reg_type:
                # 如果没有明确类型，根据标题判断
                if "规章" in regulation.title or "规定" in regulation.title:
                    reg_type = "部门规章"
                elif "办法" in regulation.title or "规则" in regulation.title:
                    reg_type = "规范性文件"
                else:
                    reg_type = "其他"

            # 标准化类型名称
            if "规章" in reg_type:
                reg_type = "部门规章"
            elif "规范" in reg_type or "文件" in reg_type:
                reg_type = "规范性文件"
            else:
                reg_type = "其他"

            classified[reg_type].append(regulation)

        return classified

    def export_to_excel(
        self,
        classified_regulations: Dict[str, List[RegulationInfo]],
        output_file: str = "customs_regulations.xlsx",
    ):
        """将分类后的法规导出到Excel文件的不同sheet中"""
        # 检查是否有数据
        has_data = any(regulations for regulations in classified_regulations.values())
        if not has_data:
            print("没有法规数据可导出")
            return

        # 创建Excel写入对象
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            for reg_type, regulations in classified_regulations.items():
                if not regulations:
                    continue

                # 准备数据
                data = []
                for regulation in regulations:
                    data.append(
                        {
                            "标题": regulation.title,
                            "文号": regulation.document_number,
                            "发布日期": regulation.publish_date,
                            "实施日期": regulation.effective_date,
                            "效力": regulation.status,
                            "法规类型": regulation.regulation_type,
                            "主体内容": regulation.content,
                            "URL": regulation.url,
                        }
                    )

                # 创建DataFrame
                df = pd.DataFrame(data)

                # 写入Excel sheet
                sheet_name = reg_type[:31]  # Excel sheet名称最大31个字符
                df.to_excel(writer, sheet_name=sheet_name, index=False)

                print(f"已导出 {reg_type} 法规 {len(regulations)} 条")

        print(f"法规数据已导出到: {output_file}")

    async def run(self):
        """执行完整的爬取流程"""
        print("开始爬取海关总署法规...")

        # 1. 获取法规链接
        links_result = await self.get_regulation_links()
        links = links_result.get("links", [])
        total_links = links_result.get("count", 0)
        print(f"获取到 {total_links} 条法规链接")

        # 2. 批量爬取法规内容
        print("开始批量爬取法规内容...")
        crawl_results = await self.crawl_regulations_batch(links)

        # 3. 解析法规信息
        regulations = []
        for i, (link, data) in enumerate(zip(links, crawl_results)):
            if data:
                regulation = self.parse_regulation_info(link, data)
                regulations.append(regulation)
                print(f"已提取 ({i+1}/{total_links}): {regulation.title[:50]}...")
            else:
                print(f"爬取失败 ({i+1}/{total_links}): {link}")

        print(f"\n成功爬取 {len(regulations)} 条法规信息")

        # 4. 筛选有效法规
        valid_regulations = self.filter_valid_regulations(regulations)
        print(f"其中有效法规 {len(valid_regulations)} 条")

        # 5. 按类型分类
        classified_regulations = self.classify_regulations(valid_regulations)

        # 打印分类统计
        for reg_type, regs in classified_regulations.items():
            print(f"{reg_type}: {len(regs)} 条")

        # 6. 导出Excel
        self.export_to_excel(classified_regulations)

        print("爬取任务完成!")


async def main():
    """主函数"""
    crawler = CustomsRegulationCrawler()
    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())
