#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_core — 知识图谱核心库（纯标准库，无第三方依赖）

统一承载：加载、schema 校验、变更操作（唯一写入口）、changelog/querylog、
反向索引重建。上层封装：
  - kg_mcp_server.py  MCP stdio server（AI 用）
  - validate.py       校验 CLI（CI / pre-commit / 人工用）

图谱目录自动探测顺序：
  1. 显式传入 kg_dir
  2. 环境变量 KG_DIR
  3. <root>/.claude/kg     （标准安装布局）
  4. <root>/tools/qx_rag   （源仓库布局，兼容上游开发）
"""

import getpass
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

MAIN_GRAPH_FILE = "graph.json"
REVERSE_INDEX_FILE = "reverse_index.json"
CHANGELOG_FILE = "changelog.jsonl"
QUERYLOG_FILE = "querylog.jsonl"
REUSE_FEEDBACK_FILE = "reuse_feedback.jsonl"
ENTRIES_DIR = "entries"

VALID_TYPES = {"system", "feature", "concept"}
VALID_CONFIDENCE = {"draft", "verified"}
# 复用推荐反馈的三种决策（D9）
VALID_REUSE_DECISIONS = {"reuse", "new", "misunderstood"}
# 能力目录以 entry 的扩展字段承载（x_ 前缀，写入时放行）
CAPABILITY_MEMBERS_FIELD = "x_capability_members"
CAPABILITY_SOURCE_FIELD = "x_capability_source"
# 统计分级阈值（D9）
REUSE_TIER_MIN_SAMPLES = 3       # 推荐次数 < 此值 = 待验证
REUSE_TIER_TRUSTED_SAMPLES = 10  # 推荐次数 ≥ 此值且采纳率 > 阈值 = 高置信
REUSE_TIER_TRUSTED_RATE = 0.7
ENTRY_REQUIRED_FIELDS = {"type", "name_cn", "doc", "summary", "code"}
# x_ 前缀为项目自定义扩展字段，写入时放行
ENTRY_ALLOWED_FIELDS = ENTRY_REQUIRED_FIELDS | {"related", "persistence_pitfalls", "tags"}


def _unknown_fields(keys):
    return {k for k in keys if k not in ENTRY_ALLOWED_FIELDS and not k.startswith("x_")}

KG_DIR_CANDIDATES = [Path(".claude/kg"), Path("tools/qx_rag")]


class KGError(Exception):
    """业务性错误（参数非法、校验失败），message 直接展示给调用方。"""


def resolve_kg_dir(root: Path, kg_dir=None) -> Path:
    root = Path(root).resolve()
    if kg_dir:
        p = (root / kg_dir).resolve() if not Path(kg_dir).is_absolute() else Path(kg_dir)
        if not p.exists():
            raise KGError("图谱目录不存在: %s" % p)
        return p
    env = os.environ.get("KG_DIR")
    if env:
        p = Path(env)
        p = p if p.is_absolute() else (root / p).resolve()
        if not p.exists():
            raise KGError("KG_DIR 指向的目录不存在: %s" % p)
        return p
    for cand in KG_DIR_CANDIDATES:
        p = root / cand
        if (p / MAIN_GRAPH_FILE).exists():
            return p.resolve()
    raise KGError("未找到图谱目录（尝试了 %s），可用 KG_DIR 环境变量指定"
                  % ", ".join(str(c) for c in KG_DIR_CANDIDATES))


class ValidationResult:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
        self.stats = {}

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def add_info(self, msg):
        self.info.append(msg)

    @property
    def ok(self):
        return len(self.errors) == 0

    def to_json(self):
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "stats": self.stats,
        }


class KG:
    def __init__(self, root, kg_dir=None):
        self.root = Path(root).resolve()
        self.kg_dir = resolve_kg_dir(self.root, kg_dir)
        self.main = None          # graph.json 内容
        self.domains = {}         # {domain_name: {"path": Path, "data": dict}}
        self.entries = {}         # {entry_id: (entry_dict, domain_name)}
        self.load_errors = []
        self._load()

    # ==================== 加载 ====================

    def _load(self):
        main_path = self.kg_dir / MAIN_GRAPH_FILE
        self.main = self._read_json(main_path)
        for domain_path in sorted(self.kg_dir.glob("graph-*.json")):
            name = domain_path.stem.replace("graph-", "")
            try:
                data = self._read_json(domain_path)
            except KGError as e:
                self.load_errors.append(str(e))
                continue
            self.domains[name] = {"path": domain_path, "data": data}
            for entry_id, entry in data.get("entries", {}).items():
                if entry_id in self.entries:
                    self.load_errors.append(
                        "entry_id '%s' 重复：同时出现在 graph-%s.json 和 %s"
                        % (entry_id, self.entries[entry_id][1], domain_path.name))
                    continue
                self.entries[entry_id] = (entry, name)

    @staticmethod
    def _read_json(path: Path):
        if not path.exists():
            raise KGError("文件不存在: %s" % path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise KGError("JSON 解析失败 %s: %s" % (path, e))

    # ==================== 校验 ====================

    def validate(self) -> ValidationResult:
        r = ValidationResult()
        for msg in self.load_errors:
            r.error(msg)

        if not isinstance(self.main, dict) or "domains" not in self.main:
            r.warn("graph.json 缺少 'domains' 字段")
        else:
            for domain_id, info in self.main["domains"].items():
                f = info.get("file")
                if not f:
                    r.error("domains.%s 缺少 'file' 字段" % domain_id)
                elif not (self.kg_dir / f).exists():
                    r.error("domains.%s 声明的文件不存在: %s" % (domain_id, f))

        if not self.domains:
            r.warn("未找到任何 graph-*.json 文件")

        real = {k: v for k, v in self.entries.items() if not k.startswith("_")}
        for entry_id, (entry, domain) in real.items():
            self._check_entry_structure(entry_id, entry, "graph-%s.json" % domain, r)

        valid_ids = set(self.entries.keys())
        referenced = set()
        for entry_id, (entry, domain) in real.items():
            doc_rel = entry.get("doc")
            if doc_rel and not (self.kg_dir / doc_rel).exists():
                r.add_info("[%s] doc 文件尚未创建（按需填充）: %s"
                           % (entry_id, Path(doc_rel).name))
            for bad in self._missing_code_paths(entry):
                r.warn("[%s].code 路径不存在: %s (可能路径有误或类尚未创建)"
                       % (entry_id, bad))
            for rel in entry.get("related", []) or []:
                if not isinstance(rel, dict):
                    continue
                target = rel.get("to")
                referenced.add(target)
                if target and target not in valid_ids:
                    r.error("[%s].related 指向不存在的 entry: '%s'" % (entry_id, target))

        for entry_id, (entry, domain) in real.items():
            if not entry.get("related") and entry_id not in referenced:
                r.warn("[%s] 孤儿节点：无出边，也未被引用（可能是新建未连接）" % entry_id)

        for entry_id, (entry, domain) in real.items():
            self._check_capability_members(entry_id, entry, r)

        self._gather_stats(real, r)
        return r

    @staticmethod
    def _check_capability_members(entry_id, entry, r: ValidationResult):
        """能力目录结构校验（§7，只做结构，不做源码交叉校验）。"""
        members = entry.get(CAPABILITY_MEMBERS_FIELD)
        if members is None:
            return
        if not isinstance(members, list) or not members:
            r.error("[%s].%s 必须是非空数组" % (entry_id, CAPABILITY_MEMBERS_FIELD))
            return
        seen = set()
        for i, m in enumerate(members):
            if not isinstance(m, dict):
                r.error("[%s].%s[%d] 必须是对象" % (entry_id, CAPABILITY_MEMBERS_FIELD, i))
                continue
            ev = m.get("enum_value")
            if not ev:
                r.error("[%s].%s[%d] 缺少 enum_value" % (entry_id, CAPABILITY_MEMBERS_FIELD, i))
                continue
            if ev in seen:
                r.error("[%s] 能力成员 enum_value 重复: '%s'" % (entry_id, ev))
            seen.add(ev)
            st = m.get("status", "active")
            if st not in ("active", "deprecated"):
                r.error("[%s].%s 的 status 非法: %s" % (entry_id, ev, st))
            if not (m.get("scenarios") or []):
                r.add_info("[%s].%s 无 scenarios（不参与复用推荐匹配，建议补语义标签）"
                           % (entry_id, ev))

    @staticmethod
    def _check_entry_structure(entry_id, entry, source, r: ValidationResult):
        if not isinstance(entry, dict):
            r.error("[%s](%s) entry 必须是对象" % (entry_id, source))
            return
        missing = ENTRY_REQUIRED_FIELDS - set(entry.keys())
        if missing:
            r.error("[%s](%s) 缺少必填字段: %s" % (entry_id, source, sorted(missing)))
            return
        if entry["type"] not in VALID_TYPES:
            r.error("[%s] type 非法: %s (合法: %s)"
                    % (entry_id, entry["type"], sorted(VALID_TYPES)))
        if not isinstance(entry.get("code"), dict):
            r.error("[%s] code 必须是对象" % entry_id)
        if "related" in entry:
            if not isinstance(entry["related"], list):
                r.error("[%s] related 必须是数组" % entry_id)
            else:
                for i, rel in enumerate(entry["related"]):
                    if not isinstance(rel, dict):
                        r.error("[%s].related[%d] 必须是对象" % (entry_id, i))
                        continue
                    if "to" not in rel or "context" not in rel:
                        r.error("[%s].related[%d] 缺少 to 或 context" % (entry_id, i))
                    if "confidence" in rel and rel["confidence"] not in VALID_CONFIDENCE:
                        r.error("[%s].related[%d].confidence 非法: %s (合法: %s)"
                                % (entry_id, i, rel["confidence"], sorted(VALID_CONFIDENCE)))

    def _missing_code_paths(self, entry):
        bad = []
        for key, value in (entry.get("code") or {}).items():
            if key.startswith("_"):
                continue
            paths = [value] if isinstance(value, str) else (value if isinstance(value, list) else [])
            for p in paths:
                if not isinstance(p, str):
                    continue
                if not (self.root / p.rstrip("/")).exists():
                    bad.append("%s: %s" % (key, p))
        return bad

    def _gather_stats(self, real, r: ValidationResult):
        by_type, by_domain = {}, {}
        conf = {"draft": 0, "verified": 0, "missing": 0}
        edge_count = 0
        for entry_id, (entry, domain) in real.items():
            by_type[entry.get("type", "unknown")] = by_type.get(entry.get("type", "unknown"), 0) + 1
            by_domain[domain] = by_domain.get(domain, 0) + 1
            for rel in entry.get("related", []) or []:
                if not isinstance(rel, dict):
                    continue
                edge_count += 1
                c = rel.get("confidence")
                conf[c if c in VALID_CONFIDENCE else "missing"] += 1
        r.stats = {
            "total_entries": len(real),
            "by_domain": by_domain,
            "by_type": by_type,
            "total_edges": edge_count,
            "confidence_distribution": conf,
        }
        if conf["draft"]:
            r.add_info("还有 %d 条 draft 边（在使用中渐进升级即可）" % conf["draft"])
        if conf["missing"]:
            r.warn("%d 条边没有 confidence 字段，建议补全" % conf["missing"])

    # ==================== 查询 ====================

    def query(self, q, domain=None, limit=8, log=True):
        tokens = [t for t in q.lower().split() if t]
        scored = []
        for entry_id, (entry, dom) in self.entries.items():
            if entry_id.startswith("_"):
                continue
            if domain and dom != domain:
                continue
            score = self._score(entry_id, entry, q.lower(), tokens)
            if score > 0:
                scored.append((score, entry_id, entry, dom))
        scored.sort(key=lambda x: (-x[0], x[1]))
        hits = [self._entry_view(eid, e, d) for _, eid, e, d in scored[:limit]]
        if log:
            self._append_log(QUERYLOG_FILE, {
                "query": q, "domain": domain,
                "hits": [h["entry_id"] for h in hits],
            })
        return hits

    @staticmethod
    def _score(entry_id, entry, q, tokens):
        hay = {
            "id": entry_id.lower(),
            "name": str(entry.get("name_cn", "")).lower(),
            "tags": " ".join(entry.get("tags", []) or []).lower(),
            "summary": str(entry.get("summary", "")).lower(),
            "code": json.dumps(entry.get("code", {}), ensure_ascii=False).lower(),
            "related": " ".join(str(r.get("context", "")) for r in entry.get("related", []) or []
                                if isinstance(r, dict)).lower(),
        }
        weights = {"id": 5, "name": 4, "tags": 3, "summary": 2, "code": 1, "related": 1}
        score = 0
        for field, text in hay.items():
            if not text:
                continue
            if q and q in text:
                score += weights[field] * 2
            for t in tokens:
                if t in text:
                    score += weights[field]
        return score

    def _entry_view(self, entry_id, entry, domain):
        view = {"entry_id": entry_id, "domain": domain}
        view.update(entry)
        view["incoming"] = self._incoming(entry_id)
        doc = entry.get("doc")
        view["doc_exists"] = bool(doc) and (self.kg_dir / doc).exists()
        return view

    def catalog(self, domain=None, log=True):
        """轻量目录：全部（或某域）entry 的 id/中文名/摘要/标签。
        关键词匹配失灵时返回给调用方 AI 做语义挑选，替代 server 内做语义检索。"""
        if domain and domain not in self.domains:
            raise KGError("域不存在: '%s'（现有: %s）" % (domain, sorted(self.domains)))
        items = []
        for entry_id, (entry, dom) in sorted(self.entries.items(),
                                             key=lambda kv: (kv[1][1], kv[0])):
            if entry_id.startswith("_"):
                continue
            if domain and dom != domain:
                continue
            items.append({"entry_id": entry_id, "domain": dom,
                          "name_cn": entry.get("name_cn", ""),
                          "summary": entry.get("summary", ""),
                          "tags": entry.get("tags", []) or []})
        if log:
            self._append_log(QUERYLOG_FILE, {"catalog": domain or "all"})
        return items

    def get_entry(self, entry_id, log=False):
        if entry_id not in self.entries:
            raise KGError("entry 不存在: '%s'（可用 kg_query/kg_catalog 先查找）" % entry_id)
        entry, domain = self.entries[entry_id]
        view = self._entry_view(entry_id, entry, domain)
        if log:  # AI 从 catalog 语义挑选后精确取，也算一次命中
            self._append_log(QUERYLOG_FILE, {"get": entry_id})
        s = self.stats()["per_entry"].get(entry_id, {})
        view["stats"] = {
            "query_hits": s.get("query_hits", 0),
            "feedback_accurate": s.get("accurate", 0),
            "feedback_inaccurate": s.get("inaccurate", 0),
            "change_count": s.get("change_count", 0),
            "recent_changes": s.get("changes", [])[:3],
        }
        return view

    def _incoming(self, entry_id):
        result = []
        for src_id, (src, src_domain) in self.entries.items():
            if src_id.startswith("_"):
                continue
            for rel in src.get("related", []) or []:
                if isinstance(rel, dict) and rel.get("to") == entry_id:
                    result.append({
                        "from": src_id, "from_domain": src_domain,
                        "context": rel.get("context", ""),
                        "confidence": rel.get("confidence", "draft"),
                    })
        return result

    def overview(self):
        """主索引视图：域清单 + 跨域关联（替代直接 Read graph.json）。"""
        return {
            "domains": (self.main or {}).get("domains", {}),
            "cross_domain_relations": (self.main or {}).get("cross_domain_relations", []),
        }

    # ==================== 统计与反馈 ====================

    def _read_log(self, filename):
        path = self.kg_dir / filename
        if not path.exists():
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def feedback(self, entry_id, accurate, note=""):
        """AI 用完某 entry 的图谱信息后回报准确性（进 querylog，用于评估图谱质量）。"""
        if entry_id not in self.entries:
            raise KGError("entry 不存在: '%s'" % entry_id)
        record = {"feedback": {"entry_id": entry_id, "accurate": bool(accurate),
                               "note": str(note or "").strip()}}
        self._append_log(QUERYLOG_FILE, record)
        return {"entry_id": entry_id, "accurate": bool(accurate)}

    def report_reuse_outcome(self, requirement, catalog_id, member, decision, note=""):
        """推荐后人拍板的结果回写（D9）。记录到 reuse_feedback.jsonl，用于统计与迭代。
        decision ∈ reuse|new|misunderstood。"""
        if not requirement or not str(requirement).strip():
            raise KGError("requirement 不能为空：记录这次推荐针对的需求")
        if catalog_id not in self.entries:
            raise KGError("catalog 不存在: '%s'" % catalog_id)
        if decision not in VALID_REUSE_DECISIONS:
            raise KGError("decision 非法: %s（合法: %s）"
                          % (decision, sorted(VALID_REUSE_DECISIONS)))
        if not member or not str(member).strip():
            raise KGError("member 不能为空：填被推荐的 enum_value")
        record = {"reuse_feedback": {
            "requirement": str(requirement).strip(),
            "catalog_id": catalog_id,
            "member": str(member).strip(),
            "decision": decision,
            "note": str(note or "").strip(),
        }}
        self._append_log(REUSE_FEEDBACK_FILE, record)
        return {"catalog_id": catalog_id, "member": str(member).strip(), "decision": decision}

    def stats(self):
        """运营统计：全局汇总 + 每个 entry 的命中/准确反馈/变更历史（来自双日志）。"""
        per = {}
        for eid in self.entries:
            if not eid.startswith("_"):
                per[eid] = {"query_hits": 0, "accurate": 0, "inaccurate": 0,
                            "change_count": 0, "changes": []}
        total_queries = 0
        for rec in self._read_log(QUERYLOG_FILE):
            if "query" in rec or "catalog" in rec:
                total_queries += 1
                for hid in rec.get("hits") or []:
                    if hid in per:
                        per[hid]["query_hits"] += 1
            gid = rec.get("get")
            if gid in per:
                per[gid]["query_hits"] += 1
            fb = rec.get("feedback")
            if isinstance(fb, dict) and fb.get("entry_id") in per:
                key = "accurate" if fb.get("accurate") else "inaccurate"
                per[fb["entry_id"]][key] += 1
        total_changes = 0
        for rec in self._read_log(CHANGELOG_FILE):
            eid = rec.get("entry_id")
            if not eid and rec.get("op") in ("add_relation", "verify_edge"):
                eid = rec.get("from")
            if eid in per:
                per[eid]["change_count"] += 1
                total_changes += 1
                per[eid]["changes"].append({"ts": rec.get("ts", ""),
                                            "op": rec.get("op", ""),
                                            "reason": rec.get("reason", "")})
        for v in per.values():
            v["changes"] = v["changes"][-5:][::-1]  # 最近 5 条，新的在前

        total_entries = len(per)
        total_hits = sum(v["query_hits"] for v in per.values())
        total_acc = sum(v["accurate"] for v in per.values())
        total_bad = sum(v["inaccurate"] for v in per.values())
        fb_count = total_acc + total_bad
        queried = sum(1 for v in per.values() if v["query_hits"] > 0)
        no_hits = sum(1 for v in per.values() if v["query_hits"] == 0)
        accuracy = round(total_acc / fb_count, 2) if fb_count else None
        summary = {
            "total_entries": total_entries,
            "total_queries": total_queries,
            "total_hits": total_hits,          # 所有 entry 命中次数之和（一次 query 可命中多个）
            "total_feedback": fb_count,
            "feedback_accurate": total_acc,
            "feedback_inaccurate": total_bad,
            "accuracy": accuracy,              # None 表示还没有反馈
            "queried_entries": queried,        # 至少被命中过一次的 entry 数
            "never_queried_entries": no_hits,  # 从没被查过的 entry（删/合并候选）
            "total_changes": total_changes,
        }
        return {"summary": summary, "total_queries": total_queries, "per_entry": per}

    # ==================== 变更操作（唯一写入口） ====================

    def add_entry(self, domain, entry_id, entry, reason):
        self._require_reason(reason)
        if domain not in self.domains:
            raise KGError("域不存在: '%s'（现有: %s）" % (domain, sorted(self.domains)))
        if entry_id in self.entries:
            raise KGError("entry_id 已存在: '%s'（在 %s 域），如需修改用 kg_update_entry"
                          % (entry_id, self.entries[entry_id][1]))
        entry = dict(entry)
        entry.setdefault("doc", "%s/%s.md" % (ENTRIES_DIR, entry_id))
        entry.setdefault("persistence_pitfalls", [])
        entry.setdefault("tags", [domain])
        unknown = _unknown_fields(entry.keys())
        if unknown:
            raise KGError("含未定义字段: %s（合法: %s，项目自定义字段用 x_ 前缀）"
                          % (sorted(unknown), sorted(ENTRY_ALLOWED_FIELDS)))
        self._check_new_entry_strict(entry_id, entry)
        self.domains[domain]["data"].setdefault("entries", {})[entry_id] = entry
        self.entries[entry_id] = (entry, domain)
        self._commit(domain, "add_entry", {"entry_id": entry_id}, reason)
        return self.get_entry(entry_id)

    def update_entry(self, entry_id, patch, reason):
        self._require_reason(reason)
        entry, domain = self._get_mut(entry_id)
        if not isinstance(patch, dict) or not patch:
            raise KGError("patch 必须是非空对象")
        unknown = _unknown_fields(patch.keys())
        if unknown:
            raise KGError("patch 含未定义字段: %s（合法: %s，项目自定义字段用 x_ 前缀）"
                          % (sorted(unknown), sorted(ENTRY_ALLOWED_FIELDS)))
        old = {k: entry.get(k) for k in patch}
        entry.update(patch)
        self._check_new_entry_strict(entry_id, entry)
        self._commit(domain, "update_entry",
                     {"entry_id": entry_id, "fields": sorted(patch), "before": old}, reason)
        return self.get_entry(entry_id)

    def add_relation(self, from_id, to_id, context, confidence, reason):
        self._require_reason(reason)
        entry, domain = self._get_mut(from_id)
        if to_id not in self.entries:
            raise KGError("目标 entry 不存在: '%s'" % to_id)
        if confidence not in VALID_CONFIDENCE:
            raise KGError("confidence 非法: %s (合法: %s)" % (confidence, sorted(VALID_CONFIDENCE)))
        if not context or not str(context).strip():
            raise KGError("context 不能为空：写清楚两个系统之间具体怎么联动")
        rels = entry.setdefault("related", [])
        for rel in rels:
            if isinstance(rel, dict) and rel.get("to") == to_id:
                raise KGError("关联已存在 %s → %s，升级 confidence 用 kg_verify_edge，"
                              "改描述用 kg_update_entry" % (from_id, to_id))
        rels.append({"to": to_id, "context": str(context).strip(), "confidence": confidence})
        self._commit(domain, "add_relation",
                     {"from": from_id, "to": to_id, "confidence": confidence}, reason)
        return self.get_entry(from_id)

    def add_pitfall(self, entry_id, pitfall, reason):
        self._require_reason(reason)
        entry, domain = self._get_mut(entry_id)
        text = str(pitfall).strip()
        if not text:
            raise KGError("pitfall 内容不能为空")
        pits = entry.setdefault("persistence_pitfalls", [])
        if text in pits:
            raise KGError("该 pitfall 已存在，无需重复添加")
        pits.append(text)
        self._commit(domain, "add_pitfall", {"entry_id": entry_id, "pitfall": text}, reason)
        return self.get_entry(entry_id)

    def add_domain(self, domain, desc, reason, key_entries=None):
        """新建一个域（graph-<domain>.json + 注册到 graph.json）。/kg-init 初始化用。"""
        self._require_reason(reason)
        if not re.match(r"^[a-z][a-z0-9_]*$", domain or ""):
            raise KGError("域名非法: '%s'（小写英文/数字/下划线，字母开头）" % domain)
        if domain in self.domains or domain in (self.main or {}).get("domains", {}):
            raise KGError("域已存在: '%s'" % domain)
        if not desc or not str(desc).strip():
            raise KGError("desc 不能为空：一句话说明这个域涵盖什么")
        filename = "graph-%s.json" % domain
        path = self.kg_dir / filename
        if path.exists():
            raise KGError("文件已存在但未注册: %s（请人工检查）" % filename)
        today = datetime.now().strftime("%Y-%m-%d")
        data = {"version": "1.0", "domain": domain, "updated_at": today, "entries": {}}
        if not isinstance(self.main, dict):
            self.main = {}
        self.main.setdefault("domains", {})[domain] = {
            "file": filename, "desc": str(desc).strip(),
            "key_entries": list(key_entries or []),
        }
        self.main["updated_at"] = today
        self._atomic_write(path, data)
        self._atomic_write(self.kg_dir / MAIN_GRAPH_FILE, self.main)
        self.domains[domain] = {"path": path, "data": data}
        self._append_log(CHANGELOG_FILE, {"op": "add_domain", "domain": domain,
                                          "desc": str(desc).strip(),
                                          "reason": str(reason).strip()})
        return {"domain": domain, "file": filename, "desc": str(desc).strip()}

    def add_cross_relation(self, from_domain, to_domain, context, confidence, reason):
        """加一条域级跨域关联（graph.json 的 cross_domain_relations）。"""
        self._require_reason(reason)
        known = set((self.main or {}).get("domains", {})) | set(self.domains)
        for d in (from_domain, to_domain):
            if d not in known:
                raise KGError("域不存在: '%s'（现有: %s）" % (d, sorted(known)))
        if confidence not in VALID_CONFIDENCE:
            raise KGError("confidence 非法: %s (合法: %s)" % (confidence, sorted(VALID_CONFIDENCE)))
        if not context or not str(context).strip():
            raise KGError("context 不能为空：写清楚两个域之间具体怎么联动")
        rels = self.main.setdefault("cross_domain_relations", [])
        for rel in rels:
            if rel.get("from") == from_domain and rel.get("to") == to_domain:
                raise KGError("跨域关联已存在: %s → %s（context: %s）"
                              % (from_domain, to_domain, rel.get("context", "")))
        rels.append({"from": from_domain, "to": to_domain,
                     "context": str(context).strip(), "confidence": confidence})
        self.main["updated_at"] = datetime.now().strftime("%Y-%m-%d")
        self._atomic_write(self.kg_dir / MAIN_GRAPH_FILE, self.main)
        self._append_log(CHANGELOG_FILE, {"op": "add_cross_relation",
                                          "from": from_domain, "to": to_domain,
                                          "confidence": confidence,
                                          "reason": str(reason).strip()})
        return {"from": from_domain, "to": to_domain, "context": str(context).strip(),
                "confidence": confidence}

    def verify_edge(self, from_id, to_id, reason):
        self._require_reason(reason)
        entry, domain = self._get_mut(from_id)
        for rel in entry.get("related", []) or []:
            if isinstance(rel, dict) and rel.get("to") == to_id:
                if rel.get("confidence") == "verified":
                    raise KGError("该边已是 verified: %s → %s" % (from_id, to_id))
                rel["confidence"] = "verified"
                self._commit(domain, "verify_edge", {"from": from_id, "to": to_id}, reason)
                return self.get_entry(from_id)
        raise KGError("边不存在: %s → %s（新建用 kg_add_relation）" % (from_id, to_id))

    # ==================== 能力目录（经验层，D1-D9） ====================

    def add_capability_catalog(self, domain, catalog_id, name_cn, members, reason,
                               source=None, summary=None):
        """录入一个能力目录（LLM 分析源码整理 + 人工确认后调用，D1/D6）。
        承载为 type=concept 的 entry + x_capability_members 扩展字段。
        members: [{enum_value, id?, name?, scenarios[], reuse_note?, status?}]。
        source: {file, symbol} 溯源线索（可选，不做机器交叉校验，D2）。"""
        self._require_reason(reason)
        if domain not in self.domains:
            raise KGError("域不存在: '%s'（现有: %s）" % (domain, sorted(self.domains)))
        if catalog_id in self.entries:
            raise KGError("catalog_id 已存在: '%s'（在 %s 域）" % (catalog_id, self.entries[catalog_id][1]))
        norm = self._normalize_members(members)
        entry = {
            "type": "concept",
            "name_cn": name_cn,
            "doc": "%s/%s.md" % (ENTRIES_DIR, catalog_id),
            "summary": summary or ("能力目录：%s（可复用行为的枚举成员，供复用推荐）" % name_cn),
            "code": {},
            "related": [],
            "persistence_pitfalls": [],
            "tags": [domain, "capability_catalog"],
            CAPABILITY_MEMBERS_FIELD: norm,
        }
        if source:
            if not isinstance(source, dict) or not source.get("file"):
                raise KGError("source 需为 {file, symbol} 形式")
            entry[CAPABILITY_SOURCE_FIELD] = {"file": str(source.get("file")),
                                              "symbol": str(source.get("symbol", ""))}
        self.domains[domain]["data"].setdefault("entries", {})[catalog_id] = entry
        self.entries[catalog_id] = (entry, domain)
        self._commit(domain, "add_capability_catalog",
                     {"entry_id": catalog_id, "member_count": len(norm)}, reason)
        return self.get_entry(catalog_id)

    @staticmethod
    def _normalize_members(members):
        """校验并规整 members：至少含 enum_value；scenarios 转 list；status 默认 active。"""
        if not isinstance(members, list) or not members:
            raise KGError("members 必须是非空数组")
        out = []
        seen = set()
        for i, m in enumerate(members):
            if not isinstance(m, dict):
                raise KGError("members[%d] 必须是对象" % i)
            ev = m.get("enum_value")
            if not ev or not str(ev).strip():
                raise KGError("members[%d] 缺少 enum_value" % i)
            ev = str(ev).strip()
            if ev in seen:
                raise KGError("members 里 enum_value 重复: '%s'" % ev)
            seen.add(ev)
            scen = m.get("scenarios") or []
            if not isinstance(scen, list):
                raise KGError("members[%s].scenarios 必须是数组" % ev)
            status = m.get("status", "active")
            if status not in ("active", "deprecated"):
                raise KGError("members[%s].status 非法: %s（active|deprecated）" % (ev, status))
            out.append({
                "enum_value": ev,
                "id": m.get("id"),
                "name": str(m.get("name", "")).strip(),
                "scenarios": [str(s).strip() for s in scen if str(s).strip()],
                "reuse_note": str(m.get("reuse_note", "")).strip(),
                "status": status,
            })
        return out

    def _iter_catalog_members(self, domain=None):
        """遍历所有能力目录的 active 成员。yield (catalog_id, catalog_entry, dom, member)。"""
        for cid, (entry, dom) in self.entries.items():
            if cid.startswith("_"):
                continue
            if domain and dom != domain:
                continue
            members = entry.get(CAPABILITY_MEMBERS_FIELD)
            if not isinstance(members, list):
                continue
            for m in members:
                if isinstance(m, dict) and m.get("status", "active") != "deprecated":
                    yield cid, entry, dom, m

    def scout_reuse(self, requirement, domain=None, limit=5, log=True):
        """复用推荐粗排（D4）：对 requirement 在各能力目录成员的 name/scenarios/reuse_note
        上做关键词匹配，返回 top-k 相关成员（扁平列表，每个带所属 catalog 元信息）。
        只做粗排，精排（recommend/reference 分级）交给 LLM。已自动过滤 deprecated。"""
        if not requirement or not str(requirement).strip():
            raise KGError("requirement 不能为空：填需求描述")
        if domain and domain not in self.domains:
            raise KGError("域不存在: '%s'（现有: %s）" % (domain, sorted(self.domains)))
        req = str(requirement).strip()
        tokens = self._tokenize(req)
        scored = []
        for cid, entry, dom, m in self._iter_catalog_members(domain):
            score, reason = self._match_member(req, tokens, m)
            if score > 0:
                scored.append((score, reason, cid, entry, dom, m))
        scored.sort(key=lambda x: (-x[0], x[2], x[5].get("enum_value", "")))
        candidates = []
        for score, reason, cid, entry, dom, m in scored[:limit]:
            candidates.append({
                "catalog_id": cid,
                "catalog_name": entry.get("name_cn", ""),
                "domain": dom,
                "member": {"enum_value": m.get("enum_value"), "id": m.get("id"),
                           "name": m.get("name", ""), "scenarios": m.get("scenarios", []),
                           "reuse_note": m.get("reuse_note", "")},
                "match_reason": reason,
            })
        if log:
            self._append_log(QUERYLOG_FILE, {"scout_reuse": req, "domain": domain,
                                             "hits": [c["member"]["enum_value"] for c in candidates]})
        return {"candidates": candidates, "total_matched": len(candidates),
                "hint": "以上为粗排候选。LLM 精排：读 reuse_note，判断需求是否含超出该能力语义的"
                        "限定词（方向/时序/计数/条件）；有则降级为 reference 并提示该维度需新增，"
                        "无则 recommend。转述给用户 + 给选项，等人拍板；勿直接照配（D8）。"}

    @staticmethod
    def _tokenize(text):
        """粗粒度分词：抽连续的 CJK/字母/数字片段。CJK 逐字也加入，提高中文召回。"""
        toks = set()
        for seg in re.findall(r"[\w一-鿿]+", text.lower()):
            toks.add(seg)
            for ch in seg:
                if "一" <= ch <= "鿿":
                    toks.add(ch)
        return toks

    def _match_member(self, req, tokens, m):
        """给单个成员打分：scenarios 命中权重最高，name 次之，reuse_note 兜底。
        返回 (score, match_reason)。"""
        scen = m.get("scenarios", []) or []
        name = str(m.get("name", ""))
        note = str(m.get("reuse_note", ""))
        hit_scen = [s for s in scen if s and (s.lower() in req.lower()
                                              or any(t in s.lower() for t in tokens))]
        score = 0
        score += 3 * len(hit_scen)
        if name and (name.lower() in req.lower() or any(t in name.lower() for t in tokens)):
            score += 2
        note_hits = [t for t in tokens if len(t) > 1 and t in note.lower()]
        score += min(len(note_hits), 2)
        reason_parts = []
        if hit_scen:
            reason_parts.append("scenarios 命中 %s" % "/".join(hit_scen[:3]))
        if name and name.lower() in req.lower():
            reason_parts.append("name 命中'%s'" % name)
        return score, "；".join(reason_parts) if reason_parts else "弱相关"

    def get_reuse_stats(self, catalog_id=None):
        """复用推荐运营统计（D9）：聚合 reuse_feedback.jsonl，按 member 汇总
        推荐次数/采纳次数/采纳率/最近推荐时间，并按阈值分级标注。"""
        per = {}  # (catalog_id, member) -> counts
        for rec in self._read_log(REUSE_FEEDBACK_FILE):
            fb = rec.get("reuse_feedback")
            if not isinstance(fb, dict):
                continue
            cid = fb.get("catalog_id")
            if catalog_id and cid != catalog_id:
                continue
            key = (cid, fb.get("member"))
            d = per.setdefault(key, {"recommended": 0, "reused": 0, "new": 0,
                                     "misunderstood": 0, "last_ts": ""})
            d["recommended"] += 1
            dec = fb.get("decision")
            if dec in ("reuse", "new", "misunderstood"):
                d[dec if dec != "reuse" else "reused"] += 1
            ts = rec.get("ts", "")
            if ts > d["last_ts"]:
                d["last_ts"] = ts
        members = []
        for (cid, member), d in sorted(per.items()):
            rec_n, reuse_n = d["recommended"], d["reused"]
            rate = round(reuse_n / rec_n, 2) if rec_n else None
            members.append({
                "catalog_id": cid, "member": member,
                "recommended": rec_n, "reused": reuse_n,
                "new": d["new"], "misunderstood": d["misunderstood"],
                "reuse_rate": rate, "last_recommended": d["last_ts"],
                "tier": self._reuse_tier(rec_n, rate),
            })
        return {"members": members, "total_feedback": sum(x["recommended"] for x in members)}

    @staticmethod
    def _reuse_tier(recommended, rate):
        """分级标注（D9）：样本少=待验证；样本足且采纳率高=高置信；其余=一般。"""
        if recommended < REUSE_TIER_MIN_SAMPLES:
            return "待验证"
        if recommended >= REUSE_TIER_TRUSTED_SAMPLES and rate is not None \
                and rate > REUSE_TIER_TRUSTED_RATE:
            return "高置信"
        return "一般"

    # ==================== 内部：提交 ====================

    def _get_mut(self, entry_id):
        if entry_id not in self.entries:
            raise KGError("entry 不存在: '%s'（可用 kg_query 先搜索）" % entry_id)
        return self.entries[entry_id]

    @staticmethod
    def _require_reason(reason):
        if not reason or not str(reason).strip():
            raise KGError("必须提供 reason：一句话说明这次改图谱的触发原因（哪个任务/发现了什么）")

    def _check_new_entry_strict(self, entry_id, entry):
        """对新写入/修改的 entry 从严：结构错误和 code 路径不存在都拒绝。"""
        r = ValidationResult()
        self._check_entry_structure(entry_id, entry, "(new)", r)
        for bad in self._missing_code_paths(entry):
            r.error("[%s].code 路径不存在: %s（以实际代码为准，先确认路径再写入）"
                    % (entry_id, bad))
        for rel in entry.get("related", []) or []:
            if isinstance(rel, dict) and rel.get("to") not in self.entries \
                    and rel.get("to") != entry_id:
                r.error("[%s].related 指向不存在的 entry: '%s'" % (entry_id, rel.get("to")))
        if r.errors:
            raise KGError("校验未通过，已拒绝写入:\n" + "\n".join("  - " + e for e in r.errors))

    def _commit(self, domain, op, detail, reason):
        """全量校验 → 原子写域文件 → 重建反向索引 → 追加 changelog。失败则回滚内存。"""
        result = self.validate()
        if not result.ok:
            # 回滚：重新从磁盘加载，丢弃内存变更
            self.__init__(self.root, self.kg_dir)
            raise KGError("全量校验未通过，已拒绝写入:\n"
                          + "\n".join("  - " + e for e in result.errors))
        info = self.domains[domain]
        info["data"]["updated_at"] = datetime.now().strftime("%Y-%m-%d")
        self._atomic_write(info["path"], info["data"])
        self.rebuild_reverse_index()
        record = {"op": op, "domain": domain, "reason": str(reason).strip()}
        record.update(detail)
        self._append_log(CHANGELOG_FILE, record)

    @staticmethod
    def _atomic_write(path: Path, data):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)

    def _append_log(self, filename, record):
        base = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "user": self._username(),
        }
        base.update(record)
        with open(self.kg_dir / filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(base, ensure_ascii=False) + "\n")

    @staticmethod
    def _username():
        try:
            return getpass.getuser()
        except Exception:
            return "unknown"

    # ==================== 反向索引 ====================

    def rebuild_reverse_index(self):
        reverse = {}
        for entry_id in self.entries:
            if not entry_id.startswith("_"):
                reverse[entry_id] = []
        for src_id, (src, src_domain) in self.entries.items():
            if src_id.startswith("_"):
                continue
            for rel in src.get("related", []) or []:
                if not isinstance(rel, dict):
                    continue
                target = rel.get("to")
                if not target or target.startswith("_") or target not in reverse:
                    continue
                reverse[target].append({
                    "from": src_id,
                    "from_domain": src_domain,
                    "context": rel.get("context", ""),
                    "confidence": rel.get("confidence", "draft"),
                })
        data = {
            "_comment": "自动生成，不要手动编辑。由 kg_core 在每次写操作后重建。",
            "generated_from": "graph-*.json",
            "incoming": reverse,
        }
        self._atomic_write(self.kg_dir / REVERSE_INDEX_FILE, data)
        return data
