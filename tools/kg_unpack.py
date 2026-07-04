#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_unpack — 图谱拆箱：把 kg_pack.py 打包的 box 导入当前项目作为参考骨架

适用场景：目标项目和来源项目业务相似（如同一套代码衍生的项目），来源项目的
系统划分、关联关系、持久化踩坑对目标项目有参考价值。

导入策略（全部经 kg_core 写入口，自动校验 + 记 changelog）：
  - 域：目标没有的补建；已有的沿用
  - entry：目标已存在同名 id 的跳过（不覆盖本地数据）
  - code 路径：逐条对目标项目校验——真实存在的保留在 code；不存在的移入
    x_ref_code 扩展字段（保留参考价值，不污染导航数据）
  - 关联边：两端 entry 都存在才导入，confidence 一律降为 draft（未在本项目验证）
  - MD 文档：目标没有的写入，文件头标注来源，内容需人工按本项目校对
  - 每个 entry 打上 x_ref_source 标记来源

用法（从目标项目根）:
  python .claude/kg/tools/kg_unpack.py kg-box-xxx.json
  python kg_unpack.py <box.json> --root <project_root> --kg <kg_dir>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, KGError  # noqa: E402


def adapt_code(code: dict, root: Path):
    """路径存在的保留，不存在的移入 x_ref_code。返回 (new_code, ref_code, kept, moved)。"""
    new_code, ref_code = {}, {}
    kept = moved = 0
    for key, value in (code or {}).items():
        if key.startswith("_"):
            new_code[key] = value
            continue
        paths = [value] if isinstance(value, str) else (value if isinstance(value, list) else [])
        valid = [p for p in paths if isinstance(p, str) and (root / p.rstrip("/")).exists()]
        invalid = [p for p in paths if p not in valid]
        kept += len(valid)
        moved += len(invalid)
        if valid:
            new_code[key] = valid[0] if (isinstance(value, str) and len(valid) == 1) else valid
        if invalid:
            ref_code[key] = invalid
    return new_code, ref_code, kept, moved


