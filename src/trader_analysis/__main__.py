raise RuntimeError("rollback probe 2026-11-04：故意让服务起不来，用于验证自动回滚")
from .cli import app


def main() -> None:
   app()


if __name__ == "__main__":
   main()
