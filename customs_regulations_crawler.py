import asyncio
import re
import os
import json
import pandas as pd
import functools
import random
import math
import aiohttp
import warnings
import sys
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

# Crawl4AI 依赖
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# 忽略 UserWarning (屏蔽 proxy 参数过时的警告)
warnings.filterwarnings("ignore", category=UserWarning)

# ==========================================
# 1. 代理管理模块 (自动维护与轮换)
# ==========================================

DYNAMIC_PROXY_API = "http://www.zdopen.com/ShortProxy/GetIP/?api=202504121800103792&akey=a84329d64bcc4039&timespan=5&type=3"


class ProxyManager:
    def __init__(self):
        self.proxy_queue = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def check_proxy_valid(
        self, session: aiohttp.ClientSession, ip: str, port: int, timeout: int = 5
    ) -> Dict:
        """快速检测代理有效性"""
        proxy_url = f"http://{ip}:{port}"
        result = {"ip": ip, "port": port, "valid": False, "proxy_url": proxy_url}

        try:
            # 降低校验超时时间，快速筛选
            async with session.get(
                "http://www.baidu.com",
                proxy=proxy_url,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 200:
                    result["valid"] = True
        except Exception:
            pass
        return result

    async def fetch_and_fill_pool(self):
        """调用API获取并验证新代理"""
        print("\n[代理池] 正在请求新代理...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(DYNAMIC_PROXY_API, timeout=10) as response:
                    if response.status != 200:
                        print(f"[代理池] API请求失败: {response.status}")
                        return

                    data = await response.json()
                    proxy_list = data.get("data", {}).get("proxy_list", [])

                    if not proxy_list:
                        print(f"[代理池] API返回为空: {data.get('msg')}")
                        return

                    print(
                        f"[代理池] 获取到 {len(proxy_list)} 个候选IP，开始并行验证..."
                    )

                    tasks = [
                        self.check_proxy_valid(session, p["ip"], p["port"])
                        for p in proxy_list
                    ]
                    results = await asyncio.gather(*tasks)

                    added_count = 0
                    for res in results:
                        if res["valid"]:
                            await self.proxy_queue.put(res["proxy_url"])
                            added_count += 1

                    print(
                        f"[代理池] 补充完成，新增可用: {added_count}，当前库存: {self.proxy_queue.qsize()}"
                    )

        except Exception as e:
            print(f"[代理池] 刷新异常: {e}")

    async def get_proxy(self) -> str:
        """获取一个可用代理，如果池空了自动刷新"""
        async with self._lock:
            if self.proxy_queue.empty():
                await self.fetch_and_fill_pool()

            if self.proxy_queue.empty():
                print("[代理池] 暂时耗尽，等待 5 秒...")
                await asyncio.sleep(5)
                return await self.get_proxy()

            proxy = await self.proxy_queue.get()
            return proxy


# ==========================================
# 2. 常量定义
# ==========================================

REGULATION_TYPES = [
    "法律",
    "行政法规",
    "海关规章",
    "其他部门规章",
    "海关规范性文件",
    "其他部委文件",
    "公约条约",
    "其他参考资料",
]

STATUS_OPTIONS = ["失效", "废止", "部分修改", "有效"]

CONTENT_CATEGORIES = [
    "综合类",
    "进出口货物监管类",
    "运输工具监管类",
    "进出境物品监管类",
    "关税征收管理类",
    "加工贸易保税监管类",
    "案件稽查类",
    "企业管理类",
    "知识产权类",
    "其他",
]


class ProgressTracker:
    """全局进度追踪器 (线程安全)"""

    def __init__(self, total):
        self.total = total
        self.current = 0
        self._lock = asyncio.Lock()

    async def increment(self):
        async with self._lock:
            self.current += 1
            return self.current

    def get_progress_str(self, current):
        percent = (current / self.total) * 100 if self.total > 0 else 0
        return f"[进度: {current}/{self.total} | {percent:.1f}%]"


class CustomsRegulationCrawler:
    def __init__(self, concurrent_workers: int = 4, save_batch_size: int = 30):
        self.concurrent_workers = concurrent_workers
        self.save_batch_size = save_batch_size
        self._write_queue: Optional[asyncio.Queue] = None
        self._task_queue: Optional[asyncio.Queue] = None  # 共享任务队列
        self.proxy_manager = ProxyManager()
        self.progress_tracker: Optional[ProgressTracker] = None

    # ==========================================
    # 3. 链接与提取逻辑
    # ==========================================
    async def get_regulation_links(self) -> List[str]:
        try:
            url_list_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "url_list"
            )
            json_files = [f for f in os.listdir(url_list_dir) if f.endswith(".json")]
            if not json_files:
                return []
            json_file = max(json_files)  # 取最新的
            json_path = os.path.join(url_list_dir, json_file)
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("links", [])
        except Exception as e:
            print(f"[初始化失败] {e}")
            return []

    def _extract_data_enhanced(self, result) -> Dict:
        text_content = (
            getattr(result.markdown, "fit_markdown", None) or result.markdown or ""
        )

        def get_match(pattern, text):
            m = re.search(pattern, text)
            return m.group(1).strip() if m else ""

        title = get_match(r"# ([^\n]+)", text_content)
        doc_no = get_match(r"文[号:：]\s*([^\n]+)", text_content)
        pub_date = re.sub(
            r"^期】", "", get_match(r"发布[日期:：]\s*([^\n]+)", text_content)
        )
        eff_date = get_match(r"实施[日期:：]\s*([^\n]+)", text_content)

        # 匹配效力
        status = "有效"
        check_area = title + text_content[:800]
        for opt in STATUS_OPTIONS:
            if opt in check_area:
                status = opt
                if opt in ["失效", "废止"]:
                    status = "失效"
                break

        # 匹配法规类型
        reg_type = "其他参考资料"
        found_type = False
        for rt in REGULATION_TYPES:
            if rt in text_content[:300]:
                reg_type = rt
                found_type = True
                break
        if not found_type:
            if "令" in doc_no:
                reg_type = "海关规章"
            elif "公告" in doc_no:
                reg_type = "海关规范性文件"

        # 匹配内容类别
        category = "其他"
        best_score = 0
        keywords_map = {
            "进出口货物监管类": ["货物", "通关", "报关", "查验", "监管代码"],
            "运输工具监管类": ["船舶", "航空器", "车辆", "集装箱", "运输"],
            "进出境物品监管类": ["行李", "物品", "邮递", "快件", "个人携带"],
            "关税征收管理类": ["税率", "征税", "完税", "HS编码", "原产地"],
            "加工贸易保税监管类": ["保税", "加工贸易", "深加工", "自贸区", "综保区"],
            "案件稽查类": ["稽查", "走私", "处罚", "扣留"],
            "企业管理类": ["注册", "备案", "AEO", "信用", "认证"],
            "知识产权类": ["知识产权", "商标", "专利", "奥林匹克"],
            "公约条约": ["协定", "公约", "备忘录"],
        }
        check_text = (title + text_content[:1000]).replace("\n", "")
        for cat in CONTENT_CATEGORIES:
            score = 0
            if cat in check_text:
                score += 10
            if cat in keywords_map:
                for kw in keywords_map[cat]:
                    if kw in check_text:
                        score += 2
            if score > best_score:
                best_score = score
                category = cat
        if best_score == 0:
            category = "综合类"

        return {
            "标题": title,
            "文号": doc_no,
            "发布日期": pub_date,
            "实施日期": eff_date,
            "效力": status,
            "法规类型": reg_type,
            "内容类别": category,
            "主体内容": text_content,
            "URL": result.url,
        }

    # ==========================================
    # 4. 弹性并发 Worker (抢单模式 + 激进换IP)
    # ==========================================
    async def _worker_process(self, worker_id: int):
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3

        # 初始获取代理
        current_proxy = await self.proxy_manager.get_proxy()
        print(f"[Worker-{worker_id}] 🟢 就绪 | 初始代理: {current_proxy}")

        while not self._task_queue.empty():

            # --- 阶段1: 如果连续失败，强制换 IP ---
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(
                    f"[Worker-{worker_id}] 🔄 代理 {current_proxy} 质量差，正在更换..."
                )
                current_proxy = await self.proxy_manager.get_proxy()
                consecutive_failures = 0

            # --- 阶段2: 准备浏览器配置 ---
            browser_config = BrowserConfig(
                headless=True,
                text_mode=True,
                light_mode=True,
                proxy=current_proxy,
                extra_args=[
                    "--disable-gpu",
                    "--disable-images",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            # 缩短超时：15秒不通直接判定代理死亡
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=15000,
                target_elements=[
                    "#hgfg_con",
                    ".easysite-news-title",
                    ".easysite-news-text",
                ],
            )

            try:
                # 启动浏览器会话
                async with AsyncWebCrawler(config=browser_config) as crawler:

                    # 只要代理没坏，就一直去队列里抢任务
                    while not self._task_queue.empty():
                        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            break  # 跳出内层循环，去外层换 IP

                        try:
                            # >>> 核心：从共享队列取任务 <<<
                            url = self._task_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        try:
                            await asyncio.sleep(random.uniform(1.0, 2.5))
                            result = await crawler.arun(url=url, config=run_config)

                            if result.success:
                                # >>> 成功 (计数+1) <<<
                                current_count = await self.progress_tracker.increment()
                                progress_str = self.progress_tracker.get_progress_str(
                                    current_count
                                )

                                consecutive_failures = 0
                                data = self._extract_data_enhanced(result)

                                log_suffix = ""
                                if data["标题"]:
                                    if data["效力"] == "有效":
                                        await self._write_queue.put(data)
                                        log_suffix = f"√ {data['标题'][:10]}... [有效]"
                                    else:
                                        log_suffix = f"⊘ 跳过({data['效力']})"
                                else:
                                    log_suffix = "? 内容为空"

                                print(f"{progress_str} [W-{worker_id}] {log_suffix}")
                                self._task_queue.task_done()

                            else:
                                # >>> 失败 <<<
                                err_msg = result.error_message or "Unknown"
                                err_lower = err_msg.lower()
                                fatal_keywords = [
                                    "proxy",
                                    "timeout",
                                    "timed out",
                                    "reset",
                                    "closed",
                                    "refused",
                                    "failed",
                                    "net::",
                                    "err_",
                                    "403",
                                    "503",
                                ]
                                is_fatal = any(k in err_lower for k in fatal_keywords)
                                is_404 = "404" in err_msg or result.status_code == 404

                                if is_fatal and not is_404:
                                    # ⚠️ 致命错误：回滚队列，不增加进度
                                    consecutive_failures += 1
                                    print(
                                        f"[W-{worker_id}] ⚠️ 网络波动，任务回滚: {err_msg[:20]}... (重试)"
                                    )
                                    await self._task_queue.put(url)
                                    self._task_queue.task_done()
                                else:
                                    # × 404错误：视为完成，增加进度
                                    current_count = (
                                        await self.progress_tracker.increment()
                                    )
                                    progress_str = (
                                        self.progress_tracker.get_progress_str(
                                            current_count
                                        )
                                    )

                                    print(f"{progress_str} [W-{worker_id}] × 无效/404")
                                    consecutive_failures = 0
                                    self._task_queue.task_done()

                        except Exception as e_inner:
                            print(f"[Worker-{worker_id}] 异常回滚: {e_inner}")
                            await self._task_queue.put(url)
                            self._task_queue.task_done()
                            consecutive_failures += 1

            except Exception as e_session:
                print(f"[Worker-{worker_id}] 浏览器会话需重启: {e_session}")
                await asyncio.sleep(1)
                consecutive_failures = MAX_CONSECUTIVE_FAILURES  # 强制下次循环换IP

        print(f"[Worker-{worker_id}] 🛑 收工 (队列已空)")

    # ==========================================
    # 5. 写入模块
    # ==========================================
    def _write_excel_sync(self, all_data_buffer, filename):
        if not all_data_buffer:
            return
        try:
            df = pd.DataFrame(all_data_buffer)
            if os.path.exists(filename):
                with pd.ExcelWriter(
                    filename, engine="openpyxl", mode="a", if_sheet_exists="overlay"
                ) as writer:
                    try:
                        reader = pd.read_excel(filename)
                        start_row = len(reader) + 1
                        header = False
                    except:
                        start_row = 0
                        header = True
                    df.to_excel(writer, index=False, header=header, startrow=start_row)
            else:
                df.to_excel(filename, index=False)
            print(f"  💾 [保存] 写入 {len(all_data_buffer)} 条有效数据 -> {filename}")
        except Exception as e:
            print(f"  ❌ [保存失败] {e}")
            bk_name = f"backup_{int(datetime.now().timestamp())}.json"
            with open(bk_name, "w", encoding="utf-8") as f:
                json.dump(all_data_buffer, f, ensure_ascii=False)

    async def _writer_listener(self, output_file):
        buffer = []
        total_saved = 0
        print(f"[写入线程] 就绪，缓冲阈值: {self.save_batch_size}")

        while True:
            item = await self._write_queue.get()

            if item is None:
                if buffer:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        functools.partial(self._write_excel_sync, buffer, output_file),
                    )
                    total_saved += len(buffer)
                print(f"[写入线程] 退出。累计保存有效数据: {total_saved} 条。")
                break

            buffer.append(item)
            if len(buffer) >= self.save_batch_size:
                data_copy = buffer[:]
                buffer = []
                total_saved += len(data_copy)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    functools.partial(self._write_excel_sync, data_copy, output_file),
                )

    # ==========================================
    # 6. 主程序
    # ==========================================
    async def run(self):
        all_links = await self.get_regulation_links()
        if not all_links:
            return

        total_links = len(all_links)
        print(f"[主程序] 待爬取链接总数: {total_links}")

        self.progress_tracker = ProgressTracker(total_links)
        await self.proxy_manager.fetch_and_fill_pool()

        self._write_queue = asyncio.Queue()

        # 初始化共享任务队列
        self._task_queue = asyncio.Queue()
        for link in all_links:
            self._task_queue.put_nowait(link)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = f"海关法规_最终版_{timestamp}.xlsx"

        writer_task = asyncio.create_task(self._writer_listener(output_file))

        # 启动 Worker
        worker_tasks = []
        for i in range(self.concurrent_workers):
            worker_tasks.append(asyncio.create_task(self._worker_process(i + 1)))

        print(f"🚀 启动 {len(worker_tasks)} 个抢单 Worker")
        await asyncio.gather(*worker_tasks)
        print("所有 Worker 任务已结束。")

        await self._write_queue.put(None)
        await writer_task
        print(f"\n✅ 执行完毕！数据文件: {output_file}")


if __name__ == "__main__":
    # 并发数4，每30条写入一次
    crawler = CustomsRegulationCrawler(concurrent_workers=4, save_batch_size=30)
    asyncio.run(crawler.run())
