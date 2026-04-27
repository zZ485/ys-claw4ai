# YS-Crawl4AI 环境依赖镜像
# 构建命令: docker build -t ys-crawl4ai-env .
# 代码通过 -v 挂载，不打包进镜像，方便后续迭代

FROM python:3.11-slim

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 Playwright Chromium 浏览器及其所有系统依赖（关键步骤）
RUN playwright install --with-deps chromium

# 创建数据持久化目录
RUN mkdir -p /app/data /app/results /app/logs

EXPOSE 8001

# 启动服务，监听所有网络接口
CMD ["python", "start_server.py", "--host", "0.0.0.0", "--port", "8001"]
