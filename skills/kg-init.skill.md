---
name: kg-init
description: >
  初始化知识图谱骨架——扫描项目结构，AI 生成 graph.json 主索引 + 各 graph-<domain>.json
  （全部 draft）。**仅在用户明确要求初始化/首次搭建知识图谱时触发**：用户说"初始化知识图谱"
  / "kg-init" / "给这个项目建知识图谱" / "搭一下图谱骨架"，或图谱目录 .claude/kg/ 存在但
  graph.json 还是空主索引（无 domains）。关键词：初始化知识图谱、kg-init、建图谱、图谱骨架、
  init knowledge graph、bootstrap graph。**不要**在日常查询/改代码时触发（那是 kg-consult skill）；
  图谱已建好（graph.json 已有 domains）时也不要触发——这是一次性重操作，会创建大量文件并需用户两道确认。
---

# 初始化知识图谱

为目标项目生成知识图谱初始骨架。图谱目录：`.claude/kg/`（应由 install 脚本预先创建）。

> 用户可能随调用给出已知核心系统列表（逗号分隔，如「订单,支付,库存,用户」）——若有，作为第 3 步的基础。

## 重要原则

- **不硬编码任何项目特定的域名/系统名**：域名和系统名都来自扫描结果或用户输入，不要假设固定值（如 combat/equip 这种是别的项目的例子）
- **`updated_at` 用今天日期**（从当前会话日期获知）
- **所有 `related` 边默认 `confidence: draft`**——骨架不保证准确
- **关系不确定宁可不加**：漏加比错加强（错的关系会误导后续查询）
- **`persistence_pitfalls` 留空 `[]`**：这部分必须人工补，是整套系统价值的核心，不要 AI 瞎编

## 步骤

### 1. 确认图谱目录就绪

检查 `.claude/kg/` 是否存在、`tools/kg_mcp_server.py` 是否存在、kg MCP 工具是否可用
（调一次 `kg_overview` 试试）。
若目录缺失 → 提示用户先在发行包目录跑 `install.sh` / `install.ps1`，然后停止。
若 MCP 工具不可用 → 提示用户重启会话使 MCP 配置生效，然后停止。

### 2. 扫描项目结构（理解项目是什么）

- 用 Glob 看顶层目录和主要源码目录（如 `src/`、`app/`、`com/`、`server/` 等）
- 用 Read 读项目元信息：`README.md` / `package.json` / `pom.xml` / `go.mod` / `Cargo.toml` / `requirements.txt` / `pyproject.toml` 等
- 目标：理解这是个什么项目、什么语言、有哪些大模块、分层是怎样的

### 3. 列候选核心系统（10-20 个）

- 如果用户给了系统列表，**以此为基础**（可能要补全到 10-20 个）
- 否则根据扫描结果推断
- **粒度标准**：开发者能用**一个词**指代的（如"订单""支付""公会""库存""认证"）。**不要**列单个类/文件（那是 javadoc，不是字典）
- 参考 `.claude/kg/templates/graph-domain.template.json` 的 type 判断：
  - `system`：独立系统
  - `feature`：某 system 的子功能
  - `concept`：跨系统的规则/机制（如持久化约定、事务边界、跨服同步）

**Gate 1**：把候选列表（带 type 标注）输出给用户，问"要加/删/改吗?"。**等用户确认后再继续**。

### 4. 划分域（3-7 个）

- 把确认的系统归类到 3-7 个域
- 域 = 业务大类（名字按项目领域起，如 social/economy/combat，或 order/payment/inventory）
- 每个域 2-5 个系统为宜
- 域 id 用小写英文，desc 用一句话中文

**Gate 2**：把域划分输出给用户确认。**等确认后再继续**。

### 5. 生成骨架（全程走 kg MCP 工具，禁止直接 Write 图谱 JSON）

**注意：图谱 JSON 在 Claude Code 下受 PreToolUse hook 保护，直接 Write/Edit 会被拦截；
Codex/Cursor 无 hook，但同样禁止直接写——绕过 MCP 会丢校验和 changelog。**
所有写入用 MCP 工具，它们自带校验并记录 changelog（reason 统一写 "kg-init 初始化"）：

按依赖顺序：

1. **建域**：对每个确认的域调 `kg_add_domain(domain=..., desc=..., reason="kg-init 初始化")`
2. **建 entry**：对每个系统调 `kg_add_entry(domain=..., entry_id=..., type=..., name_cn=...,
   summary=..., code=..., related=[...], reason="kg-init 初始化")`
   - **先建被依赖的 entry，再建带 related 的 entry**（related.to 必须已存在，否则被拒）
   - `code` 路径**必须用 Glob 找到的真实文件**——写入时会强校验，瞎编的路径会被拒绝。
     找不到主入口就 `code` 传 `{"_TODO": "未定位到主入口"}`（下划线开头的 key 跳过路径校验）
   - `related` 只加扫描时有明确证据的依赖（如 A 文件 import/调用 B），全部 `confidence: "draft"`。不确定的**不加**
   - `persistence_pitfalls` 不传（留给人工填）
3. **跨域关联**：对有明确证据的域级联动调
   `kg_add_cross_relation(from_domain=..., to_domain=..., context=..., confidence="draft", reason="kg-init 初始化")`

### 6. 跑校验

调 `kg_validate` MCP 工具（或 Bash: `python .claude/kg/tools/validate.py`）：

- **ERROR 必须修**（正常情况下不会有——写入口已强校验；有说明流程异常，报告用户）
- **WARNING 记录并报告**（如孤儿节点），交给用户决定

### 7. 报告 + 引导人工补充（关键收尾，不可省!）

生成完，向用户输出类似：

```
骨架已生成:
- graph.json(主索引,N 个域)
- graph-<domain>.json × N(共 M 个 entry,全部 draft confidence)

⚠ 重要:骨架只是目录级,价值核心在 persistence_pitfalls
   (代码里看不出来的隐式契约,如"字段X 改后必须 Y,否则 Z")。
   不补的话,图谱沦为目录,1 个月就废弃(见 DESIGN.md §7.1)。

下一步(建议 2-3 小时一次性投入,这是 80% 价值来源):
1. 对每个核心 entry,回忆/翻 commit log,补:
   - persistence_pitfalls(JSON 里)
   - MD entry(.claude/kg/entries/<id>.md,参考 templates/entry.template.md)
2. 把你确定的关系从 draft 升 verified

要不要现在就开始?挑你最熟的 1-2 个系统,你口述踩坑和约定,我帮你填。
```

## 不要做的事

- ❌ 不问用户就一口气生成所有文件（必须有 Gate 1 / Gate 2 让用户确认系统和域）
- ❌ 瞎编 code 路径（找不到就 code 传 `{"_TODO": "未定位到主入口"}`）
- ❌ AI 自己填 persistence_pitfalls（必须人工）
- ❌ 把所有可能的 related 都加上（只加有证据的）
- ❌ 在生成的 JSON 里留模板的 `_comment` / `_template_*`
