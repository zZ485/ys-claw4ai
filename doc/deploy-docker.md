# Docker 部署指南

## 策略说明

采用「环境镜像 + 代码挂载」的方式部署：

- **环境镜像**：包含 Python 运行时、pip 依赖、Playwright Chromium 浏览器及其系统依赖
- **代码挂载**：项目代码通过 `-v` 从宿主机挂载到容器内，修改代码后重启容器即可生效，无需重新构建镜像

## 部署步骤

### 1. 构建环境镜像（仅需一次）

在项目根目录执行：

```bash
docker build -t ys-crawl4ai-env .
```

> 当 `requirements.txt` 有变更时需要重新构建镜像。

### 2. 启动容器

将下面命令中的 `/path/to/ys-claw4ai` 替换为服务器上的实际项目路径，然后执行：

```bash
docker run -d --name ys-crawl4ai --restart unless-stopped --shm-size=2g -p 8001:8001 -v /path/to/ys-claw4ai:/app -v crawl4ai-data:/app/data -v crawl4ai-results:/app/results -v crawl4ai-logs:/app/logs ys-crawl4ai-env
```

**参数说明：**

| 参数 | 说明 |
|---|---|
| `-d` | 后台运行 |
| `--name ys-crawl4ai` | 容器名称 |
| `--restart unless-stopped` | 自动重启（服务器重启后自动恢复） |
| `--shm-size=2g` | **关键**：分配 2GB 共享内存给 Chromium，缺少会导致浏览器崩溃 |
| `-p 8001:8001` | 端口映射 |
| `-v /path/to/ys-claw4ai:/app` | 挂载项目代码（修改代码后重启容器生效） |
| `-v crawl4ai-data:/app/data` | 持久化数据库文件（named volume） |
| `-v crawl4ai-results:/app/results` | 持久化采集结果（named volume） |
| `-v crawl4ai-logs:/app/logs` | 持久化日志文件（named volume） |

### 3. 验证服务

```bash
# 查看容器日志
docker logs -f ys-crawl4ai

# 测试接口
curl http://localhost:8001/target_configs
```

服务启动后访问 `http://服务器IP:8001/docs` 查看 API 文档。

## 日常迭代

### 更新代码

直接修改宿主机上的项目文件，然后重启容器：

```bash
docker restart ys-crawl4ai
```

### 更新依赖

修改 `requirements.txt` 后，需要重新构建镜像并重启：

```bash
docker build -t ys-crawl4ai-env . && docker stop ys-crawl4ai && docker rm ys-crawl4ai && docker run -d --name ys-crawl4ai --restart unless-stopped --shm-size=2g -p 8001:8001 -v /path/to/ys-claw4ai:/app -v crawl4ai-data:/app/data -v crawl4ai-results:/app/results -v crawl4ai-logs:/app/logs ys-crawl4ai-env
```

### 查看日志

```bash
docker logs -f ys-crawl4ai
```

### 进入容器调试

```bash
docker exec -it ys-crawl4ai bash
```

### 停止 / 删除容器

```bash
docker stop ys-crawl4ai && docker rm ys-crawl4ai
```

## 注意事项

1. **Playwright 浏览器已内置**：镜像构建时已安装 Chromium 及其所有系统依赖，无需在容器内再次执行 `playwright install`
2. **共享内存**：`--shm-size=2g` 是必需的，否则 Chromium 会因共享内存不足而崩溃（这是 Docker 部署 Playwright 的常见坑）
3. **数据持久化**：数据库、采集结果、日志均通过 named volume 持久化，容器删除后数据不会丢失
4. **代码挂载会覆盖镜像内的文件**：挂载 `/app` 后，容器内 `/app` 目录完全由宿主机文件决定，所以 `requirements.txt` 的变更也需要在宿主机上生效
