# 爬虫参数配置说明文档

## 配置文件位置
`config/crawler_params_config.json`

## 配置概览

### 1. concurrency_settings（并发设置）
控制并发爬虫实例数量，根据URL数量动态调整。

#### max_crawlers_by_url_count
根据URL数量自动选择最大并发爬虫实例数。

| max_urls | max_crawlers | 说明 |
|----------|--------------|------|
| ≤ 50     | 2            | 少量URL，低并发 |
| ≤ 200    | 4            | 中等数量URL |
| ≤ 500    | 6            | 较多URL，提高并发 |
| > 500    | 8            | 大规模URL，最高并发 |

**使用位置**: `crawler_utils.py:242`
```python
max_crawlers = crawler_params_config.get_max_crawlers(urls_count)
```

---

### 3. batch_size_settings（批量写入设置）
控制数据批量写入的大小，减少IO操作次数。

#### by_url_count
根据URL数量自动选择批量写入大小。

| max_urls | batch_size | 说明 |
|----------|------------|------|
| ≤ 50     | 5          | 小批量写入 |
| ≤ 200    | 10         | 中等批量 |
| ≤ 500    | 20         | 较大批量 |
| ≤ 5000   | 30         | 大批量写入 |
| > 5000   | 40         | 超大批量 |

**使用位置**: `crawler_utils.py:182`
```python
batch_size = crawler_params_config.get_batch_size(urls_count)
```

---

### 4. flush_interval_settings（刷新间隔设置）
控制批量写入器的自动刷新间隔（秒）。

#### by_url_count
根据URL数量自动选择刷新间隔。

| max_urls | flush_interval | 说明 |
|----------|----------------|------|
| ≤ 100    | 60             | 60秒刷新一次 |
| ≤ 500    | 30             | 30秒刷新一次 |
| ≤ 5000   | 20             | 20秒刷新一次 |
| > 5000   | 10             | 10秒刷新一次 |

**使用位置**: `crawler_utils.py:184`
```python
flush_interval = crawler_params_config.get_flush_interval(urls_count)
```

---

### 5. progress_settings（进度设置）
控制进度回调的触发时机。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| progress_after_fetch | 20 | 获取URL后立即更新进度 |
| progress_after_crawl | 90 | 爬取完成后更新进度 |
| progress_complete | 100 | 全部完成时更新进度 |

---

### 6. error_handling（错误处理设置）
控制重试策略和日志记录。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retry_attempts | 3 | 最大重试次数 |
| retry_delay_seconds | 1.0 | 重试延迟（秒） |
| log_success_threshold | 100 | 每成功N条记录一次日志 |

---

### 7. memory_settings（内存优化设置）
控制内存使用的优化策略。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| memory_optimization_threshold | 500 | URL数量超过此值时启用内存优化 |
| max_buffer_size_ratio | 0.05 | 缓冲区最大大小比例 |

**使用位置**: `crawler_utils.py:257`
```python
should_store_all_data = urls_count <= memory_optimization_threshold
```

---

### 8. proxy_settings（代理设置）
控制动态代理的使用和超时配置。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| use_dynamic_proxy | `false` | 是否启用动态代理 |
| max_consecutive_failures | 3 | 代理连续失败N次后切换代理 |
| page_timeout | 15000 | 页面加载超时时间（毫秒） |
| proxy_check_timeout | 5 | 代理可用性检查超时（秒） |

**使用位置**:
- `crawler_utils.py:187-189`
```python
use_dynamic_proxy = crawler_params_config.use_dynamic_proxy()
proxy_settings = crawler_params_config.get_proxy_settings()
max_consecutive_failures = proxy_settings.get("max_consecutive_failures", 3)
```

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

## 注意事项

1. **并发控制**: 并发数受系统资源限制，过高可能导致内存不足
2. **批量写入**: 批量大小影响内存占用和IO性能，需根据实际情况调整
3. **代理切换**: 连续失败会触发代理切换，避免因单个代理失败影响整体进度
4. **内存优化**: 超过阈值后不再保存完整数据到内存，避免内存溢出
