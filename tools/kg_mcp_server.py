#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_mcp_server — 知识图谱 MCP stdio server（纯标准库）

作为图谱的唯一读写入口暴露给 AI 编程助手（Claude Code / Codex 等支持 MCP 的工具）。
所有写操作在 kg_core 内完成 schema 校验、全量校验、changelog 记录、反向索引重建；
所有查询记录 querylog。

注册方式（Claude Code，项目根 .mcp.json）:
  {"mcpServers": {"kg": {"command": "python", "args": ["-X","utf8",".claude/kg/tools/kg_mcp_server.py"]}}}

注册方式（Codex，~/.codex/config.toml）:
  [mcp_servers.kg]
  command = "python"
  args = [".claude/kg/tools/kg_mcp_server.py"]

图谱目录自动探测：<cwd>/.claude/kg（标准安装布局）或 <cwd>/tools/qx_rag（源仓库布局），也可 --kg / KG_DIR 指定。
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, KGError  # noqa: E402

SERVER_NAME = "kg"


def _server_version():
    """从发行包/安装目录的 VERSION 文件读取，避免 serverInfo.version 与 VERSION 不一致
    （曾硬编码导致它滞后于实际发版版本）。读不到时回退 0.0.0。"""
    try:
        v = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
        return v or "0.0.0"
    except Exception:
        return "0.0.0"


SERVER_VERSION = _server_version()

REASON_SCHEMA = {
    "type": "string",
    "description": "本次修改的触发原因：哪个任务/验证了什么/发现了什么。会写入 changelog，必填。",
}

TOOLS = [
    {
        "name": "kg_overview",
        "description": "获取知识图谱主索引：域清单（每个域的描述和 key_entries）+ 跨域关联。"
                       "接到新需求时先调这个定位涉及哪些域，替代直接读 graph.json。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kg_query",
        "description": "按关键词搜索图谱 entry（id/中文名/tags/摘要/代码路径/关联描述的字面匹配）。"
                       "返回命中 entry 的代码路径、持久化注意点、出边和入边。"
                       "开发新功能/跨模块改动前先查这个，代替盲目 grep。查询会记录到 querylog。"
                       "注意这是字面匹配：无命中或命中与需求不符时，不要直接放弃——"
                       "改调 kg_catalog 拿轻量目录，由你语义判断哪些 entry 相关。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，可空格分隔多个，支持中文"},
                "domain": {"type": "string",
                           "description": "可选，限定某个域；可用的域见 kg_overview 返回的 domains"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_catalog",
        "description": "获取全部（或某域）entry 的轻量目录：id/中文名/摘要/标签。"
                       "kg_query 关键词没命中或命中可疑时调用——目录很小，"
                       "由你（AI）通读后语义判断哪些 entry 和当前需求相关，"
                       "再用 kg_get_entry 取详情。通读目录后确认图谱确实没有相关系统，才 fallback 到 grep。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string",
                           "description": "可选，限定某个域；可用的域见 kg_overview 返回的 domains"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_get_entry",
        "description": "按 entry_id 精确获取单个 entry 的完整信息（含入边 incoming、doc 是否存在、"
                       "使用统计）。从 kg_catalog 语义挑选后用它取详情。",
        "inputSchema": {
            "type": "object",
            "properties": {"entry_id": {"type": "string"}},
            "required": ["entry_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_validate",
        "description": "全量校验图谱完整性（结构/悬空引用/代码路径漂移/孤儿节点），返回错误、警告和统计。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kg_stats",
        "description": "图谱运营统计。返回全局汇总（总查询/总命中/反馈准确率/被查与未被查 entry 数/总变更）"
                       "，以及可选的 per_entry 明细。用户问'图谱用得怎么样/质量如何/哪些 entry 没人查'时用；"
                       "单 entry 的统计见 kg_get_entry 返回里的 stats。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "per_entry": {"type": "boolean",
                              "description": "是否返回每个 entry 的明细（默认 false，只返回汇总）"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_add_entry",
        "description": "新增一个图谱 entry（新功能/新系统开发完成后调用）。"
                       "写入前强校验：code 路径必须真实存在、related 目标必须存在、type 必须合法。"
                       "summary 写一句话说明系统做什么；persistence_pitfalls 写持久化踩坑（改动前必读的那种）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string",
                           "description": "所属域，必须已存在；可用的域见 kg_overview 返回的 domains"},
                "entry_id": {"type": "string",
                             "description": "英文小写下划线 id，如 equip_huishou"},
                "type": {"type": "string", "enum": ["system", "feature", "concept"]},
                "name_cn": {"type": "string", "description": "中文名"},
                "summary": {"type": "string", "description": "一句话：这个系统/功能做什么"},
                "code": {
                    "type": "object",
                    "description": "代码定位，key 语义化（manager/data/config/handler...），"
                                   "value 是项目根相对路径（str 或 str 数组），目录以 / 结尾。路径必须真实存在。",
                },
                "related": {
                    "type": "array",
                    "description": "出边：和哪些已有 entry 有联动",
                    "items": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "目标 entry_id，必须已存在"},
                            "context": {"type": "string", "description": "具体怎么联动（写清楚调用点/机制）"},
                            "confidence": {"type": "string", "enum": ["draft", "verified"],
                                           "description": "verified=本次实际验证过；没验证过写 draft"},
                        },
                        "required": ["to", "context", "confidence"],
                    },
                },
                "persistence_pitfalls": {
                    "type": "array", "items": {"type": "string"},
                    "description": "持久化/时序踩坑，每条一句可执行的告诫，如\"X 后必须 saveToDB\"",
                },
                "tags": {"type": "array", "items": {"type": "string"}},
                "extra_fields": {
                    "type": "object",
                    "description": "可选：项目自定义扩展字段，key 必须以 x_ 开头（如 x_gm_commands）",
                },
                "reason": REASON_SCHEMA,
            },
            "required": ["domain", "entry_id", "type", "name_cn", "summary", "code", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_update_entry",
        "description": "修改已有 entry 的字段（整字段替换，不是深合并）。"
                       "常见场景：修正漂移的 code 路径、改 summary。"
                       "追加踩坑用 kg_add_pitfall，加关联用 kg_add_relation，升级边用 kg_verify_edge。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "patch": {
                    "type": "object",
                    "description": "要替换的字段，仅限: type/name_cn/doc/summary/code/related/persistence_pitfalls/tags",
                },
                "reason": REASON_SCHEMA,
            },
            "required": ["entry_id", "patch", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_add_relation",
        "description": "给已有 entry 加一条出边（发现了新的跨系统联动时调用）。两端 entry 必须已存在。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
                "context": {"type": "string", "description": "具体怎么联动（调用点/机制），不能空泛"},
                "confidence": {"type": "string", "enum": ["draft", "verified"],
                               "description": "本次实际验证过写 verified，否则 draft"},
                "reason": REASON_SCHEMA,
            },
            "required": ["from_id", "to_id", "context", "confidence", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_add_pitfall",
        "description": "给已有 entry 追加一条持久化/时序踩坑（开发中踩到坑后立刻记录）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "pitfall": {"type": "string",
                            "description": "一句可执行的告诫，如\"回收后装备从背包移除必须 saveToDB\""},
                "reason": REASON_SCHEMA,
            },
            "required": ["entry_id", "pitfall", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_feedback",
        "description": "回报图谱信息的准确性（遥测，不改图谱数据，无需用户确认）。"
                       "任务中实际使用了某 entry 的信息后调用：代码路径直达、联动信息正确 → accurate=true；"
                       "路径漂移、信息误导、缺关键联动 → accurate=false 并在 note 写明哪里不对。"
                       "每个任务对每个用到的 entry 报一次即可。数据用于评估图谱质量和迭代取舍。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "accurate": {"type": "boolean"},
                "note": {"type": "string",
                         "description": "accurate=false 时必写：哪里不准（错误路径/缺失联动等）"},
            },
            "required": ["entry_id", "accurate"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_add_domain",
        "description": "新建一个域（生成 graph-<domain>.json 并注册到主索引）。"
                       "仅在图谱初始化（/kg-init）或确实出现新业务大类时使用，日常开发加 entry 不需要新域。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "域 id：小写英文/数字/下划线，字母开头"},
                "desc": {"type": "string", "description": "一句话中文：这个域涵盖什么"},
                "key_entries": {"type": "array", "items": {"type": "string"},
                                "description": "可选：该域最核心的 2-3 个 entry_id（可后补）"},
                "reason": REASON_SCHEMA,
            },
            "required": ["domain", "desc", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_add_cross_relation",
        "description": "加一条域级跨域关联（主索引的 cross_domain_relations），"
                       "表示两个域之间存在系统性联动。entry 级联动用 kg_add_relation。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_domain": {"type": "string"},
                "to_domain": {"type": "string"},
                "context": {"type": "string", "description": "一句话：两个域怎么联动"},
                "confidence": {"type": "string", "enum": ["draft", "verified"]},
                "reason": REASON_SCHEMA,
            },
            "required": ["from_domain", "to_domain", "context", "confidence", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_verify_edge",
        "description": "把一条 draft 边升级为 verified（本次开发实际验证了该联动真实存在时调用）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
                "reason": REASON_SCHEMA,
            },
            "required": ["from_id", "to_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_add_capability_catalog",
        "description": "录入一个'能力目录'（经验层）——某个可配置行为的枚举/常量族，"
                       "每个成员是一种现成能力（如奖励发放方式、通知触发方式、任务条件类型）。"
                       "用于后续复用推荐（kg_scout_reuse），避免把'配一下就能实现'的需求当新功能开发。"
                       "何时用（三条同时满足）：① 成员是行为变体，非纯数据标签；"
                       "② 被 switch/配表/注册表消费；③ 需求方用'描述'提需求而非点枚举名。"
                       "流程：你（LLM）读源码整理成员的事实字段(enum_value/id/name)+起草语义字段"
                       "(scenarios/reuse_note)，缺口处给用户选项，**经用户确认后**再调此工具写入。"
                       "reuse_note 要写清该能力的'边界'（配不出来的维度，如'无方向/无连续天数'），"
                       "这是防止误推荐的关键。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "所属域，必须已存在"},
                "catalog_id": {"type": "string", "description": "英文小写下划线 id，如 reward_grant_type"},
                "name_cn": {"type": "string", "description": "中文名，如'奖励发放方式'"},
                "summary": {"type": "string", "description": "可选，一句话说明这个目录是什么"},
                "source": {
                    "type": "object",
                    "description": "溯源线索（可选）：枚举所在文件与符号名，便于人工核对。不做机器交叉校验。",
                    "properties": {"file": {"type": "string"}, "symbol": {"type": "string"}},
                },
                "members": {
                    "type": "array",
                    "description": "能力成员列表，至少一个",
                    "items": {
                        "type": "object",
                        "properties": {
                            "enum_value": {"type": "string", "description": "枚举值/常量名（必填）"},
                            "id": {"type": ["integer", "null"], "description": "数值 id（可选）"},
                            "name": {"type": "string", "description": "中文名/说明"},
                            "scenarios": {"type": "array", "items": {"type": "string"},
                                          "description": "适用场景关键词，供粗排匹配（如 登录/减伤/发放）"},
                            "reuse_note": {"type": "string",
                                           "description": "复用边界：这个能力配不出来的维度/限制，防误推荐"},
                            "status": {"type": "string", "enum": ["active", "deprecated"],
                                       "description": "默认 active；deprecated 不参与推荐"},
                        },
                        "required": ["enum_value"],
                    },
                },
                "reason": REASON_SCHEMA,
            },
            "required": ["domain", "catalog_id", "name_cn", "members", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_scout_reuse",
        "description": "复用推荐（分诊闸门）：新造能力/加新行为的需求进来时**先调这个**，"
                       "看经验层里有没有现成能力可配，避免重复开发。返回按需求粗排出的 top-k 相关"
                       "能力成员（扁平列表，每个带所属目录）。这是**粗排**，你要做**精排**：读每个候选的"
                       "reuse_note，判断需求是否含超出该能力语义的限定词（方向/时序/计数/条件）——"
                       "有则该候选降为'参考'并提示那个维度需新增，无则'可复用推荐'。"
                       "**必须把结论转述给用户并给选项（复用/新增/理解错了），等用户拍板**，"
                       "不要直接照着推荐写代码（不返回可照抄配置串是刻意的）。"
                       "用户拍板后调 kg_report_reuse_outcome 记录结果。"
                       "例外：用户已点名具体机制时跳过本工具。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "requirement": {"type": "string", "description": "需求描述（自然语言），如'玩家连续登录7天发奖励'"},
                "domain": {"type": "string", "description": "可选，限定某个域缩小范围（推荐先判域再查）"},
            },
            "required": ["requirement"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_report_reuse_outcome",
        "description": "回写复用推荐的结果（遥测，进 reuse_feedback.jsonl，无需 reason/确认）。"
                       "kg_scout_reuse 推荐后、用户拍板了，调此工具记一笔：用户选了复用(reuse)/"
                       "当新功能开发(new)/需求被理解错了(misunderstood)。数据用于统计采纳率、"
                       "发现误推荐、迭代 scenarios 质量。每次推荐拍板后记一次。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "requirement": {"type": "string", "description": "这次推荐针对的需求描述"},
                "catalog_id": {"type": "string", "description": "命中能力所属目录 id"},
                "member": {"type": "string", "description": "被推荐的成员 enum_value"},
                "decision": {"type": "string", "enum": ["reuse", "new", "misunderstood"],
                             "description": "用户拍板结果"},
                "note": {"type": "string", "description": "可选，补充说明（如'复用发放触发，计数新增'）"},
            },
            "required": ["requirement", "catalog_id", "member", "decision"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kg_get_reuse_stats",
        "description": "复用推荐运营统计：聚合 reuse_feedback，返回每个能力成员的推荐次数/采纳次数/"
                       "采纳率/最近推荐时间，并按阈值分级（推荐<3次=待验证 / ≥10次且采纳率>70%=高置信）。"
                       "用于评估经验层质量：哪些能力常被成功复用、哪些总被推却没人用（scenarios 可能太宽）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalog_id": {"type": "string", "description": "可选，限定某个目录；不填返回全局"},
            },
            "additionalProperties": False,
        },
    },
]


