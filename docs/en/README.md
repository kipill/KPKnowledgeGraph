# KPKnowledgeGraph

> A knowledge graph that grows with your project — so AI coding assistants **check the graph before reading code**.

[中文](../../README.md) | **English**

A project knowledge graph optimized for AI coding assistants (Claude Code, Codex, etc.).
It uses **Markdown as the "dictionary"**, **JSON as the "index"**, and **MCP as the "single gateway"**
so the AI can quickly locate code, spot cross-module impact, and avoid persistence traps when working
on a new feature — cutting grep waste, reducing missed cross-module changes, and keeping the graph
itself **from rotting into dead documentation**.

## Why you need it

When AI "fumbles around" an unfamiliar codebase it's expensive: multiple greps, reading a pile of
files, possibly writing code on wrong assumptions. Token consumption differs by 5-10x, and cross-module
impact is frequently missed. Traditional wikis are too large, low-density, and drift the moment
maintenance lapses.

KPKnowledgeGraph is a **development-experience knowledge graph for small-to-medium projects**.
Traditional code-level knowledge graphs (ASTs, call graphs, class diagrams) tell the AI what the code
*looks like*, but not *how this project should be changed*. The truly expensive knowledge — which
fields must be saved to DB after mutation, where the cross-server boundary is, which systems must be
updated together during a refactor, the conventions newcomers trip over — usually lives only in the
lead developer's head or scattered code comments.

It copies that **project-specific development experience** to the AI, instead of relying on the user
to remind the AI via prompts every time or making the AI analyze the codebase from scratch. The AI
stops being a black box that relies solely on its generic memory and gradually becomes a **replica of
the core developer**: the more actively you maintain it, the better it understands your project.

KPKnowledgeGraph gives the AI **navigation**, not an encyclopedia: where a system is, what a change
touches, what the traps are. Crucially, it has a **governance mechanism** that guarantees what gets
written in is correct and traceable — so it doesn't rot over time.

## Key features

- **🧭 Two-stage query**: `kg_query` literal match (fast path) + `kg_catalog` semantic fallback (when keywords miss, the AI reads the lightweight catalog and picks semantically)
- **🔒 Single read/write gateway**: all graph access goes through MCP tools; writes are strictly validated (code paths must really exist, related targets must exist, a reason is mandatory)
- **🛡️ Drift-proof**: a PreToolUse hook blocks direct edits to graph JSON, eliminating "AI bypassing validation"
- **📝 Full audit**: `changelog.jsonl` records every change (who / when / what / why); `querylog.jsonl` records every query
- **📊 Operational visibility**: query hits, accurate/inaccurate feedback, and change history per system — data-driven iteration
- **👁️ Visual browser**: view the system-relationship graph in a browser, click a draft edge to mark it verified directly; export a static `graph_view.html` or start a live local server
- **🔄 Graph reuse**: `kg_pack` / `kg_unpack` to box/unbox between similar projects, reusing accumulated pitfall knowledge
- **⬆️ In-place upgrade**: `kg_admin.py update` works like `claude update` — one command in any installed project pulls the latest (only the tool layer; graph data is untouched)
- **🌐 Cross-tool**: works with both Claude Code and Codex; pure Python standard library, zero third-party deps

## 30-second install

> Requires Python 3. Run this repo's install script from the **target project root**:

```bash
# macOS / Linux / Git Bash
./install.sh                  # install into the current directory
./install.sh /path/to/project # install into a specific project
```

```powershell
# Windows PowerShell
.\install.ps1                 # install into the current directory
.\install.ps1 -TargetPath C:\path\to\project
```

The installer creates `<project>/.claude/kg/` (graph dir + tools), the skill, the `/kg-init` command,
and auto-merges registration of `.mcp.json` (MCP server) and `.claude/settings.json` (drift-proof hook) —
idempotent, never overwrites existing config. Restart your Claude Code session, then run:

```
/kg-init
```

The AI scans the project structure → lists candidate core systems (you confirm) → groups domains →
generates the graph skeleton entirely through MCP tools (all `draft`) → auto-validates.

## Quick start

### 1. Initialize (one-time)

After installing, restart Claude Code and run:

```
/kg-init
```

The AI scans the project → lists candidate systems (you confirm) → groups domains → generates the
graph skeleton through MCP tools (all `draft`) → auto-validates.

### 2. Fill conventions and pitfalls (80% of the value)

The skeleton is just a table of contents. Spend the next 2–4 hours on each core system:

- Dictate or review commit logs and have the AI write persistence pitfalls via `kg_add_pitfall`
- Upgrade confirmed `related` edges from `draft` to `verified` with `kg_verify_edge`

This experience is the core value of the graph — governance prevents "writing it wrong", but not
"nobody writing".

### 3. Daily use

When working on a new feature, the AI auto-triggers the `kg-consult` skill:

