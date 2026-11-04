# Tasks: 后端只在新版本检查通过后上线

**Input**: `spec.md` / `plan.md`（本目录）

## Phase 1: 前置核对（已完成）

- [x] **T001** 读服务器 hook：`checkout -f main` + `systemctl restart`，**不装依赖**、无 `set -e`
- [x] **T002** 服务器**连不上 GitHub**（curl 超时）→ 不能改成「服务器 pull」
- [x] **T003** 服务器**连不上 pypi.org**，但 `mirrors.aliyun.com/pypi/simple` 返回 200；
      venv 的 `pip config` 已指向该镜像 → 依赖可以在服务器装
- [x] **T004** 环境事实：工作树 `/opt/trader-analysis`（含 `.venv` Python 3.11.13、`.env`、`data/`）；
      裸库 `/opt/git/trader-analysis.git`；systemd `trader-api`（`ExecStart=.venv/bin/python -m trader_analysis serve`）

## Phase 2: 部署 job

- [ ] **T005** `ci.yml` 新增 `deploy`：`needs: [check]`、仅 `push main`、`concurrency: deploy-main`
- [ ] **T006** checkout 用 `fetch-depth: 0`；记录 `PREV_SHA=$(git rev-parse HEAD~1)` 到 job env
- [ ] **T007** 主机公钥固化到 `.github/deploy_known_hosts`（复制前端的同内容文件）
- [ ] **T008** Prepare SSH：`DEPLOY_SSH_KEY` → `~/.ssh/deploy`（600）+ `ssh-keygen -y` 校验 + 缺 secret 明确失败
- [ ] **T009** 推送 commit 到裸库：`git push ssh://root@$HOST$BARE HEAD:main`（hook 已停用，不会重复部署）
- [ ] **T010** 单连接部署：`checkout -f <sha>` → 依赖有变更则 `pip install -r requirements.txt` → `systemctl restart`
- [ ] **T011** 健康检查：轮询 `GET /health` ≤40s，200 才算通过
- [ ] **T012** `if: failure()` 回滚：`checkout -f <PREV_SHA>` → 必要时 pip → restart → 再轮询

## Phase 3: 单一部署路径

- [ ] **T013** 备份服务器 hook 为 `post-receive.bak-20261104`，替换为「打印说明 + exit 0」
- [ ] **T014** 本地 remote 拆分：`origin` 只留 GitHub，服务器地址移到 `deploy`

## Phase 4: 文档

- [ ] **T015** `docs/guides/ops/README.md`：后端部署链路改为 Actions → bare repo → checkout/pip/restart/健康检查
- [ ] **T016** `README.md`：上线方式、回滚命令
- [ ] **T017** `AGENTS.md`：§5 硬性约定（禁止手工覆盖工作树、回滚优先 git checkout）、§9 常用命令

## Phase 5: 验证

- [x] **T018** 本地模拟：同一段命令跑通「checkout → 跳过依赖 → restart」，`/health` 第 1 次 502、第 2 次 200
      （证明必须轮询，一次性检查会误判）
- [x] **T019** 远端：`3d83e12` 部署绿（deploy 19s），工作树 HEAD = 推送 sha，服务 active，`/health` 200
- [x] **T020** 依赖判定：改 `requirements.txt` 注释后 Deploy 步骤 **5s → 157s**（走 pip + 阿里云镜像），
      health 仍通过；改回后再次 157s
- [ ] **T021** 回滚：**未端到端验证**，见下方「探针两次都被 lint 拦下」
- [x] **T022** SC 逐条回填（见下表）

## 依赖关系

```
T005-T008 → T009-T012 → T013-T014 → T015-T017 → T018-T022
```

## 验证记录（2026-11-04 实测）

| 项 | 实测 | 结论 |
|---|---|---|
| SC-001 push → /health 200 | 一次完整运行：check 双平台 81s/50s + deploy 19s ≈ **2.5 分钟** | ✅ ≤5min |
| SC-002 检查红则不部署 | 两次探针提交（`96f13c5` E402、`965e97c` invalid-syntax）check 红后 deploy 直接 skipped，裸库 main 与工作树 HEAD **都没动** | ✅ 实测 |
| SC-003 失败自动回滚 | **未验证**（探针没走到 deploy）。已单独验证：守卫逻辑（worktree≠target → 跳过）、回滚命令（checkout+restart）与部署用的是同一组命令、健康检查轮询可用 | ⚠️ 部分 |
| SC-004 deploy ≤90s | 无依赖变更 **19s**；有依赖变更 **157s**（pip 装 53 个包） | ✅ 常态达标；依赖变更时会超 |
| SC-005 依赖未变则不装 | 无变更的运行 Deploy 5s；有变更 157s，差异显著 | ✅ |
| SC-006 推裸库不上线 | hook 已停用；推 `deploy` remote 只更新裸库（hook 打印移交说明） | ✅ |

### 首跑失败与修复（两处）

1. **`Push commit to bare repo` 失败：Permission denied (publickey)**
   `git push` 自己起 ssh 时不认前面步骤的 `-i ~/.ssh/deploy`，而 runner 上没有任何默认身份。
   修复：给该步骤设 `GIT_SSH_COMMAND="ssh -i ~/.ssh/deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes ..."`。
2. **推送失败时回滚仍然执行**，白白重启一次服务（工作树其实没变）。
   修复：回滚前先比对工作树 HEAD 与 `TARGET_SHA`，不同则跳过。

### 探针两次都被 lint 拦下（回滚没测成，但反证门禁有效）

想验证「启动失败 → 自动回滚」，两次设计都被 `check` 挡住，deploy 从未执行：

| 探针 | 被什么拦下 |
|---|---|
| `raise` 写在 `__main__.py` 模块顶层 | ruff **E402**（import 不在文件顶部） |
| 缩进与项目 3 空格风格不一致 | ruff **invalid-syntax** |

结论：**「检查不过就不上线」这条链是真的通的**，但也因此没能端到端验证回滚。
后续若要做，建议不要走主分支：直接往裸库推一个坏 sha，再手工触发一次 checkout+restart，
观察 `/health` 失败后执行回滚命令即可（命令与 workflow 内一致）。

### 顺带发现

- 服务器**无外网**（GitHub / pypi.org 都不通），仅阿里云镜像可用 → 依赖只能走 `mirrors.aliyun.com`。
- 服务器 Python **3.11.13**、CI **3.13**：本次未消除差异，`requires-python >=3.10` 兜底。
- `gitleaks-action@v2`（前端已升 v3）：本次未动，记入技术债。
