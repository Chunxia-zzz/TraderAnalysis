#!/usr/bin/env python3
"""按官方地址拉取富途第三方技能（futuapi / install-opend）。

**这两个技能不入库**：它们由富途团队开发，随包只提供免责声明
（`LEGAL_Futu_api_cn.md`），没有可再分发的授权。把 420 KB 官方脚本
逐字推进公开仓库属于未授权再分发，因此改为「用时从官方拉」。

拉取位置：`skills/futuapi/`、`skills/install-opend/`（已被 .gitignore 忽略，`skills/` 本体保留）
拉完记得跑 `python scripts/agent/sync_skills.py` 让 agent 能发现它们。

用法：
    python scripts/agent/fetch_futu_skills.py
    python scripts/agent/fetch_futu_skills.py --force     # 覆盖已有
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

URL = "https://openapi.futunn.com/skills/opend-skills.zip"
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "skills"
WANTED = ("futuapi", "install-opend")


def download(dest: Path) -> Path:
    print(f"下载 {URL}")
    with urllib.request.urlopen(URL, timeout=120) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
    print(f"  已保存 {dest.stat().st_size / 1024:.0f} KB")
    return dest


def find_skills_dir(extracted: Path) -> Path | None:
    """官方包里技能放在 `skills/` 下；容忍嵌套一层。"""
    for candidate in [extracted / "skills", *extracted.glob("*/skills")]:
        if candidate.is_dir() and any((candidate / name).is_dir() for name in WANTED):
            return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="拉取富途第三方技能到 skills/（不入库）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的目录")
    args = ap.parse_args()

    SRC.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = download(tmp_path / "opend-skills.zip")
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_path / "extracted")

            pkg = find_skills_dir(tmp_path / "extracted")
            if pkg is None:
                print("[FAIL] 压缩包里没找到 skills/futuapi 或 skills/install-opend，"
                      "官方结构可能变了，请检查下载内容。", file=sys.stderr)
                return 1

            copied = 0
            for name in WANTED:
                src = pkg / name
                if not src.is_dir():
                    print(f"  [skip] {name}（包内不存在）")
                    continue
                dest = SRC / name
                if dest.exists():
                    if not args.force:
                        print(f"  [skip] skills/{name} 已存在（加 --force 覆盖）")
                        continue
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                print(f"  [ok] skills/{name}")
                copied += 1

            legal = pkg.parent / "LEGAL_Futu_api_cn.md"
            if not legal.exists():
                legal = pkg / "LEGAL_Futu_api_cn.md"
            if legal.exists():
                shutil.copy2(legal, SRC / "LEGAL_Futu_api_cn.md")
                print("  [ok] skills/LEGAL_Futu_api_cn.md")

    except Exception as exc:  # 网络/解压失败都归到这里，给出可操作提示
        print(f"[FAIL] 拉取失败：{exc}", file=sys.stderr)
        print("提示：该地址需要外网；失败时不影响自研技能，"
              "只是晨星核对、复权核对等用到富途脚本的步骤不可用。", file=sys.stderr)
        return 1

    print(f"\n完成，新增 {copied} 个技能。下一步：python scripts/agent/sync_skills.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
