"""认证核心逻辑。

JWT 签发/验证、密码哈希、FastAPI 依赖注入。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.auth_storage import query_user_by_username

# ── 密码哈希 ──────────────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Bearer Token 提取 ─────────────────────────────────────────────────────────
security = HTTPBearer(auto_error=True)


# ── Pydantic Models ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ── 密码工具 ──────────────────────────────────────────────────────────────────
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# ── JWT 工具 ──────────────────────────────────────────────────────────────────
def _check_secret() -> str:
    if not config.JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY 环境变量未设置。"
            "请设置后重启服务：export JWT_SECRET_KEY=$(python -c \"import secrets; print(secrets.token_hex(32))\")"
        )
    return config.JWT_SECRET_KEY


def create_access_token(username: str, role: str) -> str:
    secret = _check_secret()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=config.JWT_EXPIRE_DAYS)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, secret, algorithm=config.JWT_ALGORITHM)


# ── FastAPI 依赖 ──────────────────────────────────────────────────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """解析并验证 JWT，返回用户 dict。未通过则抛 401。"""
    secret = _check_secret()
    token = credentials.credentials
    try:
        payload = jwt.decode(token, secret, algorithms=[config.JWT_ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )

    user = query_user_by_username(username)
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled"
        )
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求 admin 角色，否则 403。"""
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
