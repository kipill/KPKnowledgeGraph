---
name: kg-consult
description: >
  知识图谱查询。当用户提出新功能开发、跨模块改动、不熟悉的领域、重构/迁移请求时使用。
  通过 kg MCP 工具（kg_overview / kg_query）快速定位涉及的系统、跨模块联动和持久化注意点，
  避免直接 grep 浪费 token 和漏改跨模块联动。
  触发场景：用户说"加一个 X" / "实现 Y" / "改造 Z"、提到"跨服 / 联动 / 同步 / 通知 / 触发"
  等关键词、需要重构某个系统、对提到的系统名不熟悉。关键词：知识图谱、knowledge graph、
  影响范围、impact、cross-module、跨模块、联动、新功能、重构、迁移。
  即使用户只说"给装备系统加个新功能"，也应触发此 skill 先查图谱再读代码。
  小改动（改单个方法/调数值/加 log）、bug 排查、性能调优、纯 review、纯问答时跳过。
---

# Knowledge Graph Consult Skill

图谱的**唯一出入口是 kg MCP 工具**（server: `kg`，见项目根 `.mcp.json`）：

| 工具 | 用途 |
|------|------|
| `kg_overview` | 主索引：域清单 + 跨域关联（替代读 graph.json） |
| `kg_query` | 关键词搜 entry（字面匹配），返回代码路径/踩坑/出边入边，自动记录 querylog |
| `kg_catalog` | 全部/某域 entry 的轻量目录，关键词失灵时由 AI 语义挑选 |
| `kg_get_entry` | 按 entry_id 精确取单个 entry（含入边 incoming、使用统计） |
| `kg_validate` | 全量校验（结构/悬空引用/路径漂移/孤儿节点） |
| `kg_add_entry` | 新增 entry（写前强校验 code 路径真实存在） |
| `kg_update_entry` | 修改字段（整字段替换） |
| `kg_add_relation` | 加一条关联边 |
| `kg_add_pitfall` | 追加持久化踩坑 |
| `kg_verify_edge` | draft 边升级 verified |
| `kg_feedback` | 回报某 entry 信息是否准确（遥测，不改图谱，无需用户确认） |

**禁止直接 Edit/Write `graph*.json`**——PreToolUse hook 会拦截。所有写操作必须走
MCP 工具，它们自带 schema 校验、changelog 记录（含 reason）、反向索引重建。
`entries/*.md` 深度文档可以直接编辑，不受限。

---

## 何时触发（满足任一）

1. **新功能开发**：用户提出"加一个 X" / "实现 Y"
2. **跨模块改动**：功能涉及多个系统（关键词：联动 / 同步 / 触发 / 跨服 / 通知）
3. **不熟悉的领域**：提到的系统名不在最近上下文里
4. **重构/迁移**：用户要重构、拆分、改造某个系统

## 何时跳过（满足任一）

1. **明确的局部小改动**：改单个方法参数、调整数值、加个 log
2. **bug 排查**：看 stack trace / 错误日志更直接
3. **性能调优**：需要实际性能数据，图谱无关
4. **纯代码审查**：用户给出具体 diff 让你 review
5. **纯概念问答**：不在做改动

**判断不确定时优先跳过**——多查图谱比少查浪费 token。

---

## 工作流程

### Step 1：`kg_query` 直接搜（首选）

用用户需求里的关键词直接查：

```
kg_query(query="装备回收")
```

返回的每个 hit 已含 `code`（文件路径）、`persistence_pitfalls`、`related`（出边）、
`incoming`（入边=谁依赖我）——**一次调用拿全**，不需要再读 reverse_index.json。

### Step 2：无命中/命中可疑时 `kg_catalog` 语义挑选（关键，不要跳过）

`kg_query` 是**字面匹配**——"卖装备换材料"查不到"装备回收"是正常的，
无命中不等于图谱没有。此时调 `kg_catalog()`（可加 domain 限定）拿全量轻量目录，
**通读 id/中文名/摘要，用你的语义理解判断哪些 entry 和需求相关**，
再 `kg_get_entry(entry_id=...)` 逐个取详情。

需要判断跨域联动时，配合 `kg_overview` 看 `cross_domain_relations`。

### Step 3：按需读 MD 深度文档

hit 里 `doc_exists: true` 时，Read `.claude/kg/entries/{entry_id}.md` 获取更深上下文。
`doc_exists: false` 是正常状态（按需填充），直接用 JSON 信息继续。

### Step 4：报告给用户

在开始写代码前，给出明确清单：

```
本次任务涉及：
- equip_huishou（装备回收系统）- 主入口，改 EquipHuiShouManager
- economy（经济系统）- 回收产出货币/材料，需要扣/加货币

关键注意点：
- 回收后装备从背包移除必须 saveToDB
- rewardItems 必须在调用 equipHuiShouBeforeGet 前填充完毕

我会先 view：
- EquipHuiShouManager.java
```

### Step 5：直接 view 代码

从 `code` 字段直接拿文件路径，**跳过 grep**。只有找具体方法/变量引用/配置字段值时才 grep。

---

## Fallback 规则（关键）

以下情况立即停止查图谱，改 grep + view 源码：

