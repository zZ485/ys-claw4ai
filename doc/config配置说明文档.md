# 配置文件说明文档

## 配置文件目录
所有配置文件位于 `config/` 目录下。

---

## 1. crawler_params_config.json

### 作用
爬虫参数配置，控制爬虫的并发、批量写入、刷新间隔等行为。

### 配置项

#### concurrency_settings（并发设置）
控制并发爬虫实例数量，根据URL数量动态调整。

| 参数 | 说明 |
|------|------|
| max_crawlers_by_url_count | 根据URL数量选择最大并发数 |

**使用位置**: `crawler_utils.py:242`

| max_urls | max_crawlers | 说明 |
|----------|--------------|------|
| ≤ 50     | 2            | 少量URL，低并发 |
| ≤ 200    | 4            | 中等数量URL |
| ≤ 500    | 6            | 较多URL，提高并发 |
| > 500    | 8            | 大规模URL，最高并发 |

#### batch_size_settings（批量写入设置）
控制数据批量写入的大小，减少IO操作次数。

| 参数 | 说明 |
|------|------|
| by_url_count | 根据URL数量选择批量写入大小 |

**使用位置**: `crawler_utils.py:182`

| max_urls | batch_size | 说明 |
|----------|------------|------|
| ≤ 50     | 5          | 小批量写入 |
| ≤ 200    | 10         | 中等批量 |
| ≤ 500    | 20         | 较大批量 |
| ≤ 5000   | 30         | 大批量写入 |
| > 5000   | 40         | 超大批量 |

#### flush_interval_settings（刷新间隔设置）
控制批量写入器的自动刷新间隔（秒）。

| 参数 | 说明 |
|------|------|
| by_url_count | 根据URL数量选择刷新间隔 |

**使用位置**: `crawler_utils.py:184`

| max_urls | flush_interval | 说明 |
|----------|----------------|------|
| ≤ 100    | 60             | 60秒刷新一次 |
| ≤ 500    | 30             | 30秒刷新一次 |
| ≤ 5000   | 20             | 20秒刷新一次 |
| > 5000   | 10             | 10秒刷新一次 |

#### progress_settings（进度设置）
控制进度回调的触发时机。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| progress_after_fetch | 20 | 获取URL后立即更新进度 |
| progress_after_crawl | 90 | 爬取完成后更新进度 |
| progress_complete | 100 | 全部完成时更新进度 |

#### error_handling（错误处理设置）
控制重试策略和日志记录。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retry_attempts | 3 | 最大重试次数 |
| retry_delay_seconds | 1.0 | 重试延迟（秒） |
| log_success_threshold | 100 | 每成功N条记录一次日志 |

#### memory_settings（内存优化设置）
控制内存使用的优化策略。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| memory_optimization_threshold | 500 | URL数量超过此值时启用内存优化 |
| max_buffer_size_ratio | 0.05 | 缓冲区最大大小比例 |

**使用位置**: `crawler_utils.py:257`

#### proxy_settings（代理设置）
控制动态代理的使用和超时配置。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| use_dynamic_proxy | `false` | 是否启用动态代理 |
| max_consecutive_failures | 3 | 代理连续失败N次后切换代理 |
| page_timeout | 15000 | 页面加载超时时间（毫秒） |
| proxy_check_timeout | 5 | 代理可用性检查超时（秒） |

**使用位置**: `crawler_utils.py:187-189`

---

## 2. db_config.json

### 作用
数据库连接配置，用于连接达梦数据库。

### 配置项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| host | localhost | 数据库主机地址 |
| port | 5236 | 数据库端口 |
| user | SYSDBA | 数据库用户名 |
| password | 123456yY | 数据库密码 |
| database | SYSDBA | 数据库名称 |
| log_sql | false | 是否记录SQL日志 |
| pool_size | 10 | 连接池大小 |

### 使用位置
- `crawler_api.py:45-55` - 初始化数据库连接池
- `utils/db_manager.py` - 数据库操作

---

## 3. logger_config.json

### 作用
日志配置，控制日志格式、级别和输出方式。

### 配置项

#### logger_settings
日志全局设置。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| default_log_format | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | 默认日志格式 |
| default_log_level | INFO | 默认日志级别 |

