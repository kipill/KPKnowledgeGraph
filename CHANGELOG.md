# 变更日志

**中文** | [English](./docs/en/CHANGELOG.md)

本文件记录知识图谱发行包（dist）的版本变更。版本号遵循语义化版本（MAJOR.MINOR.PATCH）。
使用者用 `python .claude/kg/tools/kg_admin.py check` 检查更新，`update` 升级。

## 2.5.0 — 2026-07-24

- **跨 AI 工具支持：Codex / Cursor 一并铺好 kg**（MINOR，向后兼容，纯新增，旧项目 `kg_admin update` 即可补齐）。此前 kg 的触发约定只以 Claude Code 私有的 skill / 斜杠命令形式存在，Codex 与 Cursor 都不解析这些格式——它们能用的是图谱真正工具无关的「网关」：**MCP**（三个工具都支持）。本版把「同一套 MCP + 同一套触发约定」铺到每个工具各自认的载体：
  - **Codex**：`install.py` 写入项目级 `.codex/config.toml` 的 `[mcp_servers.kg]` 表；触发约定合并进项目根 `AGENTS.md`（Codex 每会话自动读）。TOML 用几行手写序列化，不引入第三方 TOML 写库（守零依赖）；生成结果经 `tomllib` 验证合法。首次在项目中会由 Codex 提示信任（trust）才加载项目级 MCP——本版不代写 `trust_level`（其 semantics 因版本/全局配置而异，误写有害），改为安装时打印提示让用户按 Codex 引导确认。
  - **Cursor**：写入项目级 `.cursor/mcp.json`（结构与 `.mcp.json` 相同的 `mcpServers.kg`）；触发约定部署为 `.cursor/rules/kg.mdc`（`alwaysApply: true`，Cursor 自动注入）。
  - 触发约定单点维护：新增 `templates/AGENTS.kg.md` 与 `templates/cursor-kg.mdc`，内容是 `kg-consult` skill 的凝缩版（何时先查图谱、怎么查、写图谱只走 MCP、任务后 kg_feedback），三处载体同源。
  - 全部「合并 / 不覆盖 + 幂等」：已存在的 MCP server 一律跳过（绝不覆盖用户配置或用户已有的其它 server）；`AGENTS.md` 用 `<!-- KG:BEGIN -->` / `<!-- KG:END -->` 标记整段管理，重跑整段替换而非重复追加，标记外的用户内容不动。
  - `kg_admin update`（`install.py --refresh-tools`）也会**补缺失**：老项目升级后自动拿到 Codex/Cursor 配置，但同样只补尚不存在的项，不碰任何已有配置——与原有「update 不覆盖用户配置」的契约一致，只是范围扩到「补齐」。
- ⚠ **已知非对称**：Codex/Cursor 没有 Claude Code 的 PreToolUse hook 机制，无法强制拦截对 `graph*.json` 的直接编辑——那里「禁止直接改图谱」只能靠 `AGENTS.md` / cursor rules 的文字约定自律（生成物中已写成显式警告）。图谱一致性的硬保证仍只在 Claude Code + hook 环境下成立。

## 2.4.0 — 2026-07-10

- **新增「能力目录 + 复用推荐」经验层**（MINOR，向后兼容，旧图谱无需迁移）。解决一类需求分诊问题：需求方用「描述」提需求（如「玩家上线发个奖励」），若不深挖易被当新功能开发，而其实现成的可配置能力（枚举成员）配一下就能实现。新增 4 个 MCP 工具：
  - `kg_add_capability_catalog`：录入「能力目录」——某个可配置行为的枚举/常量族（成员是行为变体、被 switch/配表消费、需求方用描述而非点名）。承载为 `type=concept` 的 entry + `x_capability_members` 扩展字段。事实字段由 LLM 读源码整理、语义字段（scenarios/reuse_note）起草后经用户确认写入（写入侧人在环里）。
  - `kg_add_capability_members`：往已有能力目录追加/更新成员（merge 语义：enum_value 已存在→更新覆盖，新的→追加）。用于分批录入大枚举（几十~上百成员）或后续完善 scenarios/reuse_note，返回更新/新增计数。
  - `kg_scout_reuse`：复用推荐分诊闸门。新造能力的需求先查这个，接口对 name/scenarios/reuse_note 做关键词**粗排**返回 top-5 相关成员；LLM 做**精排**（读 reuse_note 判断需求是否含超出能力语义的限定词，分级 recommend/reference），转述给用户并给选项，等人拍板。刻意不返回可照抄配置串，逼人工确认。
  - `kg_report_reuse_outcome`：回写推荐结果（reuse/new/misunderstood）到 `reuse_feedback.jsonl`（遥测）。
  - `kg_get_reuse_stats`：聚合反馈，按成员统计推荐次数/采纳次数/采纳率，按阈值分级（<3 次=待验证 / ≥10 次且采纳率>70%=高置信）。
