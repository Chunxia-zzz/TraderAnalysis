# Feature Specification: 后端只在新版本检查通过后上线

**Feature Branch**: `001-deploy-on-green`

**Created**: 2026-11-04

**Status**: Draft

**Input**: User description: "开始 D：后端也接 CI→CD。给后端仓库也加 deploy job（替掉 post-receive hook），让后端同样「合到 main 且检查通过才上线」。需先写 specs，并处理 systemd 重启与失败回滚。"

## 背景

后端 CI 已有两道门（`.github/workflows/ci.yml`：`check` 双平台 lint + pytest + 覆盖率门禁、`security` gitleaks），
但它们**只提示，不决定上线**。真实链路仍是：

```
git push origin main
  ├─→ GitHub        → check / security        ← 事后体检
  └─→ 服务器 bare   → post-receive：
                        GIT_WORK_TREE=/opt/trader-analysis git checkout -f main
                        systemctl restart trader-api
```

与前端 004 改造前是同一类问题，但后端有三个**独有约束**（均已在服务器核对）：

1. **服务器无法访问 GitHub**（`curl https://github.com` 超时）→ 不能改成「服务器去 pull」。
2. **服务器无法访问 pypi.org**，但**能连阿里云镜像**（`mirrors.aliyun.com/pypi/simple` 返回 200/1.4s），
   且 venv 的 pip 已配好该 index-url → 依赖**可以**在服务器装，前提是走镜像。
3. **hook 从不安装依赖**（原文里没有 pip）→ `requirements.txt` 变更后即使代码更新，服务仍跑旧依赖，
   直到有人手工 pip install。这是一个现存缺口，本 feature 顺带补上。

另有版本差异：服务器 Python **3.11.13**，CI 矩阵用 **3.13**（`requires-python >=3.10`）。
本 feature **不扩大**这个差异，只记录：部署时用服务器自己的解释器安装依赖。

## 决策记录

| 问题 | 决定 | 理由 |
|---|---|---|
| 代码怎么到服务器 | **Actions 推 commit 到 bare repo + 显式 SSH 执行部署步骤** | 服务器不能连 GitHub；bare repo 已有；用 git 语义（而不是 tar）才能正确处理**删除文件**——这是 Python 服务最容易被 tar 覆盖搞坏的地方 |
| hook 是否保留 | **停用其自动部署**（备份原文件） | 否则 Actions 一次推送会触发两遍（hook + 显式步骤） |
| 依赖安装 | **仅在 `requirements*.txt` 变更时**执行 `pip install -r requirements.txt` | 不变时白跑一遍要 3~5s 且要打镜像；变更时漏装会让服务起不来 |
| 失败回滚 | Actions 侧 `if: failure()`：`git checkout -f <上一个 sha>` + 必要时重装依赖 + 重启 + 健康检查 | 与前端同构，用 git 天然有回滚锚点（不需要 .prev 目录） |
| 健康检查 | 轮询 `GET /health` 直到 200，最长 40s | 进程重启需要时间，固定 sleep 不可靠 |
| 部署密钥 | **复用前端那把部署密钥**（同一台服务器同一 root） | 少一把钥匙要管；两者爆炸半径本来就相同（都是 root）。日后若改专用用户再拆分 |
| 远程 | `origin` 只指向 GitHub，服务器地址拆成 `deploy` | 否则本地一次 `git push` 仍会绕过 Actions 直接上线 |
| Python 版本 | 不动 | 升服务器 3.11 → 3.13 属独立需求，与本次无关 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 合到 main 且检查通过才上线 (Priority: P1)

开发者把代码推到 `main`，CI 的 lint/测试/覆盖率全绿后，服务自动更新并重启；检查红了，服务器上的代码与进程**都不动**。

**Why this priority**: 这是需求的全部意义——后端也要有"绿了才发"的纪律。

**Independent Test**: 推一个正常提交，观察 CI 绿 → deploy 执行 → `/health` 返回 200 且 `/api/market-temperature` 正常；再推一个 lint 失败的分支到 main（临时），确认 deploy skipped 且服务未重启。

**Acceptance Scenarios**:

1. **Given** `main` 收到通过检查的推送，**When** 流水线完成，**Then** 服务器工作树切到该 commit、服务重启、`/health` 200
2. **Given** 检查失败，**When** 流水线结束，**Then** `deploy` 显示 skipped，服务器文件与进程均未变化
3. **Given** PR 触发，**When** 检查通过，**Then** 不发生部署

---

### User Story 2 - 依赖变更不会漏装 (Priority: P1)

`requirements.txt` 有改动时，部署过程必须在重启前把依赖装好；没改动时不做多余安装。

**Why this priority**: 现有 hook 只 checkout + 重启。依赖变更后服务会带着旧依赖启动，
可能出现「代码是新的、行为是旧的」这种最难查的状态。

**Independent Test**: 改一行 requirements（加注释即可触发变更判定）→ 部署日志出现 pip install；
再改一个纯 Python 文件 → 日志不出现 pip install。

**Acceptance Scenarios**:

