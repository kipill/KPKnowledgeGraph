# 变更日志

**中文** | [English](./docs/en/CHANGELOG.md)

本文件记录知识图谱发行包（dist）的版本变更。版本号遵循语义化版本（MAJOR.MINOR.PATCH）。
使用者用 `python .claude/kg/tools/kg_admin.py check` 检查更新，`update` 升级。

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
