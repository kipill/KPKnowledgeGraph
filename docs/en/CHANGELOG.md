# Changelog

[中文](../../CHANGELOG.md) | **English**

This file records version changes to the KPKnowledgeGraph distribution. Versions follow semver
(MAJOR.MINOR.PATCH). Users check for updates with `python .claude/kg/tools/kg_admin.py check` and
upgrade with `update`.

## 2.5.0 - 2026-07-24

- **Cross–AI-tool support: kg now installs for Codex / Cursor too** (MINOR, backward compatible,
  pure addition; existing projects pick it up via `kg_admin update`). Until now kg's trigger
  convention existed only as Claude Code's private skill / slash-command formats, which neither
  Codex nor Cursor parse — but the graph's truly tool-agnostic "gateway" is **MCP**, which all three
  tools support. This release lays down "the same MCP + the same trigger convention" in whatever
  file each tool recognizes:
  - **Codex**: `install.py` writes the `[mcp_servers.kg]` table into project-level
    `.codex/config.toml`; the trigger convention is merged into the project-root `AGENTS.md` (Codex
    reads it every session). The TOML is emitted with a few lines of hand-rolled serialization — no
    third-party TOML writer (keeps the zero-dependency rule); the result is validated with `tomllib`.
    Codex prompts for project trust before loading project-level MCP the first time — this release
    does **not** write `trust_level` for you (its semantics vary by version/global config, so writing
    it blindly is harmful); instead the installer prints a note to confirm trust when Codex asks.
  - **Cursor**: writes project-level `.cursor/mcp.json` (same `mcpServers.kg` shape as `.mcp.json`);
    the trigger convention deploys to `.cursor/rules/kg.mdc` (`alwaysApply: true`, auto-injected by
    Cursor).
  - Single-source trigger convention: adds `templates/AGENTS.kg.md` and `templates/cursor-kg.mdc`, a
    condensed version of the `kg-consult` skill (when to consult the graph first, how to query, writes
    go only through MCP, `kg_feedback` after a task) — three carriers, one source.
  - Everything is "merge / never-overwrite + idempotent": an existing MCP server is always skipped
    (never overwrites your config or your other servers); `AGENTS.md` is managed as a marked block
    (`<!-- KG:BEGIN -->` / `<!-- KG:END -->`), replaced as a whole on re-run rather than appended
    again, leaving your content outside the markers untouched.
  - `kg_admin update` (`install.py --refresh-tools`) **backfills** too: existing projects get the
    Codex/Cursor config on upgrade, but again only what's missing — it touches no existing config,
    consistent with the original "update never overwrites user config" contract, just widened to
    "fill in the gaps".
- ⚠ **Known asymmetry**: Codex/Cursor have no PreToolUse hook like Claude Code's, so direct edits to
  `graph*.json` cannot be hard-blocked there — "don't edit the graph directly" rests only on the
  textual convention in `AGENTS.md` / cursor rules (written as an explicit warning in the generated
  files). The hard guarantee of graph consistency still holds only under Claude Code + the hook.

## 2.4.0 - 2026-07-10

- **Added the "capability catalog + reuse recommendation" experience layer** (MINOR, backward
  compatible, no migration needed for existing graphs). It solves a request-triage problem:
  requesters phrase requests as a **description** (e.g. "send the user a notification after they place
  an order"), and without digging in these tend to be built as new features — when an existing configurable
  capability (an enum member) would do the job with a bit of configuration. Adds 4 MCP tools:
  - `kg_add_capability_catalog`: catalog a "capability catalog" — an enum/constant family of a
    configurable behavior (members are behavior variants, consumed by switch/config tables, and
    requesters describe rather than name them). Carried as a `type=concept` entry plus an
    `x_capability_members` extension field. Fact fields are organized by the LLM reading the source;
    semantic fields (scenarios/reuse_note) are drafted and then written after the user confirms
    (human-in-the-loop on the write side).
  - `kg_add_capability_members`: append/update members on an existing capability catalog (merge
    semantics: an existing enum_value is overwritten, a new one is appended). Used to catalog large
    enums in batches (tens to hundreds of members) or to refine scenarios/reuse_note later; returns
    updated/added counts.
  - `kg_scout_reuse`: the reuse-recommendation triage gate. Query this first when a request would
    build a new capability; the tool does a keyword **coarse ranking** over name/scenarios/reuse_note
    and returns the top-5 relevant members; the LLM does the **fine ranking** (reads reuse_note to
    judge whether the request carries qualifiers beyond the capability's semantics, and grades
    recommend/reference), relays it to the user with options, and waits for the human to decide. It
    deliberately does not return a copy-pasteable config string, forcing human confirmation.
  - `kg_report_reuse_outcome`: write the recommendation outcome (reuse/new/misunderstood) back to
    `reuse_feedback.jsonl` (telemetry).
  - `kg_get_reuse_stats`: aggregate feedback, counting recommendations/adoptions/adoption rate per
    member, graded by threshold (<3 = unverified / ≥10 and adoption rate >70% = trusted).
- The `kg-consult` skill gains a "reuse recommendation (triage gate)" step, placed ahead of the fact
  query.
- `validate.py` / `kg_validate` gains capability-catalog structure validation (enum_value required
  and deduplicated, status legal, warning when scenarios are missing; no source cross-check).
- **Visualization (kg-view) extended**: a capability catalog renders as a gold-bordered diamond node;
  clicking it shows a member list in the detail panel — each member carries reuse-stat badges
  (recommended/reused/adoption rate + grade: unverified/normal/trusted), deprecated members are
  pinned to the bottom with a marker, and the source enum is attached. Supported in both static
  export and the live server.

## 2.3.5 - 2026-07-04

- Fixed `kg_guard_hook` crashing under subdirectories. The hook was registered with a **relative**
  path `python -X utf8 .claude/kg/tools/kg_guard_hook.py`, but Claude Code runs hooks with cwd =
  **session current directory** — once you `cd` into a subdir (e.g. `backend/`), the relative path no
  longer resolves, Python exits non-zero ("can't open file ... kg_guard_hook.py"), and Claude Code
  treats that as a block; the script's own fail-open never runs. Switched to **exec form +
  `${CLAUDE_PROJECT_DIR}`**: Claude Code substitutes the placeholder to an absolute project-root path
  before spawning, independent of any shell, working cross-platform (Windows PowerShell/Git Bash and
  Unix). `install.py` is now idempotent — it detects and upgrades the legacy relative-path form in
  place, so **affected users fix it by re-running `install.py`** (`kg_admin update` intentionally
  never touches settings.json).

## 2.3.4 - 2026-07-04

- Fixed a visualization crash on page open: `Cannot read properties of null (reading
  'addEventListener')`. The tooltip and draft-edge verification modal DOM elements were placed after
  the `<script>` tag, so the script ran before those elements were parsed. They are now moved before
  the `<script>` tag.

## 2.3.3 - 2026-07-04

- Visualization UI improvements:
  - Edge tooltip is larger (max-width 460px, 14px font, more padding) and now detects viewport
    edges to avoid clipping near screen borders.
  - Added a **node hover tooltip** showing the node summary, domain, and type.
  - Nodes now use different shapes by `type`: `system` round-rectangle, `module` rectangle,
    `service` ellipse, `api` diamond, `entity` hexagon.
  - The draft-edge verification modal now shows node Chinese names for from/to, improving readability.
  - Fixed a detail in static export where the operations summary was empty: `summary` is now
    included in the generated HTML.

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