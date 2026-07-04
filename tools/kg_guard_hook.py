#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_guard_hook — Claude Code PreToolUse hook：拦截对图谱文件的直接 Edit/Write

图谱 JSON 的唯一写入口是 kg MCP 工具（kg_add_entry / kg_update_entry / ...），
直接改文件会绕过 schema 校验、changelog 和反向索引重建，这正是图谱漂移的来源。

判定规则：目标文件名匹配受保护模式，且其所在目录含 graph.json（即是图谱目录）→ 阻止。
entries/*.md 深度文档不受限，可以直接编辑。

逃生口：设置环境变量 KG_ALLOW_DIRECT_EDIT=1 可跳过拦截（人工修复场景）。
任何异常一律放行（fail-open），保证 hook 故障不影响正常开发。

注册（.claude/settings.json，exec 形式 + ${CLAUDE_PROJECT_DIR} 锚定项目根，
不受会话 cd 进子目录影响；Windows/Unix 通用）:
  "hooks": {"PreToolUse": [{"matcher": "Edit|Write",
    "hooks": [{"type": "command", "command": "python",
               "args": ["-X", "utf8", "${CLAUDE_PROJECT_DIR}/.claude/kg/tools/kg_guard_hook.py"],
               "timeout": 10}]}]}
"""

import fnmatch
import json
import os
import sys
from pathlib import Path

PROTECTED_PATTERNS = [
    "graph.json", "graph-*.json",
    "reverse_index.json", "changelog.jsonl", "querylog.jsonl",
]

BLOCK_MESSAGE = (
    "已拦截：图谱文件禁止直接编辑（这是图谱漂移的主要来源）。\n"
    "请改用 kg MCP 工具（唯一写入口，自带校验/changelog/反向索引重建）：\n"
    "  新增 entry     -> kg_add_entry\n"
    "  修改字段       -> kg_update_entry\n"
    "  加关联         -> kg_add_relation\n"
    "  加踩坑         -> kg_add_pitfall\n"
    "  draft->verified -> kg_verify_edge\n"
    "reverse_index.json / changelog.jsonl / querylog.jsonl 为自动生成/追加，不应手改。\n"
    "人工修复特殊情况可设 KG_ALLOW_DIRECT_EDIT=1 后重试。"
)


def main():
    try:
        if os.environ.get("KG_ALLOW_DIRECT_EDIT") == "1":
            return 0
        data = json.load(sys.stdin)
        file_path = (data.get("tool_input") or {}).get("file_path")
        if not file_path:
            return 0
        target = Path(file_path)
        if not target.is_absolute():
            target = Path(data.get("cwd") or os.getcwd()) / target
        name = target.name
        if not any(fnmatch.fnmatch(name, pat) for pat in PROTECTED_PATTERNS):
            return 0
        # 只拦图谱目录里的同名文件：所在目录必须存在 graph.json 主索引
        if not (target.parent / "graph.json").exists():
            return 0
        print(BLOCK_MESSAGE, file=sys.stderr)
        return 2  # exit 2 = 阻止工具调用，stderr 反馈给 AI
    except Exception:
        return 0  # fail-open


if __name__ == "__main__":
    sys.exit(main())
