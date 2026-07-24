---
description: 扫描项目结构,AI 生成知识图谱初始骨架(graph.json 主索引 + 各 graph-<domain>.json,全部 draft)
argument-hint: [可选:已知的核心系统列表,逗号分隔。如:订单,支付,库存,用户]
---

# 初始化知识图谱

执行 **kg-init skill** 的完整流程（已随安装部署到 `.claude/skills/kg-init/SKILL.md`）：
扫描项目结构 → 列候选系统（Gate 1 确认）→ 划分域（Gate 2 确认）→ 走 kg MCP 工具生成骨架
→ 校验 → 报告并引导人工补 persistence_pitfalls。

用户可选提供的系统列表：**$ARGUMENTS**（若非空，作为候选系统列表的基础）。

> 该流程的权威定义在 kg-init skill（`.claude/skills/kg-init/SKILL.md`），与 Codex/Cursor 用的
> `.agents/skills/kg-init/SKILL.md` 同源。请按 skill 文档逐步执行，严格保留两道 Gate 用户确认，
> 不要跳过收尾的「引导人工补 pitfall」环节。
