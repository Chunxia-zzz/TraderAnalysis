# Specification Quality Checklist: 后端只在新版本检查通过后上线

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-04
**Feature**: [`spec.md`](../spec.md)

## Content Quality

- [x] No implementation details — spec 只写「什么时候允许上线、失败要怎样」，`git`/`systemctl`/`pip` 全在 plan
- [x] Focused on user value — 「合到 main 就上线」「依赖变了不会漏装」「起不来自动退回」
- [x] Written for non-technical stakeholders — 用「绿了才发」「服务不动」表述
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers — 三条服务器事实（无 GitHub 出网 / 无 pypi.org / pip 已配镜像）
      已在 Phase 1 核对完，结论写进「决策记录」
- [x] Requirements are testable — FR-001~010 每条对应一个可观察结果
- [x] Success criteria are measurable — SC-001 ≤5min / SC-002 HEAD 不变 / SC-003 ≤90s / SC-004 ≤90s / SC-005 无 pip
- [x] Success criteria technology-agnostic
- [x] All acceptance scenarios defined — 4 条 Story 共 9 个 Given/When/Then
- [x] Edge cases identified — 磁盘权限、`.env`/`data` 不受影响、重启窗口、并发、健康检查地址、Python 版本差异
- [x] Scope bounded — 明确不做：多实例/蓝绿、升 Python、改 systemd unit
- [x] Dependencies and assumptions identified — 6 条，含镜像可用性、密钥复用、数据目录不入 git

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows — 上线、依赖、回滚、单一入口
- [x] Feature meets measurable outcomes
- [x] No implementation details leak into specification

## Notes

- 本 feature 与前端 004 **刻意保持同构**（needs / 仅 push main / 串行 / 失败回滚 / 单一入口），
  差异只在「部署单元是 commit 而不是静态产物」——这是 Python 服务与静态站点的本质区别。
- **风险点**：重启窗口 2~3 秒不可用（实测第一次 `/health` 可能返回 502）。健康检查必须轮询，不能只看一次。
