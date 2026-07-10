# Design Document

[中文](../../DESIGN.md) | **English**

This document explains **why** this knowledge-graph system is designed the way it is, and the
reasoning behind key decisions. If you just want to use it, see [DEVELOPMENT.md](./DEVELOPMENT.md).

> v2 change: a **governance layer** is added (single MCP gateway + write-time strict validation +
> audit logs + anti-bypass hook). The data schema is v1-compatible; what changed is "how you read/write". See section 5.

---

## 1. The problem to solve

### 1.1 AI "fumbling around" an unfamiliar codebase is expensive

For a simple request like "where do I change the guild member cap?", without a graph the AI may grep
multiple times, read 3-4 files in full, infer the entry point, and possibly write code on a wrong
assumption. Token consumption can differ by 5-10x, and cross-module impact is frequently missed.

### 1.2 Traditional wikis don't solve this

Auto-generated wikis produce 50k-100k line docs: too large (5-15k tokens a file), low density
(30-40% boilerplate), high maintenance cost and drift, wrong abstraction level - "a second-hand
description of source", when the AI really needs "where to change + what not to miss".

### 1.3 The real need is navigation, not an encyclopedia

The AI needs three kinds of info: (1) concept entry - what this system is, core data, conventions;
(2) related systems - what a change touches; (3) code location - which files to view. #1 is
narrative; #2 and #3 are structured. A single format can't serve both, so layering is mandatory.

### 1.4 The v1 lesson: the graph rots on its own (v2)

v1 used "AI directly edits JSON + spec in docs + humans run validation". On a real project it broke:
record drift (AI fills paths from memory, nothing catches mistakes), validation by self-discipline
(nobody remembers to run validate.py), no traceability (can't tell which task changed what or which
entries are used). Conclusion: a spec that lives only in docs is no spec at all. The spec must
become a mechanism - the origin of the v2 governance layer.

---

## 2. Core mental model: dictionary + index + gatekeeper

A dictionary with an index and a gatekeeper. MD dictionary (narrative, for the why, freely editable)
<-> JSON index (structure, for jumping, read/written only via MCP gateway) -> MCP gateway
(write-time strict validation, changelog/querylog, anti-bypass hook).

AI workflow: kg_query for the entry -> MD for the concept (optional) -> view the code (skip greps)
-> write back experience with user consent.

---

## 3. Separation of concerns across four components

3.1 MD dictionary (narrative). Write: concept (2-3 paras), core data model, key conventions,
typical scenarios, known traps. Don't: method-call flows, full data-flow diagrams, source details,
duplicating JSON. Length 100-300 lines; over 500 means source leaked in. Not subject to the gateway.

3.2 JSON index (structure). Node metadata (type, entry file, MD mapping), related between nodes,
persistence traps, code paths. No concept explanations / why-arguments / business rules / line refs.
Boundary test: delete the MD - can the AI still figure out relationships? If not, JSON is incomplete.

3.3 MCP gateway (governance, new in v2). The single read/write channel; pure-stdlib stdio MCP
server. Query returns "enough in one shot"; write passes strict validation (code paths exist,
related targets exist, reason mandatory) and is rejected on failure, rebuilding reverse index and
appending changelog; a PreToolUse hook blocks direct edits. The writing spec is no longer a doc
paragraph - it's the tool's parameter schema and rejection logic.

3.4 HTML visualization (optional). For humans, not the AI. Read-only - edits go through MCP so
logs and validation aren't bypassed.

---

## 4. Schema design principles

4.1 Simplicity first. No edge type (nobody uses 30 types fluently; a one-sentence context suffices);
no source_line refs (lines drift; class paths are stable); only two-state confidence (draft/verified,
clean decision); no graph database (<100 relations, JSON is plenty).

4.2 Machine-verifiable -> JSON; explanatory -> MD (the one hard rule). E.g. "GuildManager calls
MailManager.sendGuildMail()" -> JSON (grep-verifiable); "the coupling should use events" -> MD (opinion).

