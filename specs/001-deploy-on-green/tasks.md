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

- [ ] **T018** 本地模拟：用部署 job 的同一段命令跑一次（checkout + restart + health）
- [ ] **T019** 远端：推送后 deploy 绿，`/health` 200，工作树 `git rev-parse HEAD` = 部署 sha
- [ ] **T020** 依赖判定：改 requirements 注释 → 日志出现 pip；改 .py → 日志无 pip
- [ ] **T021** 回滚：注入坏 import → 自动回滚，`/health` 恢复 200
- [ ] **T022** SC 逐条回填

## 依赖关系

```
T005-T008 → T009-T012 → T013-T014 → T015-T017 → T018-T022
```
