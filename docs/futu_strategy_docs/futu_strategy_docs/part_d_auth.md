# 简易认证体系 技术设计文档

> 最后更新：2026-05-06 | 版本：v1.0 | 状态：P0 已实现

---

## 1. 概述

### 1.1 目标

为上云部署提供最小化认证体系，阻止未授权的公网访问。当前仅需支持单管理员账号，架构上预留多用户/会员扩展能力。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| 最小化 | v1 只做登录 + token 校验，不做注册/邀请/OAuth |
| 不侵入 | 现有 API 逻辑不改，只加一层中间件拦截 |
| 可扩展 | users 表 + role 字段，未来加会员只需加角色 |
| 标准化 | JWT Bearer Token，前端对接无学习成本 |

---

## 2. 数据模型

### 2.1 新表：`users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,          -- bcrypt hash
    role        TEXT NOT NULL DEFAULT 'member',  -- admin / member
    is_active   INTEGER NOT NULL DEFAULT 1,      -- 0=禁用, 1=启用
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_login  TEXT
);
```

### 2.2 角色定义

| 角色 | 权限 | 说明 |
|------|------|------|
| `admin` | 全部读写 | 管理员（你自己） |
| `member` | 只读 | 未来会员，可查看数据但不能修改标的池 |

### 2.3 权限矩阵

| 端点类型 | admin | member | 未登录 |
|---------|-------|--------|--------|
| `GET /api/*`（查询类） | ✅ | ✅ | ❌ 401 |
| `POST/PATCH/DELETE /api/watchlist/*` | ✅ | ❌ 403 | ❌ 401 |
| `POST /api/watchlist/refresh-snapshot` | ✅ | ❌ 403 | ❌ 401 |
| `GET /api/stock-filter/*` | ✅ | ✅ | ❌ 401 |
| `POST /api/auth/login` | 🔓 公开 | 🔓 公开 | 🔓 公开 |
| `GET /health` | 🔓 公开 | 🔓 公开 | 🔓 公开 |

---

## 3. API 设计

### 3.1 登录

```
POST /api/auth/login
```

**Request Body:**
```json
{
  "username": "admin",
  "password": "your_password"
}
```

**Response 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 604800,
  "role": "admin"
}
```

**Response 401:**
```json
{"data": null, "message": "Invalid username or password"}
```

### 3.2 Token 使用

所有需要认证的请求在 Header 中携带：

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### 3.3 获取当前用户信息

```
GET /api/auth/me
```

**Response 200:**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "created_at": "2026-05-06T00:00:00",
  "last_login": "2026-05-06T10:30:00"
}
```

### 3.4 修改密码（admin）

```
POST /api/auth/change-password
```

**Request Body:**
```json
{
  "old_password": "current",
  "new_password": "new_secure_password"
}
```

**Response 200:**
```json
{"message": "Password updated"}
```

---

## 4. JWT 规格

### 4.1 Token 结构

```python
# Header
{"alg": "HS256", "typ": "JWT"}

# Payload
{
  "sub": "admin",          # username
  "role": "admin",         # 角色
  "exp": 1717200000,       # 过期时间戳
  "iat": 1716595200        # 签发时间戳
}
```

### 4.2 配置项

```python
# 环境变量或 .env 文件
JWT_SECRET_KEY = "随机生成的密钥"    # 部署时必须设置
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7                   # Token 有效期 7 天
```

> **重要：** `JWT_SECRET_KEY` 不能硬编码在代码中，必须通过环境变量注入。

---

## 5. 实现细节

### 5.1 依赖

```
python-jose[cryptography]    # JWT 编解码
passlib[bcrypt]              # 密码哈希
python-dotenv                # .env 文件加载（可选）
```

### 5.2 核心模块

```python
# auth.py (新文件)

from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

pwd_context = CryptContext(schemes=["bcrypt"])
security = HTTPBearer()

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {"sub": username, "role": role, "exp": expire, "iat": datetime.utcnow()}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """FastAPI 依赖：解析并验证 token，返回用户信息"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = query_user_by_username(username)
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    return user

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI 依赖：要求 admin 角色"""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

### 5.3 中间件集成

```python
# api_server.py 中的使用方式

from auth import get_current_user, require_admin

# 只读端点 —— 登录即可访问
@app.get("/api/scores/overview")
def scores_overview(user: dict = Depends(get_current_user)):
    ...

# 写端点 —— 仅 admin
@app.post("/api/watchlist")
def add_stock(body: ..., user: dict = Depends(require_admin)):
    ...

# 公开端点 —— 无需认证
@app.get("/health")
def health():
    ...

@app.post("/api/auth/login")
def login(body: ...):
    ...
```

### 5.4 Storage 层新增

```python
# auth_storage.py 或 storage.py 中新增

def query_user_by_username(username: str) -> dict | None:
    """根据用户名查询用户"""
    ...

def create_user(username: str, password_hash: str, role: str = "member") -> int:
    """创建用户，返回 id"""
    ...

def update_last_login(username: str) -> None:
    """更新最后登录时间"""
    ...

def update_password(username: str, new_hash: str) -> None:
    """更新密码"""
    ...
```

---

## 6. 初始化管理员账号

### 6.1 CLI 命令

```python
@app.command()
def create_admin(
    username: str = typer.Option("admin", help="管理员用户名"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="管理员密码"),
):
    """创建管理员账号（首次部署时使用）"""
```

### 6.2 使用方式

```bash
# 首次部署
trader-analysis create-admin --username admin
# 提示输入密码（不回显）
Password: ********

# 输出
Admin account 'admin' created successfully.
```

---

## 7. 公开端点白名单

以下端点不需要 token：

```python
PUBLIC_PATHS = [
    "/health",
    "/api/auth/login",
    "/docs",            # Swagger UI（生产环境可关闭）
    "/openapi.json",    # OpenAPI schema
]
```

其余所有 `/api/*` 端点默认需要认证。

---

## 8. 前端对接指南

### 8.1 登录流程

```
1. POST /api/auth/login {username, password}
2. 收到 access_token
3. 存入 localStorage 或内存
4. 后续所有请求 Header: Authorization: Bearer <token>
5. 收到 401 时跳转登录页
```

### 8.2 角色判断

```javascript
// 登录响应中包含 role
const { access_token, role } = await login(username, password)

// 前端根据 role 控制 UI
if (role === 'admin') {
  // 显示编辑按钮、删除按钮
} else {
  // 只显示查看
}
```

---

## 9. 安全注意事项

| 事项 | 措施 |
|------|------|
| JWT 密钥泄露 | 通过环境变量注入，不提交到仓库 |
| 暴力破解 | v1 暂不做限频（单用户场景），v2 可加 rate limit |
| Token 过期 | 7 天有效期，过期需重新登录 |
| HTTPS | 部署时 Nginx/Caddy 反代加 TLS，不在应用层处理 |
| 密码强度 | v1 不做前端校验，后续可加最小长度要求 |
| CORS | 生产环境收紧 `allow_origins` 为前端域名 |

---

## 10. 未来扩展（v2 会员体系）

当功能稳定后，扩展为会员项目只需：

```
1. 新增 POST /api/auth/register（或邀请码注册）
2. users 表加字段：invite_code, expire_at, plan(free/pro)
3. 权限矩阵加列：free 只看部分数据，pro 看全部
4. 可选：接入支付（Stripe/支付宝）管理 plan 状态
```

当前 JWT + role 架构天然支持这些扩展，无需重构。

---

## 11. 实现优先级

| 阶段 | 范围 | 验收标准 |
|------|------|---------|
| **P0** | users 表 + login + token 校验 + create-admin CLI | 未登录访问任何 API 返回 401 |
| **P1** | 角色权限（admin/member 区分） | member 无法调用写接口 |
| **P2** | change-password + 密码强度 | 可在线改密码 |
| **P3** | 注册/邀请码 + 会员体系 | 多用户可用 |

---

## 12. 验收标准（P0）

- [ ] `trader-analysis create-admin` 成功创建账号
- [ ] `POST /api/auth/login` 正确用户名密码返回 token
- [ ] `POST /api/auth/login` 错误密码返回 401
- [ ] 携带有效 token 访问 `GET /api/watchlist` 返回 200
- [ ] 不带 token 访问 `GET /api/watchlist` 返回 401
- [ ] 过期 token 返回 401
- [ ] `GET /health` 无需 token 正常返回
- [ ] `JWT_SECRET_KEY` 从环境变量读取，代码中无硬编码
