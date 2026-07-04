# Development Guide

[中文](../../DEVELOPMENT.md) | **English**

Practical: how to set up, use, and maintain. For design rationale see [DESIGN.md](./DESIGN.md).

> v2 core change: graph JSON reads/writes go through kg MCP tools (single gateway), no direct file
> editing. Data schema is v1-compatible.

---

## 1. Directory layout

After install (install.sh / install.ps1 / python install.py), the target project layout:

```
<project_root>/
├── .mcp.json                            # kg MCP server registration (auto-merged by installer)
├── .claude/
│   ├── settings.json                    # PreToolUse drift-proof hook (auto-merged)
│   ├── kg/                              # knowledge-graph directory
│   │   ├── graph.json                   # main index (domain list + cross-domain relations)
│   │   ├── graph-<domain>.json          # domain files (entries live here)
│   │   ├── reverse_index.json           # reverse index (auto-rebuilt after writes; don't edit)
│   │   ├── changelog.jsonl              # change log (auto-appended; commit to git)
│   │   ├── querylog.jsonl               # query log (auto-appended; commit to git)
│   │   ├── entries/                     # MD dictionary entries (on demand, freely editable)
│   │   ├── templates/                   # template reference
│   │   └── tools/
│   │       ├── kg_core.py               # core lib: load/validate/mutate/log (the write gateway impl)
│   │       ├── kg_mcp_server.py         # MCP stdio server (pure stdlib)
│   │       ├── kg_guard_hook.py         # PreToolUse hook: block direct graph-JSON edits
│   │       ├── validate.py              # validate CLI (CI / pre-commit / human)
│   │       ├── build_reverse_index.py   # manual reverse-index rebuild (after manual direct edits)
│   │       └── gen_graph_html.py        # generate visualization HTML
│   ├── skills/kg-consult/SKILL.md       # Claude skill (decides when AI auto-checks the graph)
│   └── commands/kg-init.md              # /kg-init command
└── ...project code...
```

Graph-dir auto-detection: .claude/kg (standard) -> tools/qx_rag (source-repo layout); or via KG_DIR
env var / the --kg flag.

---

## 2. Read/write rules (read this first)

