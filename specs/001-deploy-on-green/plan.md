# Implementation Plan: 后端只在新版本检查通过后上线

**Branch**: `001-deploy-on-green` | **Date**: 2026-11-04 | **Spec**: [`spec.md`](./spec.md)

## Summary

在现有 `ci.yml` 增加 `deploy` job：`needs: [check]`、仅 `push main`、job 级串行。
它先把该 commit 推到服务器裸库（保持 git 语义与历史），再经**一条** SSH 连接执行
「checkout → 按需 pip install → 重启 → 健康检查」，失败则回滚到上一个 sha。
同时停用服务器 hook 的自动部署，并把本地 `origin` 的服务器推送地址拆成 `deploy`。

## Technical Context

**Language/Version**: YAML（GitHub Actions）+ 服务器 shell；服务本身 Python 3.11.13（服务器）/ 3.13（CI）

**Primary Dependencies**: 无新增仓库依赖；服务器侧用 git / systemd / 已配好的阿里云 PyPI 镜像

**Storage**: 工作树 `/opt/trader-analysis`（含 `.venv` `.env` `data`）；裸库 `/opt/git/trader-analysis.git`

**Testing**: 部署后轮询 `GET /health`；用「改注释触发 requirements 变更」「坏 import 触发回滚」做故障注入

**Target Platform**: GitHub 托管 runner（ubuntu-latest）+ 单台 ECS（Alibaba Cloud Linux 3）

**Project Type**: 常驻服务发布（systemd）

**Performance Goals**: deploy ≤ 90s；push → /health 200 ≤ 5min；重启不可用窗口 2~3s

**Constraints**:
- 服务器**不能访问 GitHub**（不能 pull），也**不能访问 pypi.org**（但阿里云镜像可用）
- 服务器 Python 3.11，CI 3.13；本 feature 不消除差异
- 不改 systemd unit、不改 Nginx

**Scale/Scope**: 单机、单实例

## Constitution Check

| 原则 | 判定 | 说明 |
|---|---|---|
| I. 两套信号体系不可合并 | ✅ 不冲突 | 不触碰任何计算逻辑；部署的是已通过 `check` 的同一 commit |
| II. 口径是事实，不是可调参数 | ✅ 不冲突 | 不改口径、不改配置；`.env` 与 `data/` 不在 git 跟踪范围，checkout 不触碰 |
| III. 术语精确 | ✅ 适用 | 文档统一用「上线/部署」「工作树」「裸库」，不把「推送」说成「部署」——本次正因二者混同才有绕过门禁的问题 |
| IV. 单一真相源 | ✅ 强化 | 部署逻辑从**服务器上的 hook 文件**（不在版本控制里）搬到 `ci.yml`（可审阅、可回滚）；hook 只留一句说明 |
| V. 文档与代码同时为真 | ✅ 适用 | `docs/guides/ops/README.md` 的部署链路、`AGENTS.md`、`README.md` 同步更新；前端 004 留下的勘误行保持不动 |
| VI. 规范先行 | ✅ 满足 | 本 spec 先于任何 workflow 改动 |
| §二 安全与数据边界 | ✅ 满足 | 复用既有部署密钥（仅存 GitHub Secrets）；仓库内只出现变量名；主机公钥固化（公钥非机密）；不写账户/仓位 |
| §三 质量门 | ✅ 强化 | 部署前必须 `scripts/check.sh` 绿（双平台）；部署后追加 `/health` 轮询 |

无违规项 → Complexity Tracking 留空。

## 技术方案

### 1. 流水线编排

```yaml
jobs:
  check:      # 已有：双平台 lint + pytest + 覆盖率
  security:   # 已有：gitleaks
  deploy:
    needs: [check]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    concurrency: { group: deploy-main, cancel-in-progress: false }
    steps:
      1. checkout (fetch-depth: 0)      # 需要历史：算上一个 sha、判断依赖变更、推送
      2. Prepare SSH                    # 私钥 + 固化主机公钥（.github/deploy_known_hosts）
      3. Push commit to bare repo       # git push ssh://root@host/opt/git/trader-analysis.git HEAD:main
      4. Deploy (single SSH session)    # checkout -f <sha> → [pip install] → systemctl restart
      5. Health check                   # 轮询 /health 直到 200，上限 40s
      6. Rollback (if failure)          # checkout -f <prev sha> → [pip install] → restart → 再检查
```

### 2. 为什么「先推到裸库」而不是直接 tar 覆盖

Python 服务的工作树里有 `.venv`、`.env`、`data/`、`logs/`，用 tar 覆盖有两个问题：
**删除的文件不会被删掉**（残留旧模块可能被 import 到）、**无法保证与某个 commit 精确对应**。
`git checkout -f <sha>` 两个都解决，且在裸库里天然留有历史，回滚只需换一个 sha。

### 3. 依赖安装的判定

```bash
changed=$(git diff --name-only "$PREV_SHA" "$SHA" | grep -E '^requirements(-dev)?\.txt$' || true)
```

- 有变更 → `pip install -q -r requirements.txt`（走已配置的阿里云镜像）
- 无变更 → 跳过（SC-005）
- **安装失败 → `set -e` 直接中止，不重启**（FR-004）——旧进程继续对外服务

### 4. 重启与健康检查

`systemctl restart trader-api` 是同步返回的，但进程真正就绪需要时间，所以：

```bash
for i in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://$DEPLOY_HOST/health || true)
  [ "$code" = "200" ] && { echo "健康检查通过（第 ${i} 次）"; exit 0; }
  sleep 2
done
echo "::error::/health 40s 内未返回 200"; exit 1
```

### 5. 回滚

```bash
ssh: git --git-dir=BARE --work-tree=WORKTREE checkout -f "$PREV_SHA"
     [依赖变更过] pip install -r requirements.txt
     systemctl restart trader-api
     再轮询 /health
```

`PREV_SHA=$(git rev-parse HEAD~1)` 在 checkout 阶段记录，通过 job 级 `env` 传给后续步骤。

### 6. 密钥与权限

| 项 | 位置 | 说明 |
|---|---|---|
| 私钥 | 后端仓库 Secrets：`DEPLOY_SSH_KEY` | **复用前端那把**（同一服务器、同一 root）；后端仓库要单独添加一次，GitHub 的 Secrets 不跨仓库共享 |
| 公钥 | 服务器 `/root/.ssh/authorized_keys` | 已在 004 追加，无需重复 |
| 主机公钥 | `.github/deploy_known_hosts`（本仓库一份） | 与前端同内容；`StrictHostKeyChecking=yes` |

### 7. 已知代价与不做的事

| 项 | 决定 |
|---|---|
| 重启期间 2~3 秒不可用 | 接受。多实例/蓝绿属独立需求 |
| 服务器 Python 3.11 vs CI 3.13 | 记录不解决；若要消除，应把 CI 矩阵加 3.11 并升服务器，属独立 spec |
| 依赖装的包与 CI 装的包是否一致 | 同一份 `requirements.txt`，不同解释器/平台；**不承诺 wheel 完全一致**，只承诺版本约束一致 |
| `gitleaks-action@v2`（前端已升 v3） | 本次不动，避免混入无关改动；记入技术债 |

## Project Structure

```text
.github/workflows/ci.yml        # 改：新增 deploy job
.github/deploy_known_hosts      # 新增：服务器主机公钥（与前端仓库同内容）
specs/001-deploy-on-green/
├── spec.md / plan.md / tasks.md
└── checklists/requirements.md
README.md                       # 改：上线方式与回滚
AGENTS.md                       # 改：§5 部署约定、§9 命令
docs/guides/ops/README.md       # 改：部署链路（前端勘误之下的后端段落）
```

服务器侧（不在仓库内，必须与文档一致）：`/opt/git/trader-analysis.git/hooks/post-receive`。
