import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def start_server(
    host="127.0.0.1", port=8000, workers=1, reload=False, log_level="info"
):
    import uvicorn

    print(f"监听地址: http://{host}:{port}")
    print(f"API 文档地址: http://{host}:{port}/docs")

    from crawler_api import app

    uvicorn.run(
        app, host=host, port=port, reload=reload, log_level=log_level, workers=1
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="启动 Crawl4AI API 服务器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument(
        "--reload", action="store_true", help="启用自动重载（开发模式）"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
        help="日志级别",
    )

    args = parser.parse_args()

    start_server(
        host=args.host,
        port=args.port,
        workers=1,
        reload=args.reload,
        log_level=args.log_level,
    )
