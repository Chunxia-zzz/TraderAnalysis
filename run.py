"""
本地调试启动脚本

用法：
    python run.py            # 默认 0.0.0.0:8000，开启热重载
    python run.py --port 9000
    python run.py --no-reload
"""
import argparse
import os
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """简单加载 .env 文件（无需安装 python-dotenv）"""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)  # setdefault: 不覆盖已有环境变量


def main() -> None:
    parser = argparse.ArgumentParser(description="TraderAnalysis 本地调试服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认 8000)")
    parser.add_argument("--no-reload", action="store_true", help="关闭热重载")
    args = parser.parse_args()

    # 加载 .env（优先于脚本内默认值，但低于已有环境变量）
    load_dotenv(Path(".env.example"))  # 先加载示例默认值
    load_dotenv(Path(".env"))          # 再用 .env 覆盖（如有）

    import uvicorn
    uvicorn.run(
        "trader_analysis.api.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        reload_dirs=["src"],
        log_level="info",
    )


if __name__ == "__main__":
    main()