class KgMcpServer:
    def __init__(self, root, kg_dir):
        self.root = root
        self.kg_dir = kg_dir

    # 每次调用重新加载，避免外部改动（git pull / 手工修）后读到陈旧缓存
    def _kg(self):
        return KG(self.root, self.kg_dir)

    def call_tool(self, name, args):
        kg = self._kg()
        if name == "kg_overview":
            return kg.overview()
        if name == "kg_query":
            hits = kg.query(args["query"], args.get("domain"))
            if not hits:
                return {"hits": [], "hint": "关键词无字面命中≠图谱没有：先调 kg_catalog 拿目录"
                                            "做语义判断；通读目录确认确实没有后再 fallback 到 grep，"
                                            "确认是图谱缺失可用 kg_add_entry 补录。"}
            return {"hits": hits}
        if name == "kg_catalog":
            return {"catalog": kg.catalog(args.get("domain")),
                    "hint": "通读后挑出与需求相关的 entry_id，用 kg_get_entry 取详情"}
        if name == "kg_get_entry":
            return kg.get_entry(args["entry_id"], log=True)
        if name == "kg_validate":
            return kg.validate().to_json()
        if name == "kg_stats":
            s = kg.stats()
            return s if args.get("per_entry") else {"summary": s["summary"]}
        if name == "kg_add_entry":
            entry = {k: args[k] for k in
                     ("type", "name_cn", "summary", "code", "related",
                      "persistence_pitfalls", "tags") if k in args}
            entry.update(args.get("extra_fields") or {})
            return kg.add_entry(args["domain"], args["entry_id"], entry, args["reason"])
        if name == "kg_update_entry":
            return kg.update_entry(args["entry_id"], args["patch"], args["reason"])
        if name == "kg_add_relation":
            return kg.add_relation(args["from_id"], args["to_id"], args["context"],
                                   args["confidence"], args["reason"])
        if name == "kg_add_pitfall":
            return kg.add_pitfall(args["entry_id"], args["pitfall"], args["reason"])
        if name == "kg_verify_edge":
            return kg.verify_edge(args["from_id"], args["to_id"], args["reason"])
        if name == "kg_feedback":
            return kg.feedback(args["entry_id"], args["accurate"], args.get("note", ""))
        if name == "kg_add_domain":
            return kg.add_domain(args["domain"], args["desc"], args["reason"],
                                 args.get("key_entries"))
        if name == "kg_add_cross_relation":
            return kg.add_cross_relation(args["from_domain"], args["to_domain"],
                                         args["context"], args["confidence"], args["reason"])
        if name == "kg_add_capability_catalog":
            return kg.add_capability_catalog(
                args["domain"], args["catalog_id"], args["name_cn"], args["members"],
                args["reason"], source=args.get("source"), summary=args.get("summary"))
        if name == "kg_scout_reuse":
            return kg.scout_reuse(args["requirement"], args.get("domain"))
        if name == "kg_report_reuse_outcome":
            return kg.report_reuse_outcome(args["requirement"], args["catalog_id"],
                                           args["member"], args["decision"], args.get("note", ""))
        if name == "kg_get_reuse_stats":
            return kg.get_reuse_stats(args.get("catalog_id"))
        raise KGError("未知工具: %s" % name)

    # ==================== JSON-RPC over stdio ====================

    def handle(self, msg):
        method = msg.get("method")
        msg_id = msg.get("id")
        if msg_id is None:  # notification，不回包
            return None
        try:
            if method == "initialize":
                client_ver = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
                result = {
                    "protocolVersion": client_ver,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = msg.get("params") or {}
                result = self._tool_call_result(params.get("name"),
                                                params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32601, "message": "Method not found: %s" % method}}
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:  # 协议层兜底，避免 server 因单条消息挂掉
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32603, "message": str(e)}}

    def _tool_call_result(self, name, args):
        try:
            data = self.call_tool(name, args)
            text = json.dumps(data, ensure_ascii=False, indent=1)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except KGError as e:
            return {"content": [{"type": "text", "text": "KG_ERROR: %s" % e}], "isError": True}
        except Exception:
            return {"content": [{"type": "text",
                                 "text": "INTERNAL_ERROR:\n%s" % traceback.format_exc()}],
                    "isError": True}

    def serve(self):
        stdin = sys.stdin.buffer
        stdout = sys.stdout.buffer
        for raw in stdin:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(msg)
            if resp is not None:
                stdout.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="KG MCP stdio server")
    parser.add_argument("--root", type=Path, default=Path("."),
                        help="项目根（默认 cwd，MCP 客户端从项目根启动时无需指定）")
    parser.add_argument("--kg", type=Path, default=None,
                        help="图谱目录（默认自动探测 .claude/kg 或 tools/qx_rag）")
    args = parser.parse_args()
    server = KgMcpServer(args.root, args.kg)
    # 启动时快速自检，图谱目录不存在则立即报错退出（客户端能看到 stderr）
    try:
        server._kg()
    except KGError as e:
        print("kg_mcp_server 启动失败: %s" % e, file=sys.stderr)
        sys.exit(1)
    server.serve()


if __name__ == "__main__":
    main()
