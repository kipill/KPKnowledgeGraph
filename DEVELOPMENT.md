# 开发文档 (Development Guide)

**中文** | [English](./docs/en/DEVELOPMENT.md)

实操向：怎么搭、怎么用、怎么维护。设计原理看 [`DESIGN.md`](./DESIGN.md)。

> v2 核心变化：图谱 JSON 的读写走 **kg MCP 工具**（唯一出入口），不再直接编辑文件。
> 数据 schema 与 v1 兼容。

---

## 1. 目录结构

安装后（`install.sh` / `install.ps1` / `python install.py`）的目标项目布局：

```
<project_root>/
├── .mcp.json                            # kg MCP server 注册（安装器自动合并）
├── .claude/
│   ├── settings.json                    # PreToolUse 防漂移 hook（安装器自动合并）
│   ├── kg/                              # 知识图谱目录
│   │   ├── graph.json                   # 主索引（域清单 + 跨域关联，必有）
│   │   ├── graph-<domain>.json          # 域文件（每个域一个，内含 entries）
│   │   ├── reverse_index.json           # 反向索引（写操作后自动重建，勿手改）
│   │   ├── changelog.jsonl              # 变更日志（自动追加，建议提交 git）
│   │   ├── querylog.jsonl               # 查询日志（自动追加，建议提交 git）
│   │   ├── entries/                     # MD 字典条目（按需创建，可直接编辑）
│   │   ├── templates/                   # 模板参考
│   │   └── tools/
│   │       ├── kg_core.py               # 核心库：加载/校验/变更/日志（唯一写入口的实现）
│   │       ├── kg_mcp_server.py         # MCP stdio server（纯标准库）
│   │       ├── kg_guard_hook.py         # PreToolUse hook：拦截直接编辑图谱 JSON
│   │       ├── validate.py              # 校验 CLI（CI / pre-commit / 人工）
│   │       ├── build_reverse_index.py   # 手动重建反向索引（人工直改后用）
│   │       └── gen_graph_html.py        # 生成可视化 HTML
│   ├── skills/
│   │   └── kg-consult/SKILL.md          # Claude skill（决定 AI 何时自动查图谱）
│   └── commands/
│       └── kg-init.md                   # /kg-init 命令（AI 生成骨架）
└── ...项目代码...
```

图谱目录位置自动探测：`tools/qx_rag`（源项目布局）→ `.claude/kg`（安装布局），
也可用环境变量 `KG_DIR` 或各工具的 `--kg` 参数显式指定。

---

## 2. 读写规则总览（先看这个）

