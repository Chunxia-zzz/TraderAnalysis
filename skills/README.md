# skills/ —— 技能唯一真相源

> **改技能只改这里**。`.claude/skills/`、`.agents/skills/`、`.workbuddy/skills/` 都是 `scripts/agent/sync_skills.py`
> 生成出来的副本/链接，**不要手改**（改了也会被下次同步覆盖）。

## 为什么在这里

技能原先只存在于 agent 的私有目录（`~/.workbuddy/skills/`、`.claude/skills/`），这些目录被 `.gitignore` 排除。
换一个 agent、换一台机器就等于不存在。迁进仓库后：

- 技能像代码一样被 review、被 diff、被回滚
- 任何 agent 都能按路径读取执行，**不依赖某个产品的技能机制**
- `data/watchlist.json` 那类「git 里躺着过期真相」的问题不会再发生在技能上

## 清单

| 技能 | 触发词 | 前置检查 | 说明 |
|---|---|---|---|
| `trader-daily-update` | 更新行情 / 更新数据 / 跑日更 / 补某天的数据 | ✅ PATH + APPDATA 两条 export，OpenD 11111 | 六步日更：update → 温度 → 评分 → 信号 → 同步线上 → 起本地服务，含归档与晨星/复权核对 |
| `doc-code-consistency-audit` | 检查文档有没有要更新的 / 文档和代码对不上 / XX 文档还准吗 | — | 按「真实路由 → 数据模型 → 枚举常量 → 交叉引用」逐项比对，含 7 类失效模式 |

技能索引与触发词的**权威表在根目录 `AGENTS.md`**，本文件只做补充说明。

## 第三方技能不在仓库里

`futuapi`（58 个脚本 / 420 KB）与 `install-opend` 来自富途官方包
（`https://openapi.futunn.com/skills/opend-skills.zip`），其 `LEGAL_Futu_api_cn.md` 只有免责声明、
**没有可再分发授权**，所以不随仓库分发。需要时运行：

```bash
python scripts/agent/fetch_futu_skills.py
```

拉下来的内容落在本目录（已 gitignore），再跑一次 `sync_skills.py` 即可被 agent 发现。

## 用户级目录里的是「占位入口」

`~/.workbuddy/skills/<name>/SKILL.md` 现在只剩 4 行正文，内容是一句话 + 仓库路径。

原因是产品级优先级：**enterprise > personal > project**，**同名时个人级覆盖项目级**。
个人级若还留着完整旧正文，你改仓库那份也不会生效——旧副本会静默胜出，而且没人会发现。
改成占位入口后：触发词仍由个人级提供（保证能被发现），正文永远只有仓库一份（保证不会漂移）。

- 原文件已归档到 `~/.workbuddy/_skills-archive-20261101/`，可随时回滚
- 换机器时不需要重建占位：仓库里的 `AGENTS.md` 索引表已足以让 agent 按路径找到技能

## 维护

```bash
python scripts/agent/sync_skills.py            # 建立链接（默认 --link）
python scripts/agent/sync_skills.py --check    # 校验：副本/链接与源是否一致，不一致非零退出
python scripts/agent/sync_skills.py --copy     # 兜底：链接不可用时改为复制
```

- Windows 用目录联结点（`mklink /J`，无需管理员）；POSIX 用 symlink
- **链接模式下「改副本」= 改源文件**，`git status` 立刻可见，不存在两份不同步
- `--copy` 模式下必须靠 `--check` 兜底：日更前置检查里应包含一次 `--check`

## 新增一个技能

1. 建目录 `skills/<name>/`，写 `SKILL.md`
2. frontmatter 只允许开放规范的 6 个字段：`name` / `description` / `license` / `compatibility` / `metadata` / `allowed-tools`
   —— 其他产品的扩展字段在严格客户端上会**直接报错**，不是忽略
3. `name` 必须与目录名一致，小写字母/数字/连字符，≤64 字符
4. 脚本、参考资料放同目录的 `scripts/`、`references/`，正文用**仓库相对路径**引用
5. 在 `AGENTS.md` 的技能索引表补一行
6. 跑 `sync_skills.py` 并提交