1. `kg_query` 无命中**且通读 `kg_catalog` 目录后确认没有相关 entry**（先语义挑选再放弃）
2. entry 存在但 `code` 路径和实际代码对不上
3. `related` 全是 draft 且无法快速验证

**fallback 不是失败，是设计的一部分**。代码是 source of truth；发现图谱路径漂移时，
顺手用 `kg_update_entry` 修正（它会强校验新路径真实存在）。

kg MCP 工具不可用（server 未启动/报错）时：查询可以退化为直接 Read
`.claude/kg/graph*.json`；**写操作不许退化为直接编辑文件**，报告用户 MCP 异常。

---

## 与规格/流程框架的边界（OpenSpec、Superpowers 等共存时）

三者处于**不同层**，是串联关系，不互斥，触发时不要混淆或互相替代：

| 层 | 负责 | 归属 |
|---|------|------|
| 需求层 | 做什么：需求、规格、变更提案 | OpenSpec 等 spec 框架 |
| 过程层 | 怎么干活：brainstorm / 计划 / TDD / review | Superpowers 等流程 skill |
| 导航层 | 代码在哪、改动影响什么、有什么坑 | 本 skill（kg） |

**协作顺序**：需求敲定（spec 框架）→ 计划（流程 skill）→ **动代码前**用本 skill
查影响范围 → 实施 → 收尾 kg_feedback + 图谱更新建议（可并入流程框架的收尾环节）。

**不要做的事**：

- ❌ 不在 entry 里复制规格/需求文档内容——entry 写"现在时"（路径/联动/踩坑），
  引用规格时写指针（如 `openspec/specs/xxx.md`），避免双份 source of truth
- ❌ 不因为流程框架已生成计划就跳过图谱查询——计划解决"步骤"，图谱解决"位置与联动"
- ❌ 不用本 skill 做需求分析或方案头脑风暴——那是需求层/过程层的事

---

## 任务完成后：按需更新图谱

### ⚠ 防遗漏机制

**在 skill 加载后、开始实现前，必须立即用 TaskCreate 记录收尾任务：**

```
TaskCreate("kg-consult 收尾：询问是否更新知识图谱", "任务完成后按 skill 文档询问用户是否更新图谱", ...)
```

原因：实现过程会很长，post-task 指令容易沉底被遗忘。TaskCreate 把软性要求变成硬性待办。

---

### 第一步：回报准确性（自动执行，无需询问）

对本次任务**实际使用过**的每个 entry 调一次 `kg_feedback`：

- 代码路径直达、联动信息正确 → `accurate=true`
- 路径漂移、信息误导、缺关键联动 → `accurate=false`，note 写明哪里不对

这是遥测数据（进 querylog），不改图谱内容，不用问用户。每个 entry 每次任务只报一次。

### 第二步：建议更新（需用户确认）

主动询问是否更新图谱（不自动改，让用户决定）。用户同意后用对应
MCP 工具执行，**reason 参数写清触发原因**（哪个任务/验证了什么），它会进 changelog：

### 情形1：用到了已有 entry

```
本次任务用到了 equip_huishou 和 economy 两个 entry。

建议更新：
1. 发现新踩坑 → kg_add_pitfall(entry_id="equip_huishou", pitfall="XXX 情况下需要先 YYY 再 saveToDB", reason="...")
2. 验证了 draft 边 → kg_verify_edge(from_id="equip_huishou", to_id="economy", reason="本次实测回收走了 CurrencyManager")

要应用吗？（可以说"全应用" / "跳过" / "只应用第X条"）
```

### 情形2：创建了新功能/文件

```
本次新增了 XxxManager.java，建议 kg_add_entry(
  domain="equip", entry_id="xxx", type="feature", name_cn="XXX功能",
  summary="一句话描述",
  code={"manager": "GameLogic/src/main/java/com/gamelogic/xxx/XxxManager.java"},
  related=[{"to": "equip", "context": "...", "confidence": "draft"}],
  reason="实现了XXX需求"
)
是否添加？
```

### 情形3：涉及系统还没有 MD entry

```
本次使用了 fight entry，但 entries/fight.md 还不存在。
现在对这个系统有了一定了解，要我帮你生成一份吗？
（按 entry.template.md 格式，填入本次发现的关键约定和踩坑；MD 可直接编辑）
```

---

## 反例：不要这样做

❌ **直接 Edit graph-*.json**：会被 hook 拦截；就算绕过也丢失校验和 changelog
❌ **盲目读所有域图谱**：kg_query 一次到位，不要挨个读文件
❌ **基于残缺图谱硬猜**：信息不全时立即 fallback
❌ **图谱 vs 代码冲突偏向图谱**：代码是 source of truth，顺手 kg_update_entry 修正
❌ **每次任务完成后大量 churn 图谱**：只建议必要的最小更新
❌ **reason 写敷衍**："更新" 不行，要写"哪个任务/发现了什么"

---

## 人工/CI 工具（非 AI 场景）

```bash
# 校验（CI / pre-commit / 人工检查）
python .claude/kg/tools/validate.py          # --strict / --json 可选

# 可视化
python .claude/kg/tools/gen_graph_html.py
```
