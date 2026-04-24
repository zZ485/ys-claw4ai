# YS-Crawl4AI

基于 [Crawl4AI](https://github.com/unclecode/crawl4ai) 的网页内容采集与清洗服务，支持多种目标网站配置、增量/全量采集、知识库上传等功能。

## 功能特性

- **多目标采集**：支持配置多种目标网站，灵活切换采集模板
- **增量/全量模式**：支持增量采集和全量采集两种模式
- **知识库上传**：采集内容自动上传至知识库，支持一致性校验
- **内容清洗**：支持来源、图片来源、作者等多维度内容清洗配置
- **异步任务管理**：基于异步架构，支持并发采集与任务状态追踪
- **动态代理IP**：支持动态代理IP获取与验证
- **REST API**：提供 FastAPI 接口，方便集成调用

## 项目结构

```
crawl4ai/
├── config/                  # 配置文件目录
│   ├── crawler_params_config.json/py   # 爬虫参数配置
│   ├── db_config.json/py               # 数据库配置
│   ├── display_names_config.json/py     # 显示名称配置
│   ├── knowledge_base_config.json/py    # 知识库配置
│   ├── logger_config.json/py            # 日志配置
│   ├── path_config.json/py              # 路径配置
│   └── target_elements_config.json/py   # 目标元素配置
├── get_links_script/        # 各目标网站采集脚本
├── utils/                   # 工具模块
│   ├── batch_writer.py      # 批量写入器
│   ├── content_cleaner.py   # 内容清洗
│   ├── crawler_utils.py     # 爬虫工具
│   ├── db_manager.py        # 数据库管理
│   ├── dynamic_ip_util.py   # 动态代理IP
│   ├── incremental_crawler.py # 增量爬虫
│   ├── knowledge_base_uploader.py # 知识库上传
│   └── task_manager.py      # 任务管理器
├── sql/                     # SQL 初始化脚本
├── doc/                     # 文档
├── crawler_api.py           # FastAPI 服务入口
├── start_server.py          # 服务器启动脚本
└── requirements.txt         # 项目依赖
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install
```

### 2. 配置

根据需要修改 `config/` 目录下的 JSON 配置文件，主要包括：

- `db_config.json` — 数据库连接配置
- `knowledge_base_config.json` — 知识库接口配置
- `crawler_params_config.json` — 爬虫运行参数
- `path_config.json` — 输出路径配置

### 3. 启动服务

```bash
python start_server.py
# 或指定参数
python start_server.py --host 0.0.0.0 --port 8001
```

服务启动后访问 `http://127.0.0.1:8001/docs` 查看 API 文档。

### 4. 调用接口

**创建采集任务：**

```bash
curl -X POST http://127.0.0.1:8001/collect \
  -H "Content-Type: application/json" \
  -d '{
    "target": "target_config_name",
    "task_name": "测试采集任务",
    "is_incremental": 0,
    "knowledge_base_name": "知识库名称",
    "knowledge_base_id": "知识库ID"
  }'
```

**查询任务列表：**

```bash
curl -X POST http://127.0.0.1:8001/tasks \
  -H "Content-Type: application/json" \
  -d '{"page": 1, "page_size": 10}'
```

## 技术栈

- **Web 框架**：FastAPI + Uvicorn
- **爬虫引擎**：Crawl4AI
- **异步 HTTP**：aiohttp
- **浏览器自动化**：Playwright
- **HTML 解析**：BeautifulSoup4
- **数据库**：SQLite（本地）/ MySQL（远程）
- **数据验证**：Pydantic

## 许可证

MIT License
