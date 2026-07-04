# 变更日志

**中文** | [English](./docs/en/CHANGELOG.md)

本文件记录知识图谱发行包（dist）的版本变更。版本号遵循语义化版本（MAJOR.MINOR.PATCH）。
使用者用 `python .claude/kg/tools/kg_admin.py check` 检查更新，`update` 升级。

## 2.1.0 — 2026-07-03

- **治理层（v2 架构）**：MCP 唯一读写出入口，写入强校验（code 路径/related 目标/reason 必填）、changelog/querylog 审计、反向索引自动重建
- **防漂移**：PreToolUse hook 拦截对图谱 JSON 的直接编辑，逃生口 `KG_ALLOW_DIRECT_EDIT=1`
- **查询两段式**：`kg_query`（字面匹配快路径）+ `kg_catalog`（语义兜底，关键词失灵时 AI 通读目录挑选）
- **遥测与可视化**：`kg_feedback` 回报信息准确性；可视化含每个 entry 的查询命中/反馈/变更历史 + 全局汇总（kg_stats）
- **图谱复用**：`kg_pack` / `kg_unpack` 装箱拆箱，相似项目参考导入
- **自管理**：`kg_admin.py`（本文件所在工具）提供 `version`/`check`/`update`，类似 `claude update`
- **跨工具**：Claude Code 与 Codex 通用；installer 自动合并注册 `.mcp.json` 和 hook
- 修复空图谱生成可视化时的边界崩溃

## 2.0.0 — 2026-06

- v1→v2 重构：从"AI 直接编辑 JSON + 手动校验"改为"MCP 出入口 + 机制强制"
- 数据 schema 与 v1 兼容
