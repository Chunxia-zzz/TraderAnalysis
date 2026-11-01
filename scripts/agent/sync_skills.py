#!/usr/bin/env python3
"""把 skills/ 物化到各 agent 的原生目录。

`skills/` 是唯一真相源；`.claude/skills/`、`.agents/skills/`、`.workbuddy/skills/`
都是生成物，**不要手改**。

默认用目录联结点（Windows `mklink /J`，无需管理员）/ 符号链接（POSIX），
保证「改副本 = 改源文件」，从根上消除「两份内容不同步」的可能。
链接不可用时用 `--copy` 兜底，此时必须靠 `--check` 发现漂移。

用法：
    python scripts/agent/sync_skills.py            # 建立/刷新链接
    python scripts/agent/sync_skills.py --check    # 校验，不一致则退出码 1
    python scripts/agent/sync_skills.py --copy     # 改为复制（兜底）
    python scripts/agent/sync_skills.py --dry-run  # 只打印将做什么
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "skills"
TARGETS = (".claude/skills", ".agents/skills", ".workbuddy/skills")


# ── 基础工具 ────────────────────────────────────────────────────────────────
def skill_dirs() -> list[Path]:
    """skills/ 下所有含 SKILL.md 的子目录（第三方技能拉下来后同样适用）。"""
    if not SRC.is_dir():
        return []
    return [d for d in sorted(SRC.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]


def is_link(path: Path) -> bool:
    """symlink 或 NTFS 联结点。注意：os.path.islink() 对 junction 返回 False。"""
    if path.is_symlink():
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, "st_reparse_tag", 0))


def points_to(link: Path, src: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(link)) == os.path.normcase(os.path.realpath(src))
    except OSError:
        return False


def make_link(link: Path, src: Path) -> None:
    if os.name == "nt":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(src)],
            capture_output=True,
        )
        if proc.returncode != 0:
            msg = (proc.stdout + proc.stderr).decode("gbk", "ignore").strip()
            raise RuntimeError(
                f"创建联结点失败：{msg}\n提示：改用 --copy 兜底，或在开发者模式下重试。"
            )
    else:
        os.symlink(src, link, target_is_directory=True)


def remove_path(path: Path) -> None:
    if is_link(path):
        try:
            os.rmdir(path)  # 联结点/目录符号链接：只删链接，不动目标
        except OSError:
            os.unlink(path)
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def manifest(root: Path) -> dict[str, str]:
    """相对路径 -> sha256，用于内容比对。"""
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            rel = f.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ── 两种模式 ────────────────────────────────────────────────────────────────
def run_sync(mode: str, dry_run: bool) -> int:
    skills = skill_dirs()
    if not skills:
        print(f"[FAIL] {rel(SRC)} 下没有任何含 SKILL.md 的技能目录", file=sys.stderr)
        return 1

    changed = 0
    for skill in skills:
        for target in TARGETS:
            parent = ROOT / target
            dest = parent / skill.name
            if mode == "link":
                if is_link(dest) and points_to(dest, skill):
                    print(f"  = {rel(dest)}（已链接）")
                    continue
                print(f"  + {rel(dest)} -> {rel(skill)}")
                if not dry_run:
                    if dest.exists() or is_link(dest):
                        remove_path(dest)
                    parent.mkdir(parents=True, exist_ok=True)
                    make_link(dest, skill)
                changed += 1
            else:
                if dest.is_dir() and not is_link(dest) and manifest(dest) == manifest(skill):
                    print(f"  = {rel(dest)}（已一致）")
                    continue
                print(f"  ~ {rel(dest)}（复制）")
                if not dry_run:
                    if dest.exists() or is_link(dest):
                        remove_path(dest)
                    parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(skill, dest)
                changed += 1

    verb = "将改动" if dry_run else "已处理"
    print(f"\n{verb} {changed} 项（{len(skills)} 个技能 × {len(TARGETS)} 个目标目录）")
    return 0


def run_check() -> int:
    skills = skill_dirs()
    if not skills:
        print(f"[FAIL] {rel(SRC)} 下没有任何含 SKILL.md 的技能目录", file=sys.stderr)
        return 1

    problems: list[str] = []
    for skill in skills:
        src_manifest = manifest(skill)
        for target in TARGETS:
            dest = ROOT / target / skill.name
            if not dest.exists() and not is_link(dest):
                problems.append(f"{rel(dest)}：缺失（应指向 {rel(skill)}）")
                continue
            if is_link(dest):
                if not points_to(dest, skill):
                    problems.append(f"{rel(dest)}：链接指向 {os.path.realpath(dest)}，应为 {rel(skill)}")
                continue
            diff = {k for k in src_manifest if src_manifest[k] != manifest(dest).get(k)}
            extra = set(manifest(dest)) - set(src_manifest)
            if diff or extra:
                detail = f"{len(diff)} 个文件内容不同" if diff else ""
                if extra:
                    detail += f"{'，' if detail else ''}{len(extra)} 个多余文件"
                problems.append(f"{rel(dest)}：副本与源不一致（{detail}）")

    if problems:
        print("[FAIL] 技能目录与 skills/ 不一致：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\n处理：跑一次 `python scripts/agent/sync_skills.py` 重新生成。"
              "\n若你确实是在原生目录里改的，先把改动同步回 skills/ 再生成。", file=sys.stderr)
        return 1

    print(f"[OK] {len(skills)} 个技能 × {len(TARGETS)} 个目标目录，全部一致")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把 skills/ 物化到各 agent 原生目录")
    ap.add_argument("--check", action="store_true", help="只校验，不一致则退出码 1")
    ap.add_argument("--copy", action="store_true", help="用复制代替链接（兜底）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将做什么")
    args = ap.parse_args()

    print(f"源：{rel(SRC)}   目标：{', '.join(TARGETS)}\n")
    if args.check:
        return run_check()
    return run_sync("copy" if args.copy else "link", args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
