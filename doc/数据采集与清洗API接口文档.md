# 数据采集与清洗API接口文档

## 基础信息

- **基础URL**: `http://71gf4110cg54.vicp.fun`
- **API文档地址**: `http://71gf4110cg54.vicp.fun/docs`

### 服务器启动

使用以下命令启动API服务器：

```bash
python start_server.py
```

可选参数：
- `--host`: 监听地址 (默认: 127.0.0.1)
- `--port`: 监听端口 (默认: 8001)
- `--reload`: 启用自动重载 (开发模式)
- `--log-level`: 日志级别 (critical, error, warning, info, debug)

示例：
```bash
python start_server.py --host 0.0.0.0 --port 8080 --reload --log-level debug
```

## 通用响应格式

所有API响应都采用统一的JSON格式：

```json
{
  "code": 200,
  "message": "成功信息",
  "data": {}
}
```

- `code`: 状态码，200表示成功，其他值表示错误
- `message`: 响应消息
- `data`: 响应数据，具体结构根据不同接口而定

---

## 1. 获取目标配置

### 接口描述
获取所有可用的目标元素配置

### 请求信息
- **URL**: `/target_configs`
- **方法**: `GET`

### 请求参数
无

### 响应示例
```json
{
  "code": 200,
  "message": "获取配置成功",
  "data": {
    "configs": [
      {
        "key": "shanghai_cross_border_association_news",
        "name": "上海跨境电商协会-行业新闻"
      },
      {
        "key": "shanghai_cross_border_association_data",
        "name": "上海跨境电商协会-行业数据"
      },
      {
        "key": "shanghai_cross_border_association_policy",
        "name": "上海跨境电商协会-最新政策"
      },
      {
        "key": "shanghai_cross_border_association_policy_interpretation",
        "name": "上海跨境电商协会-政策解读"
      },
      {
        "key": "shanghai_cross_border_association_interactive_communication",
        "name": "上海跨境电商协会-互动交流"
      },
      {
        "key": "ebrun_general",
        "name": "亿邦动力-最新全部"
      },
      {
        "key": "ebrun_newsflash",
        "name": "亿邦动力-快讯"
      },
      {
        "key": "ebrun_weight_list",
        "name": "亿邦动力-独家重磅"
      },
      {
        "key": "ebrun_special_topic",
        "name": "亿邦动力-专题"
      },
      {
        "key": "ebrun_column",
        "name": "亿邦动力-专栏"
      },
      {
        "key": "ebrun_business_trends",
        "name": "亿邦动力-商情动态"
      },
      {
        "key": "ennews_information",
        "name": "亿恩网-资讯"
      },
      {
        "key": "ennews_newsflash",
        "name": "亿恩网-快讯"
      },
      {
        "key": "dianshangbao_newsflash",
        "name": "电商报-快讯"
      },
      {
        "key": "dianshangbao_retail",
        "name": "电商报-零售"
      },
      {
        "key": "dianshangbao_logistics",
        "name": "电商报-物流"
      },
      {
        "key": "dianshangbao_life_service",
        "name": "电商报-生活服务"
      },
      {
        "key": "dianshangbao_b2b",
        "name": "电商报-B2B"
      },
      {
        "key": "dianshangbao_people",
        "name": "电商报-人物"
      },
      {
        "key": "dianshangbao_cross_border_ecommerce",
        "name": "电商报-跨境电商"
      },
      {
        "key": "dianshangbao_industry_observation",
        "name": "电商报-行业观察"
      },
      {
        "key": "customs_regulations",
        "name": "海关总署-海关法规"
      }
    ]
  }
}
```

### 响应字段说明
- `configs`: 配置列表
  - `key`: 配置标识符，用于采集请求中的target参数
  - `name`: 配置显示名称

---

## 2. 采集数据

### 接口描述
创建异步采集任务，立即返回任务ID，任务在后台执行

### 请求信息
- **URL**: `/collect`
- **方法**: `POST`

### 请求参数
```json
{
  "target": "shanghai_cross_border_association_news",
  "task_name": "采集上海跨境电商新闻",
  "is_incremental": 0,
  "knowledge_base_name": "电商新闻知识库",
  "knowledge_base_id": "kb_20231216_001",
  "force_upload_by_id": false,
  "cleaning_config": {
    "source": 1,
    "image_source": 1,
    "author": 1
  }
}
```

#### 参数说明
- `target`: 目标配置，如 `shanghai_cross_border_association_news`，从`/target_configs`接口获取
- `task_name`: 任务名称
- `is_incremental`: 是否增量采集，1表示增量采集，0表示全量采集，默认为0
- `knowledge_base_name`: 知识库名称（必须提供）
- `knowledge_base_id`: 知识库ID（必须提供，用于唯一标识知识库）
  - 特殊情况：当`knowledge_base_name`和`knowledge_base_id`均为"-1"时，系统将跳过知识库导入
