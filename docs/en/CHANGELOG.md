# Changelog

[中文](../../CHANGELOG.md) | **English**

This file records version changes to the KPKnowledgeGraph distribution. Versions follow semver
(MAJOR.MINOR.PATCH). Users check for updates with `python .claude/kg/tools/kg_admin.py check` and
upgrade with `update`.

## 2.3.2 - 2026-07-04

- Visualization UI improvements:
  - Edge context tooltip is now a custom floating box (larger font, dark background, follows
    the mouse) instead of the tiny 9px cytoscape label.
  - Clicking a draft edge opens a custom modal confirmation dialog instead of browser-native
    `prompt`/`alert`, showing from→to, context, a reason input, and confirm/cancel buttons.
    Supports ESC and clicking the backdrop to close.

## 2.3.1 - 2026-07-04

- `gen_graph_html.py --serve` adds `--idle-timeout` (default 1800s = 30min). Server auto-stops
  after idle time, preventing zombie servers if the skill or Claude Code exits unexpectedly.
- `kg-view` skill docs explain manual Ctrl+C vs skill TaskStop shutdown, plus the 30-min idle fallback.

## 2.3.0 - 2026-07-04

- **New `kg-view` skill**: when the user says "show the graph / visualize / relationship graph",
  the AI auto-starts the viewer server in the background, returns the URL, and stops it when done
  (no need to run the command manually).
- `install.py` skill deployment changed from hardcoded `kg-consult` to iterating `skills/*.skill.md`,
  so new skills deploy automatically on install / upgrade (`kg_admin update`).

## 2.2.1 - 2026-07-04

- Fix `kg_mcp_server`'s `serverInfo.version` being stale: now read dynamically from the `VERSION`
  file instead of hardcoded (it was stuck at 2.0.0 and never tracked releases).

## 2.2.0 - 2026-07-04

- **Dynamic visualization**: `gen_graph_html.py` gains a `--serve` mode — a local server (127.0.0.1
  only, auto-selects a free port, prints the view URL) serving live graph data, with in-page
  draft→verified marking. The write goes through `kg_core.verify_edge`, so validation / changelog /
  reverse-index all apply — equivalent to the AI calling the kg MCP tool (governance preserved,
  ADR-004). Without `--serve` it still exports a static `graph_view.html`.
- **Cytoscape localized**: the front-end library ships in the dist (`tools/vendor/cytoscape.min.js`);
  the CDN dependency is removed so visualization works offline. Static export inlines cytoscape to
  keep a single self-contained file.
- `install.py`'s `deploy_tools` now deploys `vendor`; `kg_admin update` can upgrade the bundled
  cytoscape.

## 2.1.0 - 2026-07-03

- **Governance layer (v2)**: MCP single read/write gateway; writes strictly validated (code path /
  related target / reason mandatory); changelog/querylog audit; reverse index auto-rebuilt
- **Drift-proof**: PreToolUse hook blocks direct edits to graph JSON; escape hatch KG_ALLOW_DIRECT_EDIT=1
- **Two-stage query**: kg_query (literal fast path) + kg_catalog (semantic fallback - AI reads the
  catalog and picks when keywords miss)
- **Telemetry & visualization**: kg_feedback reports accuracy; visualization shows per-entry query
  hits / feedback / change history + a global summary (kg_stats)
- **Graph reuse**: kg_pack / kg_unpack to box/unbox between similar projects
- **Self-management**: kg_admin.py (version/check/update/config), like `claude update`
- **Cross-tool**: Claude Code and Codex both supported; installer auto-merges .mcp.json and hook
- Fixed an empty-graph visualization crash

## 2.0.0 - 2026-06

- v1 -> v2 refactor: from "AI directly edits JSON + manual validation" to "MCP gateway + enforced mechanism"
- Data schema is v1-compatible