# Changelog

[中文](../../CHANGELOG.md) | **English**

This file records version changes to the KPKnowledgeGraph distribution. Versions follow semver
(MAJOR.MINOR.PATCH). Users check for updates with `python .claude/kg/tools/kg_admin.py check` and
upgrade with `update`.

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