-- SQLite 建表脚本
-- 数据库文件默认位于项目 data/crawler.db

-- 创建采集任务表
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
);

-- 创建最新链接表
CREATE TABLE IF NOT EXISTS collected_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_template TEXT NOT NULL,
    url TEXT NOT NULL,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_collection_task_template ON collection_task(collection_template);
CREATE INDEX IF NOT EXISTS idx_collection_task_status ON collection_task(task_status);
CREATE INDEX IF NOT EXISTS idx_collected_links_template ON collected_links(collection_template);
