DROP TABLE IF EXISTS collection_task;
DROP TABLE IF EXISTS collected_links;

-- 创建采集任务表
CREATE TABLE collection_task (
    task_id VARCHAR(50) PRIMARY KEY,
    task_name VARCHAR(255) NOT NULL,
    task_status VARCHAR(50) NOT NULL,
    collection_template VARCHAR(255) NOT NULL,
    task_type TINYINT NOT NULL CHECK (task_type IN (0, 1)),
    knowledge_base_name VARCHAR(255) NOT NULL,
    knowledge_base_id VARCHAR(255) NOT NULL,
    failure_reason VARCHAR(1000),
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    complete_time TIMESTAMP,
    progress INT DEFAULT 0 NOT NULL CHECK (progress BETWEEN 0 AND 100),
    total_links INT DEFAULT 0 NOT NULL,
    success_count INT DEFAULT 0 NOT NULL,
    error_count INT DEFAULT 0 NOT NULL
);

-- 创建最新链接表
CREATE TABLE collected_links (
    id INT IDENTITY(1,1) PRIMARY KEY,
    collection_template VARCHAR(255) NOT NULL,
    url VARCHAR(1000) NOT NULL,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 添加表注释
COMMENT ON TABLE collection_task IS '采集任务表';
COMMENT ON TABLE collected_links IS '最新链接表，存储每种采集模板的最新链接';

-- 添加字段注释
COMMENT ON COLUMN collection_task.task_id IS '任务编号（主键）';
COMMENT ON COLUMN collection_task.task_name IS '任务名称';
COMMENT ON COLUMN collection_task.task_status IS '任务状态：pending/running/success/failed/cancelled';
COMMENT ON COLUMN collection_task.collection_template IS '采集模板名称（关联target配置）';
COMMENT ON COLUMN collection_task.task_type IS '任务类型：0-增量采集，1-全量采集';
COMMENT ON COLUMN collection_task.knowledge_base_name IS '知识库名称';
COMMENT ON COLUMN collection_task.knowledge_base_id IS '知识库ID'; 
COMMENT ON COLUMN collection_task.failure_reason IS '失败原因（仅当状态为failed时有效）';
COMMENT ON COLUMN collection_task.create_time IS '任务创建时间';
COMMENT ON COLUMN collection_task.complete_time IS '任务完成时间';
COMMENT ON COLUMN collection_task.progress IS '任务进度百分比(0-100)';
COMMENT ON COLUMN collection_task.total_links IS '总链接数量';
COMMENT ON COLUMN collection_task.success_count IS '成功爬取数量';
COMMENT ON COLUMN collection_task.error_count IS '失败爬取数量';

COMMENT ON COLUMN collected_links.id IS '自增主键ID';
COMMENT ON COLUMN collected_links.collection_template IS '采集模板名称';
COMMENT ON COLUMN collected_links.url IS '最新链接地址';
COMMENT ON COLUMN collected_links.create_time IS '记录创建时间';