| Object | Read | Write |
|---|---|---|
| graph JSON (graph*.json) | kg_overview / kg_query / kg_get_entry | ONLY via kg_add_* / kg_update_* / kg_verify_edge |
| MD docs (entries/*.md) | direct Read | direct edit (not gated) |
| reverse_index.json / *.jsonl | direct Read | never hand-edit (auto-generated/appended) |

### kg MCP tool list

| Tool | Purpose |
|---|---|
| kg_overview | domain list + cross-domain relations |
| kg_query | keyword search (literal match) |
| kg_catalog | lightweight catalog (semantic fallback when keywords miss) |
| kg_get_entry | fetch one entry by id (with in-edges, usage stats) |
| kg_validate | full validation |
| kg_add_entry / kg_update_entry | add/update entry |
| kg_add_relation / kg_add_pitfall / kg_verify_edge | add edge / trap / draft->verified |
| kg_add_domain / kg_add_cross_relation | create domain / domain-level relation (init only) |
| kg_stats | operational stats (global summary + per-entry) |
| kg_feedback | report entry accuracy (telemetry, auto at task close) |

All write tools require a reason, written to changelog.jsonl.

### Write validation rules (when a write is rejected)

- code paths must really exist (project-relative; dirs end with /; _-prefixed keys skip validation,
  e.g. {"_TODO": "entry point not located"})
- related[].to must be an existing entry id -> create the target first, or drop the edge
- type in system/feature/concept; confidence in draft/verified
- non-whitelist keys need an x_ prefix (see section 11)
- a full validation runs before write; existing ERRORs also block (no building on a broken base)

### Escape hatch

For manual bulk fixes: set KG_ALLOW_DIRECT_EDIT=1 to bypass the hook and edit files directly; after,
you MUST run validate.py + build_reverse_index.py.

---

## 3. JSON schema

### 3.1 Two-layer structure (main index + domain files)

Main index graph.json holds only the domain list and cross-domain relations, no entry details:

```json
{
  "version": "1.0",
  "updated_at": "2026-05-10",
  "domains": {
    "social": { "file": "graph-social.json", "desc": "...", "key_entries": ["guild","mail"] }
  },
  "cross_domain_relations": [
    { "from": "social", "to": "economy", "context": "...", "confidence": "verified" }
  ]
}
```

Domain file graph-<domain>.json holds that domain's entries. Domains and cross-domain relations are
created via kg_add_domain / kg_add_cross_relation; updated_at is auto-maintained by the gateway.

### 3.2 Entry fields

```json
{
  "guild": {
    "type": "system",
    "name_cn": "Guild",
    "doc": "entries/guild.md",
    "summary": "guild create, member mgmt, shared resources",
    "code": { "manager": "src/.../GuildManager.java", "data": ["..."], "dao": ["..."] },
    "related": [ { "to": "mail", "context": "join/leave/notices go via mail", "confidence": "verified" } ],
    "persistence_pitfalls": [ "After editing Guild.storeData you must saveToDB" ],
    "tags": ["social","core"]
  }
}
```

### 3.3 Field details

type (required): system / feature / concept. Test: would a developer proactively look this up?
code (required): semantic keys (manager/data/dao/message/handler/script/config...); project-relative
paths; dirs end with /. _-prefixed keys are comments, skip path validation.
related (optional): to (existing entry), context (how they interact, <50 chars), confidence.
persistence_pitfalls (optional, the value core): "after X you must Y".
tags (optional): free-form.

### 3.4 Confidence

draft: skeleton/unverified/drift-suspected. verified: confirmed in a real task. Upgrade via
kg_verify_edge. AI behavior: verified -> trust; draft -> grep one extra step.

---

## 4. MD entry writing

(MD is not gated; edit freely. Template: templates/entry.template.md)

Structure: ## What it is / ## Core data / ## Key conventions / ## Typical scenarios / ## Pitfall
history. Don't write method signatures, full call flows, duplicating JSON. Ideal 100-200 lines;
cut over 500.

---

## 5. Workflow: initialization

### 5.1 First setup (one-time, 2-4h)

Step 1 Install (1 min): run ./install.sh /path/to/project; restart the Claude Code session.
Step 2 AI skeleton (30 min): run /kg-init. AI scans -> lists candidate systems (you confirm) ->
groups domains (you confirm) -> builds domains, entries, cross-domain relations ENTIRELY via MCP
tools (all draft). Granularity: one word a developer would say (guild, economy, combat), 10-20 total.
Step 3 Human conventions+traps (2-3h): the 80% value source. For each core entry, dictate / mine
commit log, let AI add via kg_add_pitfall (reason = source), and kg_verify_edge the edges you're
sure of. Skip this and the graph degrades to a directory listing in a month.
Step 4 Validate (1 min): kg_validate. No ERRORs expected (the gateway already blocked structural errors).

### 5.2 Incremental (30 min/week)

AI finds an entry missing -> propose kg_add_entry after the task. AI verified a draft edge ->
propose kg_verify_edge. New trap -> kg_add_pitfall. AI only proposes; you yes/no. Applied changes
auto-enter changelog.

---

## 6. Workflow: daily use

### 6.1 Standard AI flow

User: "add a guild-auction feature" -> AI triggers kg-consult -> kg_query("guild auction") gets
code/traps/edges in one shot -> reads entries/guild.md if doc_exists -> reports "involves guild,
auction, mail; note Guild.storeData must saveToDB; I'll view GuildManager.java, AuctionManager.java"
-> views code, implements -> at close: kg_feedback per entry used + propose kg_verify_edge/kg_add_pitfall.

### 6.2 When to fall back to grep (key)

MUST fall back when: (1) kg_query has no hits AND reading kg_catalog confirms no relevant entry
(semantic-fallback first, then give up); (2) entry exists but code path mismatches real code (fix
via kg_update_entry); (3) all-draft edges and can't quickly verify; (4) bug triage (stack trace
beats graph). Falling back is part of the design, not failure.

---

## 7. Workflow: update/maintenance

Triggers: feature done -> kg_add_entry/kg_add_relation; refactor -> kg_update_entry for code paths;
new trap -> kg_add_pitfall; verified draft edge -> kg_verify_edge.

Recommended: after a big change, ask the AI to review git diff and propose graph updates; you yes/no.
Applied changes are in changelog for traceability.

### 7.3 git pre-commit validation

```bash
#!/bin/sh
python .claude/kg/tools/validate.py --strict || { echo "KG validation failed"; exit 1; }
```

### 7.4 Drift tracing

```bash
grep '"entry_id": "guild"' .claude/kg/changelog.jsonl   # who/when/why wrote it
grep '"guild"' .claude/kg/querylog.jsonl                # was it ever used?
```

---

## 8. Tool reference

### 8.1 kg_mcp_server.py (MCP server)
Pure-stdlib stdio. Claude Code (.mcp.json): {"mcpServers":{"kg":{"command":"python","args":["-X","utf8",".claude/kg/tools/kg_mcp_server.py"]}}}.
Codex (~/.codex/config.toml): [mcp_servers.kg] command="python" args=["-X","utf8",".claude/kg/tools/kg_mcp_server.py"].
Reloads graph files per call; external changes (git pull) need no restart.

### 8.2 kg_guard_hook.py (drift-proof hook, Claude Code only)
PreToolUse, auto-registered to .claude/settings.json. Blocks graph*.json / reverse_index.json /
*.jsonl when the file's dir contains graph.json; entries/*.md passes; fail-open on hook error.

### 8.3 validate.py
```bash
python .claude/kg/tools/validate.py [--strict|--json]
```
ERROR: JSON parse fail / declared domain file missing / duplicate entry_id / missing required fields
/ bad enum / dangling related.to. WARNING: code path missing / orphan node / edge missing confidence.
INFO: doc MD not created (normal) / draft edge count.

### 8.4 Other
```bash
python .claude/kg/tools/build_reverse_index.py   # only after KG_ALLOW_DIRECT_EDIT manual edits
python .claude/kg/tools/gen_graph_html.py        # graph_view.html: nodes show hits/feedback/history + global summary
```

### 8.5 Graph reuse: kg_pack / kg_unpack (box/unbox)

```bash
python .claude/kg/tools/kg_pack.py               # box: outputs kg-box-<project>.json
python .claude/kg/tools/kg_unpack.py kg-box.json # unbox in a similar target project
```

Packed: domain list, cross-domain relations, all entries, MD docs full text. Not packed: logs.
Unbox is reference import: same-name entry skipped; code paths validated per-target (valid kept,
invalid moved to x_ref_code); edges/cross-domain downgraded to draft; MD docs written with a source
header; each imported entry tagged x_ref_source; changelog reason records "unboxed from X".
After unbox: move x_ref_code paths back to code via kg_update_entry once located; kg_verify_edge
drafts; run validate.

---

## 9. Granularity guide

Decision tree: would a developer proactively look this up? No -> don't create. Yes -> type: system
/ feature / concept. Don't create per-class entries (that's javadoc, not a dictionary). Split into
feature-level only when a system entry's MD exceeds ~300 lines or is frequently queried for a sub-feature.

---

## 10. FAQ

Q: kg MCP tools unavailable (server won't start)? Restart the session (.mcp.json is read at startup).
Queries can fall back to direct Read of graph JSON; writes must NOT fall back to direct edit - fix
the server first.

Q: AI's write was rejected? The message is explicit: path missing -> Glob for the real path; related
target missing -> create it first; existing ERROR blocks -> fix existing first (deliberate).

Q: kg_query has no hits? Literal miss != graph doesn't have it. Call kg_catalog, read the catalog,
pick semantically; only fall back to grep after confirming no relevant entry.

Q: AI doesn't auto-check the graph? Check skill triggers / skill file location. May be the task is
genuinely better as direct grep - not forcing graph use is by design.

Q: all confidence is draft? Normal after init. Don't organize a review; upgrade via kg_verify_edge
in natural use. Still draft and never queried after months -> delete.

Q: graph drifted from code? Three lines of defense: write-gateway rejects new drift; AI fixes paths
via kg_update_entry when it notices; pre-commit/CI validate.py reports existing drift. Trace via changelog.

---

## 11. Advanced: extending the schema

Project-specific needs can extend entry fields. Rules: new fields x_-prefixed (the gateway allows
x_ prefixes, rejects other unknowns); passed via kg_add_entry extra_fields or kg_update_entry patch;
must be optional. E.g. x_gm_commands, x_config_files. But run the standard schema 2-4 weeks first.

---

## 12. Exit strategy

Honest: when to stop. querylog flat for 3 months -> delete; AI greps instead of checking graph ->
fix the skill or graph quality first; maintenance cost > token savings -> simplify or revert to MD.
Sunk cost is not a reason.

---

## 13. Maintainer: release & distribution

### 13.1 Repo structure
The release repo root = dist contents: install.py / VERSION / CHANGELOG.md / tools/ / skills/ /
templates/ / examples/ / *.md. install.py must be at the root (kg_admin.py update looks for it after clone).

### 13.2 Release flow (after changing tool behavior)

```bash
# In the source repo, edit tools/qx_rag/tools/, verify, then:
python tools/qx_rag/tools/build_dist.py        # sync to dist/

# Bump version (semver: PATCH/MINOR/MAJOR), edit dist/VERSION + dist/CHANGELOG.md

# In the release repo: commit + tag + push
cd <release-repo>
git add -A && git commit -m "release vX.Y.Z"
git tag vX.Y.Z
git push && git push --tags
```

### 13.3 User upgrade experience
```bash
python .claude/kg/tools/kg_admin.py check      # "new version available"
python .claude/kg/tools/kg_admin.py update     # pull upgrade, data untouched
```
If --repo wasn't given at install: kg_admin.py config --repo <url> backfills it.

### 13.4 Semver
PATCH: bug fixes, no interface change. MINOR: new tools/fields, backward-compatible. MAJOR:
schema/protocol-breaking (rare; note migration in CHANGELOG).