- `force_upload_by_id`: 是否强制使用ID上传且不检查一致性，true表示强制上传并不检查历史一致性，默认为false
- `cleaning_config`: 清洗配置，JSON对象，包含以下字段：
  - `source`: 是否清洗来源信息，0表示不清洗，1表示清洗，默认为1
  - `image_source`: 是否清洗图源信息，0表示不清洗，1表示清洗，默认为1
  - `author`: 是否清洗作者信息，0表示不清洗，1表示清洗，默认为1

### 响应示例
```json
{
  "code": 200,
  "message": "采集任务创建成功，正在后台执行",
  "data": {
    "task_id": "task_20231216_001",
    "target": "shanghai_cross_border_association_news",
    "task_name": "采集上海跨境电商新闻",
    "is_incremental": 0,
    "knowledge_base_name": "电商新闻知识库",
    "knowledge_base_id": "kb_20231216_001",
    "force_upload_by_id": false,
    "cleaning_config": {
      "source": 1,
      "image_source": 1,
      "author": 1
    },
    "file_name": "task_20231216_001"
  }
}
```

### 响应字段说明
- `task_id`: 任务唯一标识符，可用于查询任务状态和下载结果
- `target`: 目标配置
- `task_name`: 任务名称
- `is_incremental`: 是否增量采集
- `knowledge_base_name`: 知识库名称
- `knowledge_base_id`: 知识库ID
- `force_upload_by_id`: 是否强制使用ID上传且不检查一致性
- `cleaning_config`: 清洗配置，包含source、image_source和author字段
- `file_name`: 结果文件名，与task_id相同

### 特殊说明
- `knowledge_base_id` 字段为必填项，用于唯一标识知识库
- 当 `force_upload_by_id` 为 false 或未提供时，系统会对同一采集模板的历史任务进行知识库ID一致性检查，如果不一致会返回错误提示
- 当 `force_upload_by_id` 为 true 时，系统不会检查历史一致性，直接使用提供的知识库ID进行上传
- 文档上传时使用`knowledge_base_id`字段进行上传
- 知识库ID不一致时会返回401错误码，包含上次使用的知识库名称和本次尝试使用的知识库名称信息
- **特殊处理**：当`knowledge_base_name`和`knowledge_base_id`均为"-1"时，系统将跳过知识库导入，仅保存到本地文件

---

## 3. 下载文件

### 接口描述
下载指定文件名的文件

### 请求信息
- **URL**: `/download`
- **方法**: `POST`

### 请求参数
```json
{
  "file_name": "task_20231216_001"
}
```

#### 参数说明
- `file_name`: 文件名，通常是任务创建时返回的task_id

### 响应
成功时返回文件内容，文件类型为`text/plain`

### 错误响应示例
```json
{
  "code": 404,
  "message": "文件不存在: task_20231216_001"
}
```

### 知识库ID不一致错误示例
```json
{
  "code": 401,
  "message": "该模板上次导入「电商新闻知识库」，本次导入「跨境电商知识库」，请确认！"
}
```

---

## 4. 获取任务列表

### 接口描述
分页获取任务列表，支持条件查询

### 请求信息
- **URL**: `/tasks`
- **方法**: `POST`

### 请求参数
```json
{
  "page": 1,
  "page_size": 10,
  "task_id": "task_202312",
  "task_name": "采集",
  "start_time": "2023-12-01",
  "end_time": "2023-12-31",
  "collection_template": "shanghai_cross_border_association_news",
  "task_type": 0,
  "task_status": "completed",
  "knowledge_base_name": "电商新闻知识库"
}
```

#### 参数说明
**分页参数**:
- `page`: 页码，从1开始，默认为1
- `page_size`: 每页大小，默认为10，最大100

**模糊匹配条件**:
- `task_id`: 任务编号（模糊匹配）
- `task_name`: 任务名称（模糊匹配）

**时间段查询条件**:
- `start_time`: 开始时间（格式：YYYY-MM-DD），查询完成时间大于等于此时间的任务
- `end_time`: 结束时间（格式：YYYY-MM-DD），查询完成时间小于等于此时间的任务

**等值匹配条件**:
- `collection_template`: 采集模板（等值匹配）
- `task_type`: 任务类型（0-全量，1-增量）（等值匹配）
- `task_status`: 任务状态（等值匹配）
- `knowledge_base_name`: 知识库（等值匹配）

### 响应示例
```json
{
  "code": 200,
  "message": "获取任务列表成功",
  "data": {
    "total": 25,
    "page": 1,
    "page_size": 10,
    "tasks": [
      {
        "task_id": "task_20231216_001",
        "task_name": "采集上海跨境电商新闻",
        "collection_template": "shanghai_cross_border_association_news",
        "task_type": 0,
        "task_status": "completed",
        "knowledge_base_name": "电商新闻知识库",
        "knowledge_base_id": "kb_20231216_001",
        "create_time": "2023-12-16 10:30:00",
        "start_time": "2023-12-16 10:30:05",
        "complete_time": "2023-12-16 10:35:20",
        "error_message": null,
        "processed_count": 120,
        "total_count": 120
      }
    ]
  }
}
```