1. `kg_query` keyword search for relevant entries
2. `kg_catalog` semantic fallback if keywords miss
3. `kg_get_entry` for details (code paths, pitfalls, outgoing/incoming edges)
4. View code directly, skipping blind greps
5. After finishing, the AI suggests `kg_verify_edge` / `kg_add_pitfall`; you just yes/no

### 4. Visualize

![Visualization preview](examples/demo_tooltip.png)

```bash
# Export a self-contained static HTML (shareable, offline)
python -X utf8 .claude/kg/tools/gen_graph_html.py

# Start a live local server (real-time data, click draft edges to verify)
python -X utf8 .claude/kg/tools/gen_graph_html.py --serve
```

### 5. Validate and upgrade

```bash
# Validate graph integrity
python -X utf8 .claude/kg/tools/validate.py

# Check for and pull the latest release (tool layer only; graph data untouched)
python .claude/kg/tools/kg_admin.py check
python .claude/kg/tools/kg_admin.py update
```

For full usage, schema, and MCP tool details see [DEVELOPMENT.md](./DEVELOPMENT.md).

## Version updates (`claude update` style)

Every installed project ships an upgrader that checks the remote for the latest version and upgrades
in place. **Only the tool layer is replaced; graph data is never touched.**

```bash
# Record this repo's address on first install (or backfill later)
python .claude/kg/tools/install.py . --repo https://github.com/kipill/KPKnowledgeGraph.git
python .claude/kg/tools/kg_admin.py config --repo https://github.com/kipill/KPKnowledgeGraph.git

# In any installed project
python .claude/kg/tools/kg_admin.py version    # local version
python .claude/kg/tools/kg_admin.py check      # is there a new version?
python .claude/kg/tools/kg_admin.py update     # pull the upgrade, data untouched
```

Upgrade safety boundary: `update` only overwrites `tools/*.py`, `skills/`, `commands/`, `templates/`,
`VERSION`; it never touches `graph*.json`, `entries/`, logs, `.mcp.json`, or `settings.json`.

### Codex users

The MCP server is a generic stdio implementation. Add to `~/.codex/config.toml`:

```toml
[mcp_servers.kg]
command = "python"
args = ["-X", "utf8", ".claude/kg/tools/kg_mcp_server.py"]
```

And state in the project's `AGENTS.md`: all graph reads/writes go through kg_* MCP tools; never edit
graph*.json directly.

## When to use / when not to

**Good fit**: 10+ core modules where grep no longer locates things well; lots of implicit conventions
not visible in code (persistence ordering, cross-server boundaries, state-machine contracts); willing
to spend ~30 min/week maintaining the graph.

**Poor fit**: < 10 modules (grep is faster); project still churning (drift outpaces maintenance);
nobody willing to maintain (governance prevents "writing it wrong", not "nobody writing").

## File map

| File / dir | Read this if you want to... |
|---|---|
| [DESIGN.md](./DESIGN.md) | Understand why it's designed this way, the decisions (ADRs), what it deliberately doesn't do |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | Actually use, extend, and maintain it — schema, MCP tools, workflows, release process |
| [templates/](../../templates) | Grab ready-made templates for your project (main index / domain file / entry MD) |
| [examples/](../../examples) | Real examples (neutralized; includes a [graph_view.html](../../examples/graph_view.html) viz demo) |
| [tools/](../../tools) | kg_core library, MCP server, hook, upgrader, validate/viz CLI |
| [skills/kg-consult.skill.md](../../skills/kg-consult.skill.md) | Claude skill definition (decides when the AI auto-checks the graph) |
| [kg-init.md](../../kg-init.md) | The `/kg-init` command (AI scans code to generate the initial skeleton) |
| [CHANGELOG.md](./CHANGELOG.md) | Version history |

## Design philosophy

- **MD for "why", JSON for "where", MCP for "how"** — a hard three-layer rule
- **Enforced spec > promised spec**: write-time validation, audit logs, and an anti-bypass hook lift the floor of graph quality from "depends on the AI's discipline" to "everything that gets in is correct"
- **Fill on demand, not up front**: add an entry when you touch that system; unfilled is the normal state
- **Code is the source of truth**: the graph is just an accelerator; when a path drifts, fix it顺手 against the real code
- **Make it "used", not "complete"**: prune with querylog data; don't chase completeness
- **The AI is a replica of the developer, not just its own memory**: encode project-specific conventions, pitfalls, and cross-module links in the graph so the AI inherits that experience instead of re-analyzing code every time
- **Active maintenance makes it smarter**: the graph won't complete itself, but every `kg_verify_edge`, every `kg_add_pitfall`, and every `kg_feedback` makes it closer to your project and your habits

See [DESIGN.md](./DESIGN.md) for details.

## Contributing

Issues and PRs welcome. When changing tool behavior, bump `VERSION` and add an entry at the top of
`CHANGELOG.md`. Dev conventions are in [DEVELOPMENT.md](./DEVELOPMENT.md) §13.

## License

[Apache License 2.0](../../LICENSE)