1. **Given** 本次提交改了 `requirements.txt`，**When** 部署，**Then** 重启前执行 `pip install -r requirements.txt`
2. **Given** 本次提交没改 requirements，**When** 部署，**Then** 跳过安装步骤，部署更快
3. **Given** pip 安装失败（镜像不可用/包不存在），**When** 部署，**Then** **不重启服务**（旧进程继续跑），job 失败

---

### User Story 3 - 部署失败自动回滚 (Priority: P1)

重启后健康检查不过，自动把工作树切回上一个 commit、重启、再检查；仍不过则明确报错。

**Why this priority**: 自动化部署最怕"改了代码服务起不来，而没人守着终端"。

**Independent Test**: 注入一个会让启动失败的改动（如坏 import），观察自动回滚后 `/health` 恢复 200。

**Acceptance Scenarios**:

1. **Given** 新代码启动失败，**When** 健康检查超时，**Then** 自动 checkout 上一个 sha + 重启，`/health` 恢复 200
2. **Given** 回滚也失败，**When** job 结束，**Then** 结论为失败并在日志标明「线上可能处于异常状态」

---

### User Story 4 - 只有一条上线路径 (Priority: P2)

推送到服务器 bare repo 不再触发部署；上线只由流水线执行。

**Acceptance Scenarios**:

1. **Given** hook 已停用，**When** 向 bare repo 推送，**Then** 打印「部署已移交流水线」，工作树与进程不变
2. **Given** 需要人工应急，**When** 查看文档，**Then** 能找到回滚命令（git checkout 上一个 sha + 重启）

---

### Edge Cases

- **服务器磁盘/权限**：`/opt/trader-analysis` 属 root，部署用 root（现状如此）。
- **`.env` 与 `data/` 不受影响**：它们不在 git 跟踪范围，checkout 不会删除。
- **重启窗口**：`systemctl restart` 期间有 2~3 秒不可用，健康检查要容忍（轮询而非一次性）。
- **并发推送**：job 级 `concurrency` 串行化，避免两个部署交叉 checkout。
- **健康检查地址**：走公网 `http://47.106.175.84/health`（与前端同源），不依赖内网。
- **CI 与线上 Python 版本不同**：检查在 3.13 跑、线上 3.11 跑；`requires-python >=3.10` 是最低约束，本次不消除差异但记录。

## Requirements *(mandatory)*

- **FR-001**: 部署 MUST 作为 `check` 的下游（`needs: [check]`），且仅 `push` 到 `main` 时执行
- **FR-002**: 部署 MUST 使用与检查通过的同一 commit（`git checkout -f <sha>`），不得部署未检查的代码
- **FR-003**: `requirements*.txt` 变更时 MUST 在重启前安装依赖；未变更时 MUST 跳过安装
- **FR-004**: 依赖安装失败 MUST 阻止重启（保持旧进程）
- **FR-005**: 重启后 MUST 轮询 `/health` 直到 200（上限 40s）
- **FR-006**: 健康检查失败 MUST 自动回滚到上一个 commit 并重启，然后再检查一次
- **FR-007**: 服务器 `post-receive` MUST 停止自动部署（保留备份）
- **FR-008**: 私钥 MUST 只经 GitHub Secrets（`DEPLOY_SSH_KEY`），主机公钥 MUST 固化在仓库文件里
- **FR-009**: 同一时刻 MUST 只有一个部署在执行
- **FR-010**: `README.md` / `AGENTS.md` / `docs/guides/ops/README.md` MUST 更新为「上线由流水线执行」并给出回滚命令

### Key Entities

- **部署单元**：一个 commit（不是构建产物）。后端是解释型服务，部署即换代码 + 可选装依赖 + 重启。
- **工作树**：`/opt/trader-analysis`（systemd 的 WorkingDirectory，含 `.venv` / `.env` / `data`）。
- **裸库**：`/opt/git/trader-analysis.git`（Actions 推送到这里，工作树从它 checkout）。

## Success Criteria *(mandatory)*

- **SC-001**: 从 push 到 `/health` 200 ≤ **5 分钟**（含双平台检查）
- **SC-002**: 检查失败的推送，服务器工作树 `git rev-parse HEAD` **不变**
- **SC-003**: 注入启动失败后，自动回滚可恢复 `/health` 200（≤ **90 秒**内）
- **SC-004**: 部署 job 耗时 ≤ **90 秒**（不含 check）
- **SC-005**: requirements 未变更的部署，日志中**无** pip install 步骤
- **SC-006**: 向 bare repo 推送后，工作树 HEAD 不变

## Assumptions

- 服务器 root 可用部署密钥登录（已完成，前端 004 建的密钥同样授权此服务器）
- 阿里云 PyPI 镜像长期可用；若不可用，依赖变更的部署会失败（FR-004 保证不会带着旧依赖硬重启）
- 单机单实例，允许重启期间 2~3 秒不可用
- `data/*.db`、`.env`、`logs/`、`.venv/` 均不被 git 跟踪，checkout 不会破坏
