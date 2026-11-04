# 运维配置（服务器侧文件的仓库副本）

> **本目录是「线上配置的快照 + 唯一可追溯记录」**，不是自动部署源。
> 服务器 `/etc/...` 里的文件才是运行时生效的那份；**改完服务器必须回写这里**，否则下一个人只能靠猜。

## 为什么放在仓库里

此前 systemd 单元与 nginx 站点配置**只存在于服务器上**：仓库里查不到服务怎么起的、反代怎么配的、缓存策略是什么。
一旦服务器重装或换机器，只能凭记忆重建。2026-11-01 抓回入库，消除这个盲区。

## 文件清单

| 文件 | 服务器路径 | 说明 |
|---|---|---|
| `trader-api.service` | `/etc/systemd/system/trader-api.service` | 后端服务单元：`/opt/trader-analysis` 下 `python -m trader_analysis serve`，`Restart=always` |
| `nginx-trader.conf` | `/etc/nginx/conf.d/trader.conf` | 站点配置：静态根 `/var/www/trader-frontend`，`/api`、`/v1`、`/health` 反代 8000 |
| `nginx-gzip.conf` | `/etc/nginx/conf.d/gzip.conf` | gzip 策略（2026-10-12 新增，删除即回滚） |

`/etc/nginx/conf.d/default.conf` 是 nginx 自带的默认站点，本项目未使用，不收录。

## 重新抓取（以服务器为准）

```bash
ssh root@47.106.175.84 "cat /etc/systemd/system/trader-api.service"                        > docs/guides/ops/trader-api.service
ssh root@47.106.175.84 "cat /etc/nginx/conf.d/trader.conf"                                 > docs/guides/ops/nginx-trader.conf
ssh root@47.106.175.84 "cat /etc/nginx/conf.d/gzip.conf"                                   > docs/guides/ops/nginx-gzip.conf
```

抓完 `git diff` 应无输出；有输出说明线上被手改过，需判断是回写还是回滚。

## 部署链路

```
本地 git push origin        →  GitHub
本地 git push <deploy>      →  root@47.106.175.84:/opt/git/trader-analysis.git（bare）
                                 └─ post-receive hook 用 --work-tree 检出到 /opt/trader-analysis
                                    └─ systemctl restart trader-api
```

- 前端：独立仓库 → `/opt/git/trader-frontend.git` → ~~检出到 `/var/www/trader-frontend`~~
- 凭证：`/opt/trader-analysis/.env`（`EnvironmentFile`），**不入库**
- 一键配置脚本：`scripts/setup-git-deploy.sh`（服务器上执行一次）

> ⚠️ **勘误（2026-11-04）：前端已不在服务器构建/部署。**
> 前端上线改由 GitHub Actions 执行（`TraderAnalysisFrontend` 仓库
> `specs/004-deploy-on-green/`）：`push main` → `check`（lint/单测/构建）→ `deploy` job
> → `tar` 到 `/var/www/trader-frontend.new` → 校验 → `mv` 交换（旧版留 `.prev`）→ 健康检查。
> 服务器 `trader-frontend.git/hooks/post-receive` 已停用（原版备份 `post-receive.bak-20261104`），
> **推该 bare repo 不再改变线上**；服务器也不需要再为前端装 Node/npm。
> 上面那行原文保留，用于记录 2026-11-04 之前的实际行为。

## 核验部署是否生效（重要）

**不要看服务器上的 `git log`**：post-receive 用 `--work-tree` 检出，**不推进该目录自己的 HEAD**，
`git -C /opt/trader-analysis log` 会一直显示旧 commit，容易误判为部署失败。

用文件内容核验：

```bash
ssh root@47.106.175.84 "grep -n '新函数名' /opt/trader-analysis/src/trader_analysis/futu_strategy/xxx.py"
ssh root@47.106.175.84 "systemctl is-active trader-api && systemctl show -p ExecMainStartTimestamp trader-api"
curl -s http://47.106.175.84/api/... | head
```

## 改配置的流程

1. 先改本目录文件并提交
2. `scp` 到服务器对应路径（或直接在服务器改完立刻回写本目录）
3. `systemctl daemon-reload && systemctl restart trader-api`（systemd）／`nginx -t && systemctl reload nginx`（nginx）
4. 用上面的核验方式确认生效，把结果记进 `docs/history/CHANGELOG.md`
