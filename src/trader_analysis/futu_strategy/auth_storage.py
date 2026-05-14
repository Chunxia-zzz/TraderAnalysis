"""用户认证存储层。

管理 users 表的 DDL 与 CRUD 操作。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from trader_analysis.futu_strategy import config

_CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login    TEXT
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_users_table() -> None:
    """创建 users 表（幂等）。"""
    conn = _get_conn()
    try:
        conn.executescript(_CREATE_USERS_TABLE_SQL)
    finally:
        conn.close()


def create_user(username: str, password_hash: str, role: str = "member") -> int:
    """创建用户，返回 id。"""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def query_user_by_username(username: str) -> dict | None:
    """根据用户名查询用户，返回 dict 或 None。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, role, is_active, created_at, last_login "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def update_last_login(username: str) -> None:
    """更新最后登录时间。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    try:
        conn.execute("UPDATE users SET last_login = ? WHERE username = ?", (now, username))
        conn.commit()
    finally:
        conn.close()


def update_password(username: str, new_hash: str) -> None:
    """更新密码。"""
    conn = _get_conn()
    try:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username))
        conn.commit()
    finally:
        conn.close()


def user_exists(username: str) -> bool:
    """检查用户是否已存在。"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        return row is not None
    finally:
        conn.close()


def list_users() -> list[dict]:
    """列出所有用户（不含密码哈希）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, username, role, is_active, created_at, last_login FROM users ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_user_active(username: str, is_active: bool) -> bool:
    """启用/禁用用户，返回是否找到该用户。"""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE users SET is_active = ? WHERE username = ?",
            (1 if is_active else 0, username),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_user(username: str) -> bool:
    """删除用户，返回是否找到该用户。"""
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