| 对象 | 怎么读 | 怎么写 |
|------|--------|--------|
| 图谱 JSON（graph*.json） | `kg_overview` / `kg_query` / `kg_get_entry` | **只能**用 kg_add_* / kg_update_* / kg_verify_edge |
| MD 深度文档（entries/*.md） | 直接 Read | 直接编辑（不受管制） |
| reverse_index.json / *.jsonl | 直接 Read | 禁止手改（自动生成/追加） |

### kg MCP 工具清单

| 工具 | 用途 | 备注 |
|------|------|------|
| `kg_overview` | 域清单 + 跨域关联 | 替代读 graph.json |
| `kg_query` | 关键词搜 entry（字面匹配） | 返回 code/踩坑/出边/入边，记 querylog |
| `kg_catalog` | 轻量目录（id/中文名/摘要/标签） | 关键词失灵时 AI 通读做语义挑选 |
| `kg_get_entry` | 按 id 精确取 | 含入边 incoming、doc_exists、使用统计 |
| `kg_validate` | 全量校验 | 同 validate.py |
| `kg_add_entry` | 新增 entry | code 路径必须真实存在 |
| `kg_update_entry` | 改字段 | 整字段替换，非深合并 |
| `kg_add_relation` | 加出边 | 两端 entry 必须存在 |
| `kg_add_pitfall` | 追加踩坑 | 自动去重 |
| `kg_verify_edge` | draft → verified | 边必须已存在 |
| `kg_add_domain` | 新建域 | 初始化用 |
| `kg_add_cross_relation` | 域级关联 | 初始化用 |
| `kg_feedback` | 回报 entry 信息准确性 | 遥测进 querylog，不改图谱，无需 reason/确认 |

**所有写工具必填 `reason`**：一句话说明触发原因（哪个任务/验证了什么/发现了什么），
写入 changelog。"更新图谱"这种敷衍的 reason 应该被 review 打回。

### 写入校验规则（被拒绝时看这里）

- `code` 里的路径必须真实存在于项目（相对项目根；目录以 `/` 结尾；
  `_` 开头的 key 跳过校验，如 `{"_TODO": "未定位到主入口"}`）
- `related[].to` 必须是已存在的 entry id → 先建目标 entry，或先删这条边
- `type` ∈ system/feature/concept；`confidence` ∈ draft/verified
- 字段白名单外的 key 需用 `x_` 前缀（见 §11）
- 写入前跑全量校验，存量 ERROR 未修复时也会拒绝（防止在坏基础上叠加）

### 逃生口

人工批量修复时：设环境变量 `KG_ALLOW_DIRECT_EDIT=1` 绕过 hook 直接改文件，
改完**必须**跑 `validate.py` + `build_reverse_index.py`。

---

## 3. JSON Schema 规范

### 3.1 总体结构（主索引 + 域文件，两层）

图谱拆成两类文件：一个**主索引** + 若干**域文件**。分域让多人协作冲突小，
AI 先定位域再取 entry，避免一次读入全量。

**主索引 `graph.json`**——只放域清单和跨域关联，不含 entry 详情：

```json
{
  "version": "1.0",
  "updated_at": "2026-05-10",
  "domains": {
    "social": {
      "file": "graph-social.json",
      "desc": "社交关系：公会、邮件、好友、聊天",
      "key_entries": ["guild", "mail", "friend"]
    }
  },
  "cross_domain_relations": [
    { "from": "social", "to": "economy", "context": "拍卖/红包涉及货币", "confidence": "verified" }
  ]
}
```

**域文件 `graph-<domain>.json`**——每个域一个，内含该域所有 entry：

```json
{
  "version": "1.0",
  "domain": "social",
  "updated_at": "2026-05-10",
  "entries": {
    "<entry_id>": { "...entry 内容，见 3.2..." }
  }
}
```

> 域和跨域关联通过 `kg_add_domain` / `kg_add_cross_relation` 创建，
> `updated_at` 由写入口自动维护。完整模板见 [`templates/`](./templates)。

`<entry_id>` 用小写 + 下划线，例如 `guild`, `cross_server`, `guild_auction`。

### 3.2 Entry 字段规范

```json
{
  "guild": {
    "type": "system",                          // 必填: system | feature | concept
    "name_cn": "公会系统",                     // 必填: 中文名（人读用）
    "doc": "entries/guild.md",                 // 对应 MD 路径（kg_add_entry 自动生成默认值）
    "summary": "公会创建、成员管理、共享资源",  // 必填: 一句话描述（< 30 字）

    "code": {                                  // 必填: 代码定位（写入时强校验存在性）
      "manager": "src/.../GuildManager.java",
      "data": ["Guild.java", "GuildMemberData.java"],
      "dao": ["Guild_SDao.java"],
      "message": ["GuildMessageC2SProto.java"]
    },

    "related": [                               // 可选: 关联其他 entry
      {
        "to": "mail",
        "context": "入会/退会/系统通知走邮件",
        "confidence": "verified"               // draft | verified
      }
    ],

    "persistence_pitfalls": [                  // 可选: 持久化注意点（价值核心）
      "Guild.storeData 修改后必须 saveToDB",
      "Player.guildId 修改后必须 saveToDB + 通知公会成员"
    ],

    "tags": ["social", "core"]                 // 可选: 自由标签
  }
}
```

### 3.3 字段详解

#### `type`（必填）

- `system`：系统级（公会、邮件、战斗）
- `feature`：功能级（公会拍卖——某个 system 的子功能）
- `concept`：概念级（持久化机制、跨服同步规则——非代码实体）

判断标准：开发者会不会主动来查这个？会 → 进 entry。不会 → 不要建 entry。

#### `code`（必填）

代码定位。子字段 key 语义化，建议保持一致：

- `manager`：业务管理类（单数）
- `data` / `dao` / `message`：数据结构 / 持久化 / 消息协议类（数组）
- 其他项目特定的：`handler`, `script`, `config` ...
- `_` 开头的 key 是注释性内容，跳过路径校验（如 `_TODO`）

**路径用相对项目根的全路径**，目录以 `/` 结尾。写入时校验存在性，瞎编的路径进不来。

#### `related`（可选）

- `to`：目标 entry id（写入时校验存在性）
- `context`：一句话描述**具体怎么联动**（调用点/机制，不能空泛，< 50 字）
- `confidence`：`draft` 或 `verified`

**单向定义**：A 指向 B 即可，反向索引自动生成，`kg_query` 结果里的 `incoming` 就是它。

#### `persistence_pitfalls`（可选，价值核心）

字符串数组。每条一个具体踩坑，格式建议："XX 改后必须 YY"。追加用 `kg_add_pitfall`。

#### `tags`（可选）

自由标签，用于过滤和分组。例如 `["social", "core"]`。

### 3.4 Confidence 规则

只有两态：

- **`draft`**：骨架生成、未验证、或代码漂移可疑
- **`verified`**：在实际任务中验证过这条联动真实存在

升级：AI 在任务中用过这条边且确认正确 → 经用户同意调 `kg_verify_edge`。
降级/清理：`kg_query` 长期查不到某 entry（看 querylog）→ 删边或删 entry。

**AI 行为差异**：

- 遇到 `verified` 边 → 直接信任使用
- 遇到 `draft` 边 → 多 grep 一步验证后再用

---

## 4. MD Entry 写作规范

（MD 不受出入口管制，直接编辑；模板见 [`templates/entry.template.md`](./templates/entry.template.md)）

### 4.1 标准结构

```markdown
# <系统名>

## 是什么
2-3 段概念描述。这个系统在项目里负责什么、解决什么问题。

## 核心数据
- `Guild`: 公会主体聚合根
- `GuildMemberData`: 成员数据
（不超过 5-8 个核心数据结构，每条一行说明）

## 关键约定
- 改 `Guild.storeData` 必须调 `saveToDB()`
- 跨服公会同步只走 leader 节点

## 典型场景
什么样的需求 AI 应该来这个 entry：
- 加成员、踢成员、换会长
- 公会战、跨服公会战

## 踩坑历史
- 2026-03: 公会拍卖结束未触发邮件 → 修复方案 ...
```

### 4.2 不写什么

- 详细方法签名（看代码）
- 完整调用流程图（看代码 + JSON 已有 related）
- 重复 JSON 已有的关联列表
- 长篇大论的设计理由（除非真的关键）

### 4.3 长度控制

**理想** 100-200 行；**警戒** > 300 行；**必须砍** > 500 行（一定混入了源码细节）。

---

## 5. 工作流：初始化

### 5.1 第一次搭建（一次性，2-4 小时）

**Step 1: 安装**（1 分钟）

在发行包目录跑 `./install.sh /path/to/project`，重启 Claude Code 会话。

**Step 2: AI 生成骨架**（30 分钟）

跑 `/kg-init`（见 [`kg-init.md`](./kg-init.md)）。AI 会扫描项目 → 列候选核心系统
（你确认）→ 划分域（你确认）→ **全程通过 MCP 工具**建域、建 entry、加跨域关联
（全部 `draft`，reason 统一记 "kg-init 初始化"）→ 自动校验。

粒度标准：开发者能用**一个词**指代的（公会、经济、战斗、任务），10-20 个。
**不要**列每个 Manager 类，那是 javadoc，不是字典。

**Step 3: 人工补"约定 + 踩坑"**（2-3 小时）

这是**整个系统价值的 80% 来源**，不可省。对每个核心 entry，你口述/翻 commit log，
让 AI 用 `kg_add_pitfall` 逐条写入（reason 记来源），并把你确定的边 `kg_verify_edge`。

如果偷懒，图谱沦为目录级，1 个月后废弃。治理层防得住"写错"，防不住"没人写"。

**Step 4: 校验**（1 分钟）

`kg_validate`（或 `python .claude/kg/tools/validate.py`）。此时应无 ERROR——
写入口已经挡掉了所有结构性错误。

### 5.2 增量扩展（每周 30 分钟）

1. AI 查图谱发现某 entry 不存在 → 完成任务后建议 `kg_add_entry`
2. AI 用了某条 `draft` 边并验证正确 → 建议 `kg_verify_edge`
3. 出现新踩坑 → 建议 `kg_add_pitfall`

AI 只**建议**，你 yes/no。所有应用的变更自动进 changelog。

---

## 6. 工作流：日常使用

### 6.1 AI 视角的标准流程

```
用户: "帮我加一个公会拍卖功能"
  ↓
AI: 触发 kg-consult skill
  ↓
1. kg_query(query="公会 拍卖")
   → 命中 guild / auction，一次拿到 code、pitfalls、related、incoming
2. doc_exists 为 true 的 entry → 读 entries/guild.md 补充概念
3. 报告给用户：
   "本次任务涉及：guild, auction, mail（拍卖结束发邮件）
    需要注意：Guild.storeData 改了必须 saveToDB
    我会先 view: GuildManager.java, AuctionManager.java"
4. 直接 view 代码，开始实现
5. 完成后：对用过的 entry 各调一次 kg_feedback（准确/不准，遥测无需确认）；
   再建议 kg_verify_edge / kg_add_pitfall（用户确认后执行）
```

### 6.2 用户视角的最小干预

理想情况下：用户**什么都不用做**，skill 自动触发。

需要干预的场景：

- AI 没有自动查图谱 → 提醒"先查图谱"
- AI 找不到相关 entry → 追问"要加 entry 吗"或直接 fallback grep
- AI 用 `draft` 边但没验证 → 提醒"那条是 draft，先 grep 验证"

### 6.3 何时 fallback to grep（关键）

AI **必须** fallback 的场景：

1. `kg_query` 无命中，**且通读 `kg_catalog` 目录做语义判断后**确认没有相关 entry
   （字面无命中 ≠ 图谱没有，先走语义兜底再放弃）
2. entry 存在但 code 路径和实际代码对不上（顺手 `kg_update_entry` 修正）
3. confidence 全是 draft 且无法快速验证
4. 任务是 bug 排查（看 stack trace 比看图谱直接）

不要让 AI 在残缺图谱上硬猜。fallback 不是失败，是设计的一部分。

---

## 7. 工作流：更新维护

### 7.1 触发更新的时机

- **新功能完成时**：`kg_add_entry` / `kg_add_relation`
- **重构后**：`kg_update_entry` 修 code 路径
- **发现踩坑后**：`kg_add_pitfall`
- **验证了 draft 边**：`kg_verify_edge`

### 7.2 推荐：让 AI 看 git diff 给建议

不要靠你回忆改了什么。每次大改后：

```
用户: 我刚完成了公会拍卖功能。看 git diff，建议怎么更新图谱。

AI:
- 检测到新文件 GuildAuctionManager.java
- 建议 kg_add_entry(domain="social", entry_id="guild_auction", type="feature", ...)
- 建议 kg_add_relation(from_id="guild", to_id="guild_auction", confidence="draft", ...)
是否应用？
```

你只需 yes/no。应用后 changelog 自动留痕，出问题能查到这次建议。

### 7.3 校验接 git pre-commit

`.git/hooks/pre-commit`:

```bash
#!/bin/sh
python .claude/kg/tools/validate.py --strict || {
  echo "Knowledge graph validation failed. Fix errors or use --no-verify to bypass."
  exit 1
}
```

写入口保证增量正确，pre-commit 兜存量漂移（代码重构导致的路径失效）的底。

### 7.4 漂移追溯

发现图谱记录可疑时：

```bash
# 谁、什么时候、基于什么理由写入的？
grep '"entry_id": "guild"' .claude/kg/changelog.jsonl
# 这个 entry 有没有被用过？
grep '"guild"' .claude/kg/querylog.jsonl
```

changelog 记录了 update 操作的 before 值，必要时可以精确回滚单个字段。

---

## 8. 工具参考

### 8.1 kg_mcp_server.py（MCP server）

纯标准库 stdio 实现。注册方式：

**Claude Code**（`.mcp.json`，安装器自动配置）：

```json
{"mcpServers": {"kg": {"command": "python", "args": ["-X", "utf8", ".claude/kg/tools/kg_mcp_server.py"]}}}
```

**Codex**（`~/.codex/config.toml`）：

```toml
[mcp_servers.kg]
command = "python"
args = ["-X", "utf8", ".claude/kg/tools/kg_mcp_server.py"]
```

server 以启动时的 cwd 为项目根（`--root` 可覆盖），自动探测图谱目录。
每次工具调用重新加载图谱文件，外部改动（git pull）无需重启。

### 8.2 kg_guard_hook.py（防漂移 hook，Claude Code 专用）

PreToolUse hook，安装器自动注册到 `.claude/settings.json`（exec 形式，`${CLAUDE_PROJECT_DIR}` 锚定项目根）：

```json
{"hooks": {"PreToolUse": [{"matcher": "Edit|Write",
  "hooks": [{"type": "command", "command": "python",
             "args": ["-X", "utf8", "${CLAUDE_PROJECT_DIR}/.claude/kg/tools/kg_guard_hook.py"],
             "timeout": 10}]}]}}
```

> 用 `${CLAUDE_PROJECT_DIR}` 而非相对路径：Claude Code 跑 hook 时 cwd 是会话当前目录，
> 一旦 `cd` 进子目录，相对路径 `.claude/...` 就解析不到。`${CLAUDE_PROJECT_DIR}` 由
> Claude Code 直接替换成项目根绝对路径，Windows（PowerShell/Git Bash）与 Unix 通用。
> `install.py` 幂等：检测到旧的相对路径形式会原地升级，重跑 install 即修复历史安装。

拦截规则：文件名匹配 `graph*.json` / `reverse_index.json` / `*.jsonl` 且所在目录含
graph.json → 阻止并提示改用 MCP 工具。`entries/*.md` 放行。hook 自身异常时放行
（fail-open），不会阻塞正常开发。

### 8.3 validate.py（校验 CLI）

```bash
python .claude/kg/tools/validate.py             # 默认输出
python .claude/kg/tools/validate.py --strict    # 任何 WARNING 也 fail
python .claude/kg/tools/validate.py --json      # JSON 输出（CI 用）
```

检查项：

| 检查 | 级别 |
|---|---|
| JSON 解析失败 / 域声明的文件不存在 / entry_id 跨文件重复 | ERROR |
| entry 缺必填字段 / type/confidence 枚举非法 / related 结构错误 | ERROR |
| `related.to` 指向不存在的 entry | ERROR |
| code 路径在代码库不存在（存量漂移） | WARNING |
| 孤儿节点（无出边也未被引用）/ 边缺 confidence | WARNING |
| doc MD 未创建（按需填充，正常）/ draft 边统计 | INFO |

### 8.4 其他

```bash
# 手动重建反向索引（仅 KG_ALLOW_DIRECT_EDIT=1 人工直改后需要；MCP 写入会自动重建）
python .claude/kg/tools/build_reverse_index.py

# 生成 HTML 可视化（输出 graph_view.html 到图谱目录，浏览器打开）
python .claude/kg/tools/gen_graph_html.py
```

可视化除关系图外，头部显示累计查询次数；点击节点的详情面板显示**运营数据**：

- 查询命中次数（来自 querylog）
- 准确 / 不准反馈次数（来自 kg_feedback）
- 变更历史（来自 changelog：最近 5 次的时间 / 操作 / reason）

这些数据是 §12 退出决策和 entry 取舍（删/合并/优先修）的依据。

### 8.5 图谱复用：kg_pack / kg_unpack（装箱 / 拆箱）

相似项目（如同一套代码衍生）之间复用图谱积累：

```bash
# 在成熟项目 A 装箱（输出 kg-box-<项目名>.json 到图谱目录）
python .claude/kg/tools/kg_pack.py

# 把 box 文件拷到项目 B，在 B 的项目根拆箱
python .claude/kg/tools/kg_unpack.py kg-box-A.json
```

打包内容：域清单、跨域关联、全部 entry、已有的 MD 文档全文。
**不打包**日志（那是项目自己的历史）。

拆箱是**参考导入**，规则：

| 内容 | 处理 |
|------|------|
| 目标已有同名 entry | 跳过，不覆盖本地数据 |
| code 路径 | 逐条对目标项目校验：存在的保留；不存在的移入 `x_ref_code` 扩展字段待人工核对 |
| 关联边 / 跨域关联 | 两端存在才导入，confidence 一律降为 `draft`（未在本项目验证） |
| MD 文档 | 目标没有的写入，文件头标注来源和"需校对"提示 |
| 来源追溯 | 每个导入 entry 带 `x_ref_source`；changelog reason 记"拆箱导入自 X" |

拆箱后的收尾（拆箱工具会打印同样的提示）：

1. 逐个核对导入 entry——在本项目找到 `x_ref_code` 路径的对应实现后，
   用 `kg_update_entry` 移回 `code` 字段
2. draft 边在实际任务中验证后 `kg_verify_edge` 升级
3. 跑一次 `validate.py`

---

## 9. 颗粒度判断指南

最常见的纠结：什么算一个 entry？

### 9.1 决策树

```
这个东西，开发者会主动来查它吗？
├── 不会 → 不建 entry
└── 会 → 建 entry，继续判断 type:
    ├── 是个独立系统？ → type: system
    ├── 是某个 system 内的子功能？ → type: feature
    └── 是个跨系统的概念/规则？ → type: concept
```

### 9.2 例子

| 候选 | 建吗？ | 原因 |
|---|---|---|
| 公会 | ✓ system | 独立系统 |
| 公会拍卖 | ✓ feature | 子功能，跨 guild + auction |
| GuildManager 类 | ✗ | 单个类，写在 guild.code 即可 |
| 跨服同步机制 | ✓ concept | 跨多个系统的规则，值得单独写 |
| saveToDB 模式 | ✗ | 太通用，作为各 entry 的 persistence_pitfalls 即可 |
| Player.guildId 字段 | ✗ | 太细，作为 guild.persistence_pitfalls 即可 |

### 9.3 长大了再拆

先按系统级建 entry，发现某个 entry 的 MD > 300 行或频繁被特定子功能查询时，再拆 feature 级。

---

## 10. 常见问题

### Q: kg MCP 工具不可用（server 没起来）怎么办？

先重启会话（`.mcp.json` 是启动时读的）。仍不行：查询可以退化为直接 Read 图谱 JSON；
**写操作不许退化为直接编辑**——hook 会拦，就算没 hook（Codex）也会丢校验和日志。
修好 server 再写。

### Q: AI 的写入被拒绝了怎么办？

看错误信息，都是明确的：路径不存在 → 用 Glob 找真实路径；related 目标不存在 →
先建目标 entry；存量 ERROR 阻塞 → 先修存量（这是刻意的，防止在坏基础上叠加）。

### Q: 和 OpenSpec / Superpowers 这类框架一起用会冲突吗？

机制上不冲突：目录、MCP server 名、hooks 互相隔离，防漂移 hook 只拦图谱 JSON
且 fail-open，对其他框架的文件完全透明。需要管理的是两类软冲突：

1. **skill 触发竞争**——三者分层串联：spec 框架管"做什么"、流程框架管"怎么干活"、
   kg 管"代码在哪/影响什么"。skill 文档里有完整边界说明；建议在项目 CLAUDE.md
   写一条显式流水线固定顺序（需求 → 计划 → 动代码前查 kg → 实施 → 收尾反馈）
2. **双份 source of truth**——entry 只写现状（路径/联动/踩坑），引用规格写指针不复制

### Q: 项目已经有 6 万行的 wiki，怎么办？

废弃 / 冷藏。不要试图把它"压缩"成 graph。这套系统从零初始化 1 天搞定，比改造 wiki 快。

### Q: 图谱多大算太大？

单域 50 entry 是健康上限。超过就再拆域。AI 永远只查主索引 + 命中的域，不读全量。

### Q: 团队多人维护怎么避免冲突？

- 分域文件 + 结构化格式，git diff 友好
- changelog 里有每次变更的 reason，merge 冲突时看双方 reason 决定取舍
- `*.jsonl` 日志冲突：keep both（都是追加式记录）

### Q: AI 没自动查图谱怎么办？

检查 skill：trigger 条件是否明确、文件是否在 `.claude/skills/kg-consult/SKILL.md`。
如果都对，可能任务确实更适合直接 grep——skill 不强制查图谱是设计，避免小任务无谓加载。

### Q: confidence 全是 draft 怎么办？

正常。初始化后所有边都是 draft。**不要专门组织升级**，在自然使用中 `kg_verify_edge`
渐进升级。半年后还是 draft 且 querylog 里查不到 → 删掉它。

### Q: 图谱和实际代码漂移了怎么办？

三道防线按序生效：写入口拒绝新增漂移 → AI 使用中发现路径不对顺手 `kg_update_entry`
修正 → pre-commit / CI 跑 `validate.py` 报告存量漂移。追溯用 changelog（§7.4）。

### Q: HTML viewer 必须做吗？

不必须。已随工具附带（`gen_graph_html.py`），想看就生成，不看不影响任何功能。

---

## 11. 进阶：扩展 Schema

项目特殊需求可以扩展 entry 字段。规则：

- 新字段名前缀 `x_`（写入口对 `x_` 前缀放行，其他未知字段拒绝）
- 通过 `kg_add_entry` 的 `extra_fields` 参数传入，或 `kg_update_entry` 的 patch 直接带
- 必须**可选**（兼容已有 entry）

例如游戏项目：

```json
{
  "guild": {
    "...标准字段...": "...",
    "x_gm_commands": ["/guild create <name>", "/guild fillmember <count>"],
    "x_config_files": ["gameconfig/guild_level.csv"]
  }
}
```

但**先用标准 schema 跑 2-4 周再扩展**。早期扩展往往是过度设计。

---

## 12. 退出策略

诚实考虑：什么时候应该停掉这套系统。

- **querylog 3 个月没增长**：没人用，删掉，不要僵尸文件
- **AI 不查图谱直接 grep**：可能 skill 写得不好，或图谱质量太低 → 优先修而不是放弃
- **维护成本 > 节省的 token**：评估是否过度工程，简化或退回纯 markdown 文档

不要因为"已经投入了"就坚持。**沉没成本不是理由。**

---

下一步：跑 `install.sh` 装进项目，看 [`README.md`](./README.md) 的 30 秒快速开始。

---

## 13. 维护者：发版与分发

### 13.1 仓库结构

发行仓库（独立 Git 仓库）的**根 = dist 内容**：

```
kg-distribution/        # 仓库根 = dist/
├── install.py          # 安装器（也是升级器内部调用的入口）
├── VERSION             # 当前版本号，如 2.1.0
├── CHANGELOG.md        # 变更日志
├── tools/              # kg_core / kg_mcp_server / kg_admin / validate ...
├── skills/  templates/  examples/  *.md
└── ...
```

`install.py` 必须在仓库根（`kg_admin.py update` clone 后会找它）。

### 13.2 发版流程（改了工具行为后）

```bash
# 在源项目里改 tools/qx_rag/tools/，验证通过后：
python tools/qx_rag/tools/build_dist.py        # 同步到 dist/

# 递增版本（语义化：PATCH 补丁 / MINOR 新功能 / MAJOR 不兼容）
# 编辑 dist/VERSION 和 dist/CHANGELOG.md（顶部加一条）

# 在发行仓库提交 + 打 tag + 推送
cd <发行仓库>
git add -A && git commit -m "release vX.Y.Z"
git tag vX.Y.Z
git push && git push --tags
```

打完 tag，所有已装项目下次 `kg_admin.py check` 就能感知到新版本。

### 13.3 使用者的升级体验

使用者无需关心仓库细节，在已装项目里：

```bash
python .claude/kg/tools/kg_admin.py check     # "有新版本可用"
python .claude/kg/tools/kg_admin.py update    # 拉取升级，数据不动
```

若使用者首次安装时没传 `--repo`，用 `kg_admin.py config --repo <url>` 补录一次即可。

### 13.4 语义化版本约定

- **PATCH**（2.1.0→2.1.1）：bug 修复、不改接口
- **MINOR**（2.1.0→2.2.0）：新增工具/字段，向后兼容（旧图谱仍能用）
- **MAJOR**（2.x→3.0）：schema 或 MCP 协议不兼容变更（极少；需使用者在 CHANGELOG 注意迁移说明）