#### crawler_settings
爬虫专用日志设置。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| log_file | crawler_api.log | 日志文件名 |
| console_output | true | 是否输出到控制台 |
| log_level | INFO | 日志级别 |

### 使用位置
- `config/logger_config.py` - 日志配置管理
- `crawler_api.py:28-31` - 设置API服务日志
- `get_links_script/*.py` - 设置爬虫脚本日志

---

## 4. path_config.json

### 作用
路径配置，管理项目目录和输出路径。

### 配置项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| default_project_root | e:/py_project/crawl4ai | 项目根目录 |
| default_results_dir | results | 结果输出目录 |

### 使用位置
- `crawler_api.py:404-406` - 确保结果目录存在
- `utils/batch_writer.py` - 批量写入文件路径
- `utils/task_manager.py` - 任务管理器路径

---

## 5. display_names_config.json

### 作用
配置名称映射，为各种爬虫模板提供友好显示名称。

### 配置项

#### config_display_names
爬虫模板名称与显示名称的映射关系。

| key（配置key） | value（显示名称） |
|---------------|------------------|
| shanghai_cross_border_association_news | 上海跨境电商协会-行业新闻 |
| ebrun_general | 亿邦动力-最新全部 |
| dianshangbao_logistics | 电商报-物流 |
| customs_regulations | 海关总署-海关法规 |

### 使用位置
- `crawler_api.py:204` - 获取格式化配置列表
- `/target_configs` API接口 - 返回可用的爬虫模板

---

## 6. target_elements_config.json

### 作用
目标元素配置，为不同网站指定需要提取的CSS选择器。

### 配置项

#### preset_configs
预设的目标元素CSS选择器配置。

| key（配置key） | value（CSS选择器） | 说明 |
|---------------|------------------|------|
| ebrun_general | [".post-text-title", ".post-text"] | 亿邦动力全部文章选择器 |
| dianshangbao_logistics | [".mb-3.border.bg-card.p-9.md\\:px-16 > h1", "#post-body"] | 电商报物流选择器 |
| customs_regulations | ["#hgfg_con",".easysite-news-title", ".easysite-news-text"] | 海关法规选择器 |

### 使用位置
- `utils/task_manager.py` - 加载目标元素配置
- `base_crawler/FitMarkdown.py` - 提取页面元素

---

## 7. knowledge_base_config.json

### 作用
知识库配置，用于知识库上传相关功能。

### 配置项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| api_base_url | http://192.168.9.47:8000 | 知识库API地址 |
| upload_timeout | 300 | 上传超时时间（秒） |
| auto_upload | false | 是否自动上传 |

### 使用位置
- `utils/knowledge_base_manager.py` - 知识库上传管理

---

## 配置调整建议

### 小规模爬取（≤ 50 URL）
- 保持低并发（2），避免资源浪费
- 小批量写入（5），快速看到结果

### 中等规模爬取（50-200 URL）
- 适度提高并发（4）
- 增大批量大小（10）

### 大规模爬取（> 500 URL）
- 启用内存优化
- 使用最高并发（8）
- 增大批量大小（20-40）
- 减少刷新间隔，防止数据丢失

### 使用代理时
- 设置 `use_dynamic_proxy: true`
- 确保 `max_consecutive_failures` 合理（建议3-5）
- 根据代理质量调整 `page_timeout`

---

## 配置热重载

API支持运行时重新加载配置，无需重启服务：

```
POST /reload_config
{
  "config_type": "all"  // 可选: display_names, target_elements, path, logger, crawler_params, all
}
```

支持热重载的配置类型：
- `display_names` - 显示名称配置
- `target_elements` - 目标元素配置
- `path` - 路径配置
- `logger` - 日志配置
- `crawler_params` - 爬虫参数配置
- `all` - 重新加载所有配置

---

## 注意事项

1. **并发控制**: 并发数受系统资源限制，过高可能导致内存不足
2. **批量写入**: 批量大小影响内存占用和IO性能，需根据实际情况调整
3. **代理切换**: 连续失败会触发代理切换，避免因单个代理失败影响整体进度
4. **内存优化**: 超过阈值后不再保存完整数据到内存，避免内存溢出
5. **数据库连接**: 修改数据库配置后需要重启服务才能生效
6. **日志文件**: 日志文件会按日期分割，建议定期清理旧日志
