#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反向索引生成 CLI（薄封装，逻辑在 kg_core.py）

正常情况下不需要手动跑——kg_core 在每次写操作后会自动重建 reverse_index.json。
本脚本用于人工修复（KG_ALLOW_DIRECT_EDIT=1 直接改过 JSON）后的手动重建。

用法:
  python build_reverse_index.py
  python build_reverse_index.py --root <project_root>
  python build_reverse_index.py --kg <kg_dir>
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, KGError, REVERSE_INDEX_FILE  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="重建知识图谱反向索引")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根（默认当前目录）")
    parser.add_argument("--kg", type=Path, default=None,
                        help="图谱目录（默认自动探测 .claude/kg 或 tools/qx_rag）")
    args = parser.parse_args()

    try:
        kg = KG(args.root, args.kg)
    except KGError as e:
        print("ERROR: %s" % e)
        return 1

    data = kg.rebuild_reverse_index()
    incoming = data["incoming"]
    print("已生成: %s" % (kg.kg_dir / REVERSE_INDEX_FILE))
    print("  entries: %d" % len(incoming))
    print("  reverse edges: %d" % sum(len(v) for v in incoming.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