### 响应字段说明
- `total`: 总任务数
- `page`: 当前页码
- `page_size`: 每页大小
- `tasks`: 任务列表
  - `task_id`: 任务ID
  - `task_name`: 任务名称
  - `collection_template`: 采集模板
  - `task_type`: 任务类型（0-全量，1-增量）
  - `task_status`: 任务状态
  - `knowledge_base_name`: 知识库名称
  - `knowledge_base_id`: 知识库ID
  - `create_time`: 创建时间
  - `start_time`: 开始时间
  - `complete_time`: 完成时间
  - `error_message`: 错误信息（如果有）
  - `processed_count`: 已处理数量
  - `total_count`: 总数量

---

## 时间段查询说明

`start_time` 和 `end_time` 参数允许您查询在特定时间范围内完成的所有任务。

### 查询规则
- 当只提供 `start_time` 时：查询完成时间大于等于该时间的所有任务
- 当只提供 `end_time` 时：查询完成时间小于等于该时间的所有任务
- 当同时提供 `start_time` 和 `end_time` 时：查询完成时间在此范围内的所有任务

### 时间格式
- 必须采用 `YYYY-MM-DD` 格式，例如：`2023-12-31`
- 时间范围为当天的 00:00:00 至 23:59:59

### 查询示例

**查询2023年12月完成的任务：**
```json
{
  "start_time": "2023-12-01",
  "end_time": "2023-12-31"
}
```

**查询2023年12月15日之后完成的任务：**
```json
{
  "start_time": "2023-12-15"
}
```

**查询2023年12月15日之前完成的任务：**
```json
{
  "end_time": "2023-12-15"
}
```

---

## 清洗配置详解

清洗配置允许用户精确控制需要从采集的内容中移除哪些信息。系统支持以下三种类型的清洗：

### 清洗类型说明

1. **来源信息 (source)**
   - 清除模式：文章来源、来源：、本文来自：等来源相关信息
   - 示例文本："文章来源：新华财经"、"来源：上海海关12360热线"
   
2. **图源信息 (image_source)**
   - 清除模式：图源：、图片来源：、图片来自：等图片来源信息
   - 示例文本："图源：微盟智慧零售公众号"
   
3. **作者信息 (author)**
   - 清除模式：作者：、文/、撰文：、记者等作者信息
   - 示例文本："作者：陈嘉莹"

### 配置示例

**全部开启清洗（默认）**:
```json
{
  "source": 1,
  "image_source": 1,
  "author": 1
}
```

**只清洗来源信息**:
```json
{
  "source": 1,
  "image_source": 0,
  "author": 0
}
```

**不清洗任何内容**:
```json
{
  "source": 0,
  "image_source": 0,
  "author": 0
}
```

---

## 错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 401 | 知识库不一致 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 使用示例

### 完整采集流程示例

1. **获取可用配置**
```bash
curl -X GET "http://127.0.0.1:8001/target_configs"
```

2. **创建采集任务**
```bash
curl -X POST "http://127.0.0.1:8001/collect" \
     -H "Content-Type: application/json" \
     -d '{
       "target": "shanghai_cross_border_association_news",
       "task_name": "采集上海跨境电商新闻",
       "is_incremental": 0,
       "knowledge_base_name": "电商新闻知识库",
       "knowledge_base_id": "kb_20231216_001",
       "force_upload_by_id": false,
       "cleaning_config": {
         "source": 1,
         "image_source": 1,
         "author": 1
       }
     }'
```

3. **查询任务列表**
```bash
curl -X POST "http://127.0.0.1:8001/tasks" \
     -H "Content-Type: application/json" \
     -d '{
       "page": 1,
       "page_size": 10,
       "task_status": "completed",
       "start_time": "2023-12-01",
       "end_time": "2023-12-31"
     }'
```

4. **下载采集结果**
```bash
curl -X POST "http://127.0.0.1:8001/download" \
     -H "Content-Type: application/json" \
     -d '{
       "file_name": "task_20231216_001"
     }' \
     --output result.txt
```

### 跳过知识库导入的示例

如果您只需要将采集结果保存到本地文件，而不需要上传到知识库，可以使用以下方式：

```bash
curl -X POST "http://127.0.0.1:8001/collect" \
     -H "Content-Type: application/json" \
     -d '{
       "target": "shanghai_cross_border_association_news",
       "task_name": "采集上海跨境电商新闻（仅本地保存）",
       "is_incremental": 0,
       "knowledge_base_name": "-1",
       "knowledge_base_id": "-1",
       "cleaning_config": {
         "source": 1,
         "image_source": 1,
         "author": 1
       }
     }'
```