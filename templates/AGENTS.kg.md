<!-- KG:BEGIN (由 install.py 维护，勿手改此标记之间的内容；升级会整段替换) -->
## 知识图谱（kg）

本项目装有 KPKnowledgeGraph——「先查图谱再读代码」的成长型知识索引，图谱数据在
`.claude/kg/`。**完整使用约定见 `kg-consult` skill**（已装在 `.agents/skills/kg-consult/SKILL.md`，
Codex 按需自动加载）：何时先查图谱、怎么查（`kg_query` / `kg_catalog` / `kg_scout_reuse`）、
写图谱只走 kg MCP 工具、任务后 `kg_feedback`。

> 兜底提醒（万一 skill 未加载）：图谱**唯一出入口是 kg MCP 工具**（server 名 `kg`）。
> **禁止直接 Edit / Write `graph*.json` / `reverse_index.json` / `*.jsonl`**——它们只能经
> kg MCP 写工具（自带 schema 校验 + changelog + 反向索引重建）；`entries/*.md` 可直接编辑。
> Codex 无 hook 强制拦截，靠本约定自律。
<!-- KG:END -->
