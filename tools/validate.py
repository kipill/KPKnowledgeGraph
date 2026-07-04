#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Knowledge Graph 校验 CLI（薄封装，逻辑在 kg_core.py）

用法:
  python validate.py                      # 默认从项目根运行
  python validate.py --strict             # WARNING 也 fail
  python validate.py --json               # JSON 格式输出（CI 用）
  python validate.py --root <path>        # 指定项目根（默认当前目录）
  python validate.py --kg <kg_dir>        # 指定图谱目录（默认自动探测）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, KGError  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Knowledge Graph 多图谱校验")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根目录（默认当前目录）")
    parser.add_argument("--kg", type=Path, default=None,
                        help="图谱目录（默认自动探测 .claude/kg 或 tools/qx_rag）")
    parser.add_argument("--strict", action="store_true", help="WARNING 也 fail")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    try:
        kg = KG(args.root, args.kg)
    except KGError as e:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(e)], "warnings": [],
                              "info": [], "stats": {}}, ensure_ascii=False, indent=2))
        else:
            print("ERROR: %s" % e)
        sys.exit(1)

    result = kg.validate()

    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    if not result.ok:
        sys.exit(1)
    if args.strict and result.warnings:
        sys.exit(2)
    sys.exit(0)


def _print_human(result):
    if result.errors:
        print("=" * 60)
        print("ERRORS (%d):" % len(result.errors))
        for e in result.errors:
            print("  [E] %s" % e)
    if result.warnings:
        print("=" * 60)
        print("WARNINGS (%d):" % len(result.warnings))
        for w in result.warnings:
            print("  [W] %s" % w)
    if result.info:
        print("=" * 60)
        print("INFO (%d):" % len(result.info))
        for i in result.info:
            print("  [i] %s" % i)
    if result.stats:
        print("=" * 60)
        print("STATS:")
        for k, v in result.stats.items():
            print("  %s: %s" % (k, v))
    print("=" * 60)
    print("Result: %s" % ("OK" if result.ok else "FAIL"))


if __name__ == "__main__":
    main()
