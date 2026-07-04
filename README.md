# KPKnowledgeGraph

**中文** | [English](./docs/en/README.md)


> 一份成长型的知识图谱 —— 让 AI 编程助手**先查图谱再读代码**。

为 AI 编程助手（Claude Code / Codex 等）优化的项目知识图谱。用 **MD 做"字典"**、
**JSON 做"索引"**、**MCP 做"唯一出入口"**，让 AI 在做新需求时快速定位代码、识别跨模块联动、
避开持久化陷阱——减少 grep 浪费，减少跨模块漏改，且**图谱本身不会漂移成废文档**。

## 为什么需要它

AI 在不熟悉的代码库里"瞎找"非常贵：多次 grep、读一堆文件、还可能基于错误假设写代码，
token 消耗差 5-10 倍，且经常漏掉跨模块联动。传统 wiki 体量太大、信息密度低、维护就漂移。

KPKnowledgeGraph 是**面向中小型项目的开发经验知识图谱**。传统的代码层知识图谱
（AST、调用图、类图）告诉 AI"代码长什么样"，却无法告诉它"这个项目该怎么改"。
真正昂贵的知识——哪些字段改了必须 `saveToDB`、跨服边界在哪里、重构时要顺带改谁、
哪些"约定"是新人最容易踩的坑——往往只存在于核心开发者的记忆或零散的代码注释里。

它要把这些**项目实际开发经验**快速复制给 AI，而不是每次靠用户写 prompt 提醒 AI，
或让 AI 自己从头扫代码分析。AI 不再是仅靠自身通用记忆工作的黑盒，而是逐渐成为
**核心开发者的复刻**：你越主动维护它，它越懂你的项目。

KPKnowledgeGraph 给 AI 的是**导航**而非百科全书：系统在哪、改这里会牵涉谁、有什么坑。
更关键的是——它有一套**治理机制**保证写进去的都是对的、可追溯的，不会随时间腐烂。

## 核心特性

- **🧭 两段式查询**：`kg_query` 字面匹配（快路径）+ `kg_catalog` 语义兜底（关键词失灵时 AI 通读目录挑选）
- **🔒 唯一读写出入口**：所有图谱读写走 MCP 工具，写入强校验（代码路径必须真实存在、关联目标必须存在、操作原因必填）
- **🛡️ 防漂移**：PreToolUse hook 拦截对图谱 JSON 的直接编辑，杜绝"AI 绕过校验乱写"
- **📝 全程审计**：`changelog.jsonl` 记每次修改（谁/何时/改了什么/为什么），`querylog.jsonl` 记每次查询
- **📊 运营可视化**：每个系统的查询命中、准确/不准反馈、变更历史，数据驱动迭代取舍
- **👁️ 可视化浏览**：浏览器查看系统关系图，支持点 draft 边直接标记为 verified；可导出静态 `graph_view.html`，也可启动实时本地 server
- **🔄 图谱复用**：`kg_pack` / `kg_unpack` 在相似项目之间装箱/拆箱，复用积累的踩坑经验
- **⬆️ 就地升级**：`kg_admin.py update` 类似 `claude update`，已装项目一条命令拉取最新版（只换工具层，图谱数据不动）
- **🌐 跨工具通用**：Claude Code 与 Codex 都能用，纯 Python 标准库实现，零第三方依赖

## 30 秒安装

> 需要 Python 3。在**目标项目根目录**下运行本仓库的 install 脚本：

```bash
# macOS / Linux / Git Bash
./install.sh                  # 安装到当前目录
./install.sh /path/to/project # 安装到指定项目
```

```powershell
# Windows PowerShell
.\install.ps1                 # 安装到当前目录
.\install.ps1 -TargetPath C:\path\to\project
```

installer 会创建 `<项目>/.claude/kg/`（图谱目录 + 工具）、skill、`/kg-init` 命令，
并自动合并注册 `.mcp.json`（MCP server）和 `.claude/settings.json`（防漂移 hook）——
幂等，不覆盖已有配置。装完重启 Claude Code 会话，然后跑：

```
/kg-init
```

AI 会扫描项目结构 → 列候选核心系统（你确认）→ 划分域 → 全程通过 MCP 工具生成图谱骨架
（全 `draft`）→ 自动校验。

## 快速开始

### 1. 初始化（一次性）

安装后重启 Claude Code，运行：

```
/kg-init
```

AI 扫描项目 → 列候选系统（你确认）→ 划分域 → 通过 MCP 工具生成图谱骨架（全 `draft`）→ 自动校验。

### 2. 补"约定和踩坑"（价值的 80%）

骨架只是目录。接下来 2–4 小时，对每个核心系统：

- 口述或翻 commit log，让 AI 用 `kg_add_pitfall` 写入持久化踩坑
- 把确定的 `related` 边用 `kg_verify_edge` 从 `draft` 升为 `verified`

这些经验是图谱价值的核心——治理层防得住"写错"，但防不住"没人写"。

### 3. 日常使用

开发新需求时，AI 会自动触发 `kg-consult` skill：

1. `kg_query` 关键词搜索相关 entry
2. 没命中就 `kg_catalog` 语义兜底
3. `kg_get_entry` 取详情（含代码路径、踩坑、出边/入边）
4. 直接 view 代码，跳过盲目 grep
5. 完成后 AI 会建议 `kg_verify_edge` / `kg_add_pitfall`，你 yes/no 即可

### 4. 可视化查看

```bash
# 导出静态 HTML（自包含、可分享）
python -X utf8 .claude/kg/tools/gen_graph_html.py

# 启动动态本地 server（实时数据、点 draft 边可验证）
python -X utf8 .claude/kg/tools/gen_graph_html.py --serve
```

### 5. 校验与升级

```bash
# 校验图谱完整性
python -X utf8 .claude/kg/tools/validate.py

# 检查并拉取最新版（只换工具层，图谱数据不动）
python .claude/kg/tools/kg_admin.py check
python .claude/kg/tools/kg_admin.py update
```

详细用法、schema、MCP 工具说明见 [DEVELOPMENT.md](./DEVELOPMENT.md)。

## 版本更新（`claude update` 式）

已装项目自带升级器，一条命令查远端最新版并就地升级。**只换工具层，图谱数据分毫不动。**

```bash
# 首次安装时记录本仓库地址（或事后补录）
python .claude/kg/tools/install.py . --repo https://github.com/kipill/KPKnowledgeGraph.git
python .claude/kg/tools/kg_admin.py config --repo https://github.com/kipill/KPKnowledgeGraph.git

# 在任意已装项目里
python .claude/kg/tools/kg_admin.py version    # 本地版本
python .claude/kg/tools/kg_admin.py check      # 有没有新版
python .claude/kg/tools/kg_admin.py update     # 拉取升级，数据不动
```

升级安全边界：`update` 只覆盖 `tools/*.py`、`skills/`、`commands/`、`templates/`、`VERSION`；
绝不碰 `graph*.json`、`entries/`、日志、`.mcp.json`、`settings.json`。

### Codex 用户

MCP server 是通用 stdio 实现。在 `~/.codex/config.toml` 加：

```toml
[mcp_servers.kg]
command = "python"
args = ["-X", "utf8", ".claude/kg/tools/kg_mcp_server.py"]
```

并在项目 `AGENTS.md` 约定：图谱读写一律走 kg_* MCP 工具，禁止直接编辑 graph*.json。

## 何时用 / 何时不用

**适合**：项目有 10+ 个核心模块，grep 已经不好定位；存在大量代码里看不出来的隐式约定
（持久化时序、跨服边界、状态机契约）；愿意每周花 ~30 分钟维护。

**不适合**：项目 < 10 个模块（直接 grep 更快）；项目还在剧烈变化（图谱漂移速度 > 维护速度）；
没人愿意维护（治理层防得住"写坏"，防不了"没人写"）。

## 文件导航

| 文件 / 目录 | 看这个如果你想... |
|---|---|
| [DESIGN.md](./DESIGN.md) | 理解为什么这样设计、决策依据（ADR）、什么不做 |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | 实际去用、扩展、维护——schema、MCP 工具、工作流、发版流程 |
| [templates/](./templates) | 拿现成模板填自己项目（graph 主索引 / 域文件 / entry MD） |
| [examples/](./examples) | 真实例子（中性化的系统，含 [graph_view.html](./examples/graph_view.html) 可视化 demo） |
| [tools/](./tools) | kg_core 核心库、MCP server、hook、升级器、校验/可视化 CLI |
| [skills/kg-consult.skill.md](./skills/kg-consult.skill.md) | Claude skill 定义（决定 AI 何时自动查图谱） |
| [kg-init.md](./kg-init.md) | `/kg-init` 命令（AI 扫代码生成初始骨架） |
| [CHANGELOG.md](./CHANGELOG.md) | 版本变更记录 |
| [docs/en/](./docs/en/) | English documentation (README / DESIGN / DEVELOPMENT / CHANGELOG) |

## 设计理念

- **MD 写"为什么"，JSON 写"在哪里"，MCP 管"怎么写"**——三层边界硬规则
- **机制强制的规范 > 文档承诺的规范**：写入校验、审计日志、防绕行 hook 把图谱质量下限从"取决于 AI 自觉"抬到"进来的都是对的"
- **不强制填满，按需驱动**：开发到哪个系统再补那个 entry，未填充是正常状态
- **代码是 source of truth**：图谱只是加速器，路径漂移时以代码为准顺手修正
- **让它"被用"而不是"完整"**：用 querylog 数据驱动清理，不追求大而全
- **AI 是开发者的复刻，而不是只有自己的记忆**：把项目特有的约定、踩坑、跨模块联动写进图谱，AI 就能继承这些经验，而不是每次重新分析代码
- **主动维护才会越用越聪明**：图谱不会自动变完整，但每一次 `kg_verify_edge`、每一条 `kg_add_pitfall`、每一次 `kg_feedback` 都会让它更贴近你的项目和习惯

详见 [DESIGN.md](./DESIGN.md)。

## 贡献

欢迎提 issue 和 PR。改动工具行为时请递增 `VERSION` 并在 `CHANGELOG.md` 顶部加一条。
开发约定见 [DEVELOPMENT.md](./DEVELOPMENT.md) §13。

## 协议

[Apache License 2.0](./LICENSE)
