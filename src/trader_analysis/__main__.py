from .cli import app


def main() -> None:
   # 探针（2026-11-04）：只有在真正 start 服务时抛错，lint 与 pytest 都不受影响，
    # 用来验证 deploy 的自动回滚。验证完毕立即 revert。
    raise RuntimeError("rollback probe：故意让服务起不来")
   app()


if __name__ == "__main__":
   main()
