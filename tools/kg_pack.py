#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_pack — 图谱装箱：把当前项目的图谱记录打包成单个 box 文件

用途：项目 A 积累的图谱（系统划分、关联关系、持久化踩坑、MD 深度文档）打包后，
在业务相似的项目 B 里用 kg_unpack.py 拆箱作为参考骨架，避免从零初始化。

打包内容：域清单、跨域关联、全部 entry、已存在的 entries/*.md 全文。
不打包：日志（changelog/querylog 是项目自己的历史）、reverse_index（自动生成）。

用法（从项目根）:
  python .claude/kg/tools/kg_pack.py                      # 输出 kg-box-<项目名>.json 到图谱目录
  python kg_pack.py --out /path/to/box.json
  python kg_pack.py --root <project_root> --kg <kg_dir>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, KGError  # noqa: E402

BOX_VERSION = "1"


def pack(kg: KG) -> dict:
    entries = {}
    docs = {}
    for entry_id, (entry, domain) in kg.entries.items():
        if entry_id.startswith("_"):
            continue
        e = dict(entry)
        e["_domain"] = domain
        entries[entry_id] = e
        doc_rel = entry.get("doc")
        if doc_rel:
            doc_path = kg.kg_dir / doc_rel
            if doc_path.exists():
                docs[entry_id] = doc_path.read_text(encoding="utf-8")
    main = kg.main or {}
    return {
        "kg_box_version": BOX_VERSION,
        "source_project": kg.root.name,
        "packed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "domains": {d: {"desc": info.get("desc", ""),
                        "key_entries": info.get("key_entries", [])}
                    for d, info in main.get("domains", {}).items()},
        "cross_domain_relations": main.get("cross_domain_relations", []),
        "entries": entries,
        "docs": docs,
    }


def main():
    parser = argparse.ArgumentParser(description="图谱装箱：打包当前项目图谱为 box 文件")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根（默认当前目录）")
    parser.add_argument("--kg", type=Path, default=None,
                        help="图谱目录（默认自动探测 .claude/kg 或 tools/qx_rag）")
    parser.add_argument("--out", type=Path, default=None,
                        help="输出文件（默认 <图谱目录>/kg-box-<项目名>.json）")
    args = parser.parse_args()

    try:
        kg = KG(args.root, args.kg)
    except KGError as e:
        print("ERROR: %s" % e)
        return 1

    box = pack(kg)
    if not box["entries"]:
        print("ERROR: 图谱为空，没有可打包的 entry")
        return 1

    out = args.out or (kg.kg_dir / ("kg-box-%s.json" % kg.root.name))
    out = out if out.is_absolute() else Path.cwd() / out
    out.write_text(json.dumps(box, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("已装箱: %s" % out)
    print("  来源项目: %s" % box["source_project"])
    print("  域: %d 个（%s）" % (len(box["domains"]), ", ".join(sorted(box["domains"]))))
    print("  entry: %d 个（含 MD 文档 %d 份）" % (len(box["entries"]), len(box["docs"])))
    print("  跨域关联: %d 条" % len(box["cross_domain_relations"]))
    print()
    print("在目标项目拆箱: python <kg_dir>/tools/kg_unpack.py %s" % out.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
