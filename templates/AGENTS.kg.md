<!-- KG:BEGIN (由 install.py 维护，勿手改此标记之间的内容；升级会整段替换) -->
## 知识图谱（kg）使用约定

本项目装有 KPKnowledgeGraph——一个「先查图谱再读代码」的成长型知识索引。
图谱数据在 `.claude/kg/`，**唯一出入口是 kg MCP 工具**（server 名 `kg`）。

### 何时先查图谱（满足任一，动代码前）
- 新功能开发：「加一个 X」「实现 Y」
- 跨模块改动：涉及联动 / 同步 / 触发 / 跨服 / 通知
- 不熟悉的系统名，或重构 / 迁移某系统

小改动（改单个方法 / 调数值 / 加 log）、bug 排查、性能调优、纯问答 → 跳过。

### 怎么查
1. `kg_query(query="关键词")` 直接搜——一次返回代码路径 / 踩坑 / 出边入边。
2. 无命中或可疑时 `kg_catalog()` 拿全量轻量目录，用语义判断哪些 entry 相关，
   再 `kg_get_entry(entry_id=...)` 取详情。字面无命中 ≠ 图谱没有。
3. 造新行为的需求（「加个能做 Y 的功能」），先 `kg_scout_reuse(requirement=...)`
   做复用分诊：是配现成能力还是真要开发——**转述给用户 + 给选项，等人拍板**，
   绝不自行采纳推荐就写代码。

### 写图谱（⚠ Codex/Cursor 无 hook 拦截，靠本约定自律）
- **禁止直接 Edit / Write `graph*.json` / `reverse_index.json` / `*.jsonl`**——
  它们只能经 kg MCP 写工具（自带 schema 校验 + changelog + 反向索引重建）。
  绕过会破坏图谱一致性，且丢失 changelog。
- `entries/*.md` 深度文档可直接编辑，不受限。
- 写工具：`kg_add_entry` / `kg_update_entry` / `kg_add_relation` / `kg_add_pitfall`
  / `kg_verify_edge` / `kg_add_capability_catalog` / `kg_add_capability_members`。
  每个写操作的 `reason` 参数要写清「哪个任务 / 发现了什么」。

### 任务完成后
- 对**实际用过**的每个 entry 调 `kg_feedback(entry_id, accurate, note)`（遥测，不改图谱，
  无需问用户）：路径直达 / 联动正确 → `accurate=true`；漂移 / 误导 → `false` 并写明。
- 发现新踩坑 / 验证了 draft 边 / 新增了系统 → **建议用户**更新图谱（不自动改），
  同意后走对应 MCP 写工具。
- 图谱路径和实际代码对不上时：代码是 source of truth，顺手 `kg_update_entry` 修正
  （会强校验新路径真实存在）。

### MCP 不可用时
查询可退化为直接 Read `.claude/kg/graph*.json`；**写操作不许退化为直接编辑文件**，
报告用户 MCP 异常。
<!-- KG:END -->
