#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
能力目录 + 复用推荐（v2.4.0）回归测试。纯标准库 unittest，可重跑。

运行：
  python -X utf8 -m unittest tests.test_capability_reuse -v
  或： python -X utf8 tests/test_capability_reuse.py

覆盖：写入(add_capability_catalog) / 粗排(scout_reuse) / 反馈(report_reuse_outcome)
      / 统计分级(get_reuse_stats) / 结构校验 / MCP stdio 协议层端到端。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
EXAMPLES = REPO / "examples"
sys.path.insert(0, str(TOOLS))

from kg_core import KG, KGError, REUSE_FEEDBACK_FILE  # noqa: E402


def _make_kg():
    """复制 examples 图谱到临时目录，返回 (root, kg_dir, KG 实例)。"""
    tmp = Path(tempfile.mkdtemp(prefix="kg_test_"))
    kg_dir = tmp / ".claude" / "kg"
    kg_dir.mkdir(parents=True)
    for f in EXAMPLES.glob("*.json"):
        shutil.copy(f, kg_dir / f.name)
    return tmp, kg_dir, KG(tmp, kg_dir)


REWARD_MEMBERS = [
    {"enum_value": "MAIL_GRANT", "id": 1, "name": "邮件发放",
     "scenarios": ["邮件", "发放", "补偿", "离线领取"]},
    {"enum_value": "DIRECT_GRANT", "id": 2, "name": "直接入包",
     "scenarios": ["即时", "入包", "立即到账"]},
    {"enum_value": "LOGIN_GRANT", "id": 3, "name": "登录时发放",
     "scenarios": ["登录", "上线发放", "每日领取", "签到"],
     "reuse_note": "无'连续/累计天数'维度；带'连续N天/累计'等计数条件的需求需新增计数逻辑"},
    {"enum_value": "LEVELUP_GRANT", "id": 4, "name": "升级时发放",
     "scenarios": ["升级", "等级奖励"], "status": "deprecated"},
]


def _add_reward_catalog(kg):
    return kg.add_capability_catalog(
        domain="economy", catalog_id="reward_grant_type", name_cn="奖励发放方式",
        members=REWARD_MEMBERS, reason="test",
        source={"file": "examples/mock-src/RewardGrantType.java", "symbol": "RewardGrantType"})


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.kg_dir, self.kg = _make_kg()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_catalog_ok(self):
        res = _add_reward_catalog(self.kg)
        self.assertEqual(res["type"], "concept")
        self.assertEqual(len(res["x_capability_members"]), 4)
        self.assertEqual(res["x_capability_source"]["symbol"], "RewardGrantType")
        # 重新加载确认落盘
        kg2 = KG(self.tmp, self.kg_dir)
        self.assertIn("reward_grant_type", kg2.entries)

    def test_reject_missing_enum_value(self):
        with self.assertRaises(KGError):
            self.kg.add_capability_catalog("economy", "bad", "坏",
                                           [{"name": "无枚举名"}], "r")

    def test_reject_duplicate_enum_value(self):
        with self.assertRaises(KGError):
            self.kg.add_capability_catalog("economy", "bad", "坏", [
                {"enum_value": "A"}, {"enum_value": "A"}], "r")

    def test_reject_empty_members(self):
        with self.assertRaises(KGError):
            self.kg.add_capability_catalog("economy", "bad", "坏", [], "r")

    def test_reject_bad_domain(self):
        with self.assertRaises(KGError):
            self.kg.add_capability_catalog("nosuchdomain", "c", "n",
                                           [{"enum_value": "A"}], "r")

    def test_reject_duplicate_catalog_id(self):
        _add_reward_catalog(self.kg)
        with self.assertRaises(KGError):
            _add_reward_catalog(self.kg)

    def test_reject_reason_required(self):
        with self.assertRaises(KGError):
            self.kg.add_capability_catalog("economy", "c", "n",
                                           [{"enum_value": "A"}], "")


class ScoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.kg_dir, self.kg = _make_kg()
        _add_reward_catalog(self.kg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _values(self, res):
        return [c["member"]["enum_value"] for c in res["candidates"]]

    def test_rc1_positive_recall(self):
        """RC-1 正向：上线发登录奖励 → 命中 LOGIN_GRANT。"""
        res = self.kg.scout_reuse("玩家上线时发个每日登录奖励", domain="economy")
        self.assertIn("LOGIN_GRANT", self._values(res))

    def test_deprecated_filtered(self):
        """deprecated 的 LEVELUP_GRANT 不参与推荐。"""
        res = self.kg.scout_reuse("玩家升级时发等级奖励", domain="economy")
        self.assertNotIn("LEVELUP_GRANT", self._values(res))

    def test_rc2_false_friend_carries_boundary(self):
        """RC-2 假朋友：连续登录7天 → 命中 LOGIN_GRANT 且 reuse_note 边界警告被带出
        （供 LLM 精排降级为 reference；粗排层只保证信息可达）。"""
        res = self.kg.scout_reuse("玩家连续登录7天后发累计奖励", domain="economy")
        login = next((c for c in res["candidates"]
                      if c["member"]["enum_value"] == "LOGIN_GRANT"), None)
        self.assertIsNotNone(login)
        self.assertIn("连续", login["member"]["reuse_note"])

    def test_top_k_limit(self):
        res = self.kg.scout_reuse("发放 奖励 登录 邮件 入包", domain="economy", limit=2)
        self.assertLessEqual(len(res["candidates"]), 2)

    def test_no_match_returns_empty(self):
        res = self.kg.scout_reuse("量子纠缠区块链元宇宙", domain="economy")
        self.assertEqual(res["total_matched"], 0)

    def test_reject_empty_requirement(self):
        with self.assertRaises(KGError):
            self.kg.scout_reuse("  ")

    def test_candidate_has_no_config_string(self):
        """D8：返回体不含可照抄的配置串（只有 enum_value/name/scenarios/reuse_note）。"""
        res = self.kg.scout_reuse("登录发奖励", domain="economy")
        for c in res["candidates"]:
            self.assertEqual(set(c["member"].keys()),
                             {"enum_value", "id", "name", "scenarios", "reuse_note"})


class FeedbackStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.kg_dir, self.kg = _make_kg()
        _add_reward_catalog(self.kg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_report_and_count(self):
        self.kg.report_reuse_outcome("上线发奖励", "reward_grant_type",
                                     "LOGIN_GRANT", "reuse", "复用触发")
        self.kg.report_reuse_outcome("连续7天", "reward_grant_type",
                                     "LOGIN_GRANT", "new", "计数新增")
        lines = (self.kg_dir / REUSE_FEEDBACK_FILE).read_text(
            encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_reject_bad_decision(self):
        with self.assertRaises(KGError):
            self.kg.report_reuse_outcome("x", "reward_grant_type", "LOGIN_GRANT", "bad")

    def test_reject_unknown_catalog(self):
        with self.assertRaises(KGError):
            self.kg.report_reuse_outcome("x", "nosuch", "A", "reuse")

    def test_stats_rate_and_tier_pending(self):
        """2 次反馈(reuse+new) → 采纳率 0.5，样本<3 → 待验证。"""
        self.kg.report_reuse_outcome("a", "reward_grant_type", "LOGIN_GRANT", "reuse")
        self.kg.report_reuse_outcome("b", "reward_grant_type", "LOGIN_GRANT", "new")
        st = self.kg.get_reuse_stats("reward_grant_type")
        lg = next(m for m in st["members"] if m["member"] == "LOGIN_GRANT")
        self.assertEqual(lg["recommended"], 2)
        self.assertEqual(lg["reused"], 1)
        self.assertEqual(lg["reuse_rate"], 0.5)
        self.assertEqual(lg["tier"], "待验证")

    def test_stats_tier_trusted(self):
        """12 次反馈、10 次 reuse → 采纳率 0.83 > 0.7 且样本≥10 → 高置信。"""
        for _ in range(10):
            self.kg.report_reuse_outcome("a", "reward_grant_type", "MAIL_GRANT", "reuse")
        for _ in range(2):
            self.kg.report_reuse_outcome("b", "reward_grant_type", "MAIL_GRANT", "new")
        st = self.kg.get_reuse_stats("reward_grant_type")
        mg = next(m for m in st["members"] if m["member"] == "MAIL_GRANT")
        self.assertEqual(mg["recommended"], 12)
        self.assertGreater(mg["reuse_rate"], 0.7)
        self.assertEqual(mg["tier"], "高置信")


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.kg_dir, self.kg = _make_kg()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_catalog_passes(self):
        _add_reward_catalog(self.kg)
        self.assertTrue(self.kg.validate().ok)

    def test_validate_catches_bad_members(self):
        from kg_core import KG as _KG  # noqa
        r = self.kg.validate()  # 先确保基线 ok
        self.assertTrue(r.ok)
        # 直接调结构校验函数验坏数据
        from kg_core import ValidationResult
        vr = ValidationResult()
        KG._check_capability_members("c", {"x_capability_members": [
            {"enum_value": "A"}, {"enum_value": "A"}, {"enum_value": "B", "status": "x"},
            {"name": "no ev"}]}, vr)
        self.assertTrue(any("重复" in e for e in vr.errors))
        self.assertTrue(any("status 非法" in e for e in vr.errors))
        self.assertTrue(any("缺少 enum_value" in e for e in vr.errors))


class McpStdioTest(unittest.TestCase):
    """真正启动 MCP server 子进程，走 JSON-RPC over stdio 端到端。"""

    def setUp(self):
        self.tmp, self.kg_dir, _ = _make_kg()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rpc(self, requests):
        """向 server 子进程喂多条 JSON-RPC，收集响应。"""
        payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(TOOLS / "kg_mcp_server.py"),
             "--root", str(self.tmp), "--kg", str(self.kg_dir)],
            input=payload, capture_output=True, text=True, encoding="utf-8", timeout=30)
        out = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out, proc

    def test_tools_registered(self):
        resps, _ = self._rpc([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        tools = {t["name"] for t in resps[-1]["result"]["tools"]}
        for name in ("kg_add_capability_catalog", "kg_scout_reuse",
                     "kg_report_reuse_outcome", "kg_get_reuse_stats"):
            self.assertIn(name, tools)

    def test_full_flow_over_stdio(self):
        """写目录 → 推荐 → 反馈 → 统计，全走 stdio 协议。"""
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "kg_add_capability_catalog", "arguments": {
                    "domain": "economy", "catalog_id": "reward_grant_type",
                    "name_cn": "奖励发放方式", "members": REWARD_MEMBERS, "reason": "stdio test"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "kg_scout_reuse", "arguments": {
                    "requirement": "玩家连续登录7天后发累计奖励", "domain": "economy"}}},
        ]
        resps, proc = self._rpc(reqs)
        by_id = {r["id"]: r for r in resps}
        # 写入成功
        self.assertFalse(by_id[2]["result"]["isError"], proc.stderr)
        # 推荐命中 LOGIN_GRANT
        scout_text = by_id[3]["result"]["content"][0]["text"]
        self.assertIn("LOGIN_GRANT", scout_text)
        self.assertIn("连续", scout_text)  # reuse_note 边界警告已带出


class VizTest(unittest.TestCase):
    """Phase 3 可视化：能力目录节点数据 + 静态 HTML 生成。"""

    def setUp(self):
        self.tmp, self.kg_dir, self.kg = _make_kg()
        _add_reward_catalog(self.kg)
        # 造反馈让 MAIL_GRANT 达高置信
        for _ in range(10):
            self.kg.report_reuse_outcome("a", "reward_grant_type", "MAIL_GRANT", "reuse")
        for _ in range(2):
            self.kg.report_reuse_outcome("b", "reward_grant_type", "MAIL_GRANT", "new")
        import gen_graph_html
        self.g = gen_graph_html

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_catalog_node_and_members(self):
        data = self.g.load_data(self.kg.kg_dir, self.kg.stats()["per_entry"],
                                self.kg.get_reuse_stats())
        cat = next(n for n in data["nodes"] if n["type"] == "capability_catalog")
        self.assertEqual(cat["id"], "reward_grant_type")
        self.assertEqual(len(cat["members"]), 4)
        # 高置信统计正确带入
        mail = next(m for m in cat["members"] if m["enum_value"] == "MAIL_GRANT")
        self.assertEqual(mail["tier"], "高置信")
        self.assertEqual(mail["recommended"], 12)
        # deprecated 成员排最后
        self.assertEqual(cat["members"][-1]["status"], "deprecated")
        # 溯源
        self.assertEqual(cat["source"]["symbol"], "RewardGrantType")

    def test_static_html_markers(self):
        out = self.kg_dir / "graph_view.html"
        rc = self.g.gen_static(self.tmp, self.kg_dir, out)
        self.assertEqual(rc, 0)
        html = out.read_text("utf-8")
        for marker in ("capability_catalog", "t-高置信", "能力成员", "mem-note"):
            self.assertIn(marker, html)


# <APPEND-TESTS>


if __name__ == "__main__":
    unittest.main(verbosity=2)