4.3 JSON is the source of truth within the graph (MD references, doesn't duplicate). Between graph
and code, the code is always the source of truth.

4.4 Confidence is a behavior hint, not a filter (draft -> grep one extra step), not
"criticality x confidence" query logic.

---

## 5. Governance-layer design (new in v2)

5.1 Why gateway convergence. Drift chain: AI edits JSON -> no write-time validation -> errors enter
silently -> validation relies on humans -> errors consumed by next query -> no logs. The minimal
intervention point is the write: if every write validates + logs, every downstream link collapses.
Hence "single gateway", not "run validation more often".

5.2 Two validation tiers. At write time (strict): for the changed entry - code path must exist,
related targets must exist, enums legal, reason mandatory; errors reject the write. Full validation
(lenient): existing code-path drift is WARNING (refactoring drift shouldn't block new writes);
dangling refs are ERROR. Strict on writes because the AI just touched the code; lenient on existing
data because drift is natural code evolution ("whoever finds it fixes it").

5.3 Dual logs. changelog.jsonl: who/when/op/before-value/reason (mandatory - answers "which task,
based on what finding"); querylog.jsonl: keyword + hits per query (answers "is the graph used" - the
data source for section 8, which v1 could only gut-feel).

5.4 Why the hook is still necessary. MCP only "provides a better path"; the AI may still edit files
directly. The PreToolUse hook makes it a hard constraint: only blocks graph JSON (name match + dir
contains graph.json); entries/*.md passes; fail-open on hook error; escape hatch KG_ALLOW_DIRECT_EDIT=1.
Codex has no hook - MCP + AGENTS.md convention there.

---

## 6. Key decision records (ADR)

ADR-001 Why not a graph database. <200 expected relations; JSON covers it, costs fewer tokens,
git-diff friendly. Migrate past ~1000. Don't speculatively add complexity.

ADR-002 Why confidence isn't three-state. lo/md/hi: md is fuzzy, higher decision cost, no clear
trigger. draft/verified: clean; upgrade = used in a real task and confirmed (kg_verify_edge).

ADR-003 Why no edge type. calls/mutates/triggers/... were cut: the AI infers from context; every
type is extra burden; boundaries unclear; the list grows. Use x_-prefixed fields for fine tagging.

ADR-004 Why HTML viz is read-only. An editor (2-3 weeks) over-invests and bypasses governance.
Edits go through MCP; the viewer just shows structure (~1 day).

ADR-005 Why MCP, not a CLI (v2). Validation up front (schema at call time vs. CLI JSON escaping
minefield on Windows); spec visible per call; cross-tool (Claude Code + Codex); no logging blind
spots. The CLI didn't disappear - validate.py etc. remain for CI/humans; core logic in kg_core.py is shared.

ADR-006 Why strict validation at write time, not CI (v2). CI catches problems after the write
context is lost -> manual archaeology. Write-time rejection lets the AI fix on the spot - an order
of magnitude cheaper. CI is kept as a backstop.

ADR-007 Why the MCP server is pure stdlib (v2). "Install into any project in 30 seconds" means no
SDK dependency. MCP stdio is just newline-delimited JSON-RPC; ~150 lines of stdlib.

ADR-008 Why semantic matching is delegated to the calling AI (v2). kg_query is literal - rephrasing
misses. Candidates: in-server embeddings (breaks zero-dep); server-calls-LLM (non-deterministic);
return a catalog, let the calling AI judge (chosen). The caller is already an LLM - a
tens-to-hundreds-entry catalog is 1-2k tokens; reading it equals semantic search at negligible cost,
server stays deterministic. Two-stage kg_query (fast) + kg_catalog (fallback). Vector search earns
its complexity only past 500+ entries.

ADR-009 Why reuse recommendation is an "experience layer" and must be human-in-the-loop (v2.4). The
graph originally indexed only **facts** (where code is, how things link). But one class of problem the
fact layer can't solve: requesters phrase requests as a **description** ("send the user a notification
after they place an order"), and without digging in these tend to be built as new features — when an existing configurable
capability (an enum member) would do the job with a bit of configuration. This calls for the graph to
do **capability reuse recommendation**.

The key distinction: a recommendation is **experience**, not **fact**. When a fact ("the code is in
file X") is wrong, the AI reads the code and self-corrects; experience ("this kind of request can
usually use Y") is probabilistic — it may be a **false friend** (the action matches, but the request
carries one more qualifier the capability can't be configured for, e.g. "24 hours later" or "only for
first-time buyers"). If the AI treats experience as fact and executes it directly, it configures a solution
that looks right but is actually incomplete — and only blows up after release.

Hence three design points:

1. **Separate the experience layer from the fact layer**: a capability catalog carries `scenarios`
   (for matching) + `reuse_note` (the capability boundary — the dimensions it can't be configured
   for). On a hit, the AI reads `reuse_note` to judge whether the request carries an out-of-boundary
   qualifier — **the boundary itself is information** that helps the AI recognize "this one can't be
   reused," which is the core of guarding against false friends.
2. **A recommendation never turns into code directly**: `kg_scout_reuse` deliberately **does not
   return a copy-pasteable config string** — only the capability name + scenarios + boundary, forcing
   the AI to **relay the conclusion to a human with options**, and only a human decision moves it into
   implementation. The human decision is the gate that turns "experience reference" into "decision."
3. **Coarse ranking on the server, fine ranking in the AI** (continuing the ADR-008 division):
   the server keyword-coarse-ranks name/scenarios/reuse_note and returns the top-k, so the full
   catalog doesn't drown the AI; the semantic grading (recommend/reference) is left to the AI.

**Why no machine cross-check** (a "parse the source enum and compare" design was once considered):
field experiments found the AI is highly accurate when it organizes fact fields **while reading the
code** during development (errors come from "filling quickly from memory"). Adding a source parser for
a second check guards against a problem that doesn't occur in this workflow, and the parser would be
language-bound and brittle. Instead: "the AI reads the source and fills + the human confirms + a
`source` provenance hint for cross-checking," relying on point 2 (a recommendation is a reference, not
an execution) to backstop the occasional slip in the fact fields.

**Feedback loop**: after a human decides, the outcome (reuse/new/misunderstood) is written back to
`reuse_feedback.jsonl` and aggregated into an adoption rate with grades. The experience layer is
therefore **data-driven** — it can surface "always recommended but never used" (scenarios too broad)
and bad recommendations, and iterate on them, rather than being frozen after one write.

---

## 7. What this system deliberately doesn't do

Not a project encyclopedia; not a source substitute; not real-time sync (write-gateway + full
validation backstop); not a strict type system; not fully AI-maintained (AI proposes, human yes/no);
not a grep replacement (fall back immediately).

---

## 8. Failure-mode warnings

8.1 Lazy initialization. "AI scans a draft, tweak slowly" -> a month later still a draft.
Countermeasure: two-stage init - AI scans structural skeleton (30 min, /kg-init); human dictates
conventions/traps (2-4h, mandatory). Governance prevents "writing wrong", not "nobody writing".

8.2 Update-trigger gap. Small change -> can't be bothered; big -> burdensome; urgent -> fix first.
Countermeasure (v2 builds in most): skill post-task AI proposes, you yes/no; write auto-validates +
changelog; pre-commit validate.py --strict.

8.3 The graph becomes dead doc. If unused after a week, it shares the wiki's fate. Countermeasure:
clear skill triggers; after 1-2 weeks check querylog.jsonl - never-queried -> delete.

---

## 9. Summary: what this system bets on

We bet: a refined navigation dataset beats a huge descriptive doc; a mechanism-enforced spec lifts
the floor from "depends on AI discipline" to "everything that gets in is correct"; AI checking the
graph first is the key to 50%+ token savings. We don't bet: the AI fully self-maintains; the graph
covers everything; one design pass works (v1->v2 was iterated on real data).

Core success criterion: three months in, querylog.jsonl still growing, changelog.jsonl reasons still
meaningful, and graph-using tasks cost fewer tokens than a non-using control group. If it doesn't
hit that bar in three months, shut it down - don't add complexity to rescue it.