- `kg-consult` skill 增加「复用推荐（分诊闸门）」步骤，前置于事实查询。
- `validate.py`/`kg_validate` 增加能力目录结构校验（enum_value 必填/去重、status 合法、无 scenarios 提示；不做源码交叉校验）。
- **可视化（kg-view）扩展**：能力目录渲染成金边菱形节点，点击详情面板展示成员列表——每个成员带复用统计徽章（推荐/复用/采纳率 + 分级：待验证/一般/高置信），deprecated 成员置底标注，附来源枚举。静态导出与动态 server 均支持。

## 2.3.5 — 2026-07-04

- 修复 `kg_guard_hook` 在子目录下崩溃：hook 此前注册成相对路径 `python -X utf8 .claude/kg/tools/kg_guard_hook.py`，而 Claude Code 跑 hook 时 cwd 是**会话当前目录**——一旦 `cd` 进子目录（如 `backend/`），相对路径解析不到脚本，Python 退出码非 0 被 Claude Code 当作拦截，脚本内部的 fail-open 根本没机会执行（报错 `can't open file ... kg_guard_hook.py`）。改为 **exec 形式 + `${CLAUDE_PROJECT_DIR}`**：Claude Code 自己把占位符替换成项目根绝对路径再 spawn，不依赖 shell 变量展开，Windows（PowerShell/Git Bash）与 Unix 通用。`install.py` 改为幂等：检测到旧的相对路径形式会原地升级，**受影响用户重跑 `install.py` 即修复**（`kg_admin update` 按契约不碰 settings.json）。

## 2.3.4 — 2026-07-04

- 修复可视化页面打开时报 `Cannot read properties of null (reading 'addEventListener')` 的崩溃：tooltip 与 draft 边验证 modal 的 DOM 元素被放在 `<script>` 之后，导致脚本执行时还未解析到这些元素。现已将它们移到 `<script>` 之前。

## 2.3.3 — 2026-07-04

- 可视化页面 UI 改进：
  - 边关系提示框进一步加大（最大宽度 460px、字体 14px、padding 加大），并增加屏幕边界检测，避免贴边时被截断。
  - 新增**节点悬停提示框**，显示节点摘要、所属域与类型。
  - 节点按 `type` 区分形状：`system` 圆角矩形、`module` 矩形、`service` 椭圆、`api` 菱形、`entity` 六边形。
  - draft 边验证 modal 中 from/to 显示节点中文名，提升可读性。
  - 修复静态导出页面运营汇总数据为空的细节：现在会把 `summary` 一并写入 HTML。

## 2.3.2 — 2026-07-04

- 可视化页面 UI 改进：
  - 边关系描述改成**自定义 tooltip**（更大字体、深色背景、跟随鼠标），替代原来 cytoscape 自带的 9px 小标签。
  - 点击 draft 边验证时，用**自定义 modal 确认框**替代浏览器原生 `prompt`/`alert`，显示 from→to、context、reason 输入框、确认/取消按钮，支持 ESC / 点击遮罩关闭。

## 2.3.1 — 2026-07-04

- `gen_graph_html.py --serve` 加 `--idle-timeout` 参数（默认 1800 秒 = 30 分钟），无请求自动停止，防止 skill 或 AI 意外退出后 server 残留。
- `kg-view` skill 文档说明手动 Ctrl+C 与 skill TaskStop 两种关闭方式，以及 30 分钟 idle 兜底。

## 2.3.0 — 2026-07-04

- **新增 `kg-view` skill**：用户说"看图谱 / 可视化 / 关系图"时，AI 自动后台启动可视化 server、返回浏览器地址、看完停止（不再需要手动敲命令）。
- `install.py` 的 skill 部署从硬编码 `kg-consult` 改为遍历 `skills/*.skill.md`，新增 skill 自动随安装 / 升级（`kg_admin update`）部署。

## 2.2.1 — 2026-07-04

- 修复 `kg_mcp_server` 的 `serverInfo.version` 滞后：改为从 `VERSION` 文件动态读取，不再硬编码（此前一直停在 2.0.0，不随发版更新）。

## 2.2.0 — 2026-07-04

- **可视化动态化**：`gen_graph_html.py` 新增 `--serve` 模式，起本地 server（仅 127.0.0.1、自动选可用端口、启动返回查看地址），浏览器实时查看图谱，并支持在页面直接把 draft 边标记为 verified——写操作经 `kg_core.verify_edge`，校验 / changelog / 反向索引全走，与 AI 调 kg MCP 工具等价（守治理层，ADR-004）。无 `--serve` 时仍生成静态 `graph_view.html`。
- **cytoscape 本地化**：前端库随发行包提供（`tools/vendor/cytoscape.min.js`），去掉 CDN 依赖，可视化零外网依赖；静态导出模式内联 cytoscape，保持单文件可离线分享。
- `install.py` 的 `deploy_tools` 增加 vendor 部署；`kg_admin update` 可随之升级 cytoscape 版本。

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