def main():
    parser = argparse.ArgumentParser(description="图谱拆箱：导入 kg-box 作为参考骨架")
    parser.add_argument("box", type=Path, help="kg_pack.py 生成的 box 文件")
    parser.add_argument("--root", type=Path, default=Path("."), help="目标项目根（默认当前目录）")
    parser.add_argument("--kg", type=Path, default=None,
                        help="图谱目录（默认自动探测 .claude/kg 或 tools/qx_rag）")
    args = parser.parse_args()

    if not args.box.exists():
        print("ERROR: box 文件不存在: %s" % args.box)
        return 1
    box = json.loads(args.box.read_text(encoding="utf-8"))
    if box.get("kg_box_version") != "1":
        print("ERROR: 不支持的 box 版本: %s" % box.get("kg_box_version"))
        return 1

    try:
        kg = KG(args.root, args.kg)
    except KGError as e:
        print("ERROR: %s" % e)
        return 1

    src = box.get("source_project", "unknown")
    reason = "拆箱导入自 %s（打包于 %s）" % (src, (box.get("packed_at") or "")[:10])
    root = kg.root
    report = {"domains_added": [], "entries_added": [], "entries_skipped": [],
              "paths_kept": 0, "paths_ref": 0, "edges_added": 0, "edges_skipped": 0,
              "cross_added": 0, "docs_written": 0, "errors": []}

    # 1. 域
    for domain, info in box.get("domains", {}).items():
        if domain in kg.domains:
            continue
        try:
            kg.add_domain(domain, info.get("desc") or ("来自 %s 的域" % src), reason)
            report["domains_added"].append(domain)
        except KGError as e:
            report["errors"].append("域 %s: %s" % (domain, e))

    # 2. entry（不带 related，第 3 步统一补边）
    imported_related = {}
    for entry_id, box_entry in box.get("entries", {}).items():
        if entry_id in kg.entries:
            report["entries_skipped"].append(entry_id)
            continue
        e = dict(box_entry)
        domain = e.pop("_domain", None)
        if domain not in kg.domains:
            report["errors"].append("entry %s: 所属域 %s 不存在" % (entry_id, domain))
            continue
        imported_related[entry_id] = e.pop("related", []) or []
        new_code, ref_code, kept, moved = adapt_code(e.get("code"), root)
        report["paths_kept"] += kept
        report["paths_ref"] += moved
        if not new_code:
            new_code = {"_ref": "路径见 x_ref_code（来自 %s，本项目未验证）" % src}
        e["code"] = new_code
        if ref_code:
            e["x_ref_code"] = ref_code
        e["x_ref_source"] = src
        try:
            kg.add_entry(domain, entry_id, e, reason)
            report["entries_added"].append(entry_id)
        except KGError as ex:
            report["errors"].append("entry %s: %s" % (entry_id, ex))
            imported_related.pop(entry_id, None)

    # 3. 关联边（两端都存在才导入，一律 draft）
    for from_id, rels in imported_related.items():
        for rel in rels:
            if not isinstance(rel, dict):
                continue
            to_id = rel.get("to")
            if to_id not in kg.entries:
                report["edges_skipped"] += 1
                continue
            try:
                kg.add_relation(from_id, to_id, rel.get("context", ""), "draft", reason)
                report["edges_added"] += 1
            except KGError:
                report["edges_skipped"] += 1

    # 4. 跨域关联（重复的静默跳过）
    for rel in box.get("cross_domain_relations", []):
        try:
            kg.add_cross_relation(rel.get("from"), rel.get("to"),
                                  rel.get("context", ""), "draft", reason)
            report["cross_added"] += 1
        except KGError:
            pass

    # 5. MD 文档（目标没有的写入，标注来源）
    entries_dir = kg.kg_dir / "entries"
    entries_dir.mkdir(exist_ok=True)
    for entry_id, content in box.get("docs", {}).items():
        if entry_id not in report["entries_added"]:
            continue
        doc_path = entries_dir / ("%s.md" % entry_id)
        if doc_path.exists():
            continue
        header = ("> ⚠ 参考条目：拆箱自 %s（%s），描述的是来源项目的实现。\n"
                  "> 使用前需按本项目实际代码校对，校对后删除本标注。\n\n"
                  % (src, (box.get("packed_at") or "")[:10]))
        doc_path.write_text(header + content, encoding="utf-8")
        report["docs_written"] += 1

    # ==================== 报告 ====================
    print("拆箱完成（来源: %s）" % src)
    print("  新建域: %d 个 %s" % (len(report["domains_added"]), report["domains_added"] or ""))
    print("  导入 entry: %d 个；跳过（已存在）: %d 个 %s"
          % (len(report["entries_added"]), len(report["entries_skipped"]),
             report["entries_skipped"] or ""))
    print("  code 路径: %d 条在本项目有效；%d 条移入 x_ref_code 待人工核对"
          % (report["paths_kept"], report["paths_ref"]))
    print("  关联边: 导入 %d 条（全部 draft）；跳过 %d 条" % (report["edges_added"], report["edges_skipped"]))
    print("  跨域关联: 导入 %d 条（全部 draft）" % report["cross_added"])
    print("  MD 文档: 写入 %d 份（文件头已标注来源）" % report["docs_written"])
    for err in report["errors"]:
        print("  [错误] %s" % err)
    print()
    print("下一步：")
    print("  1. 对导入 entry 逐个核对——x_ref_code 里的路径找到本项目对应实现后，")
    print("     用 kg_update_entry 移回 code 字段")
    print("  2. draft 边在实际任务中验证后 kg_verify_edge 升级")
    print("  3. 跑校验: python %s/tools/validate.py" % kg.kg_dir.name)
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
