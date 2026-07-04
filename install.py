#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识图谱系统安装器（跨平台，纯标准库）

把本发行包安装到目标项目，并注册 MCP server 和防漂移 hook。
也供 kg_admin.py update 调用做工具层升级（--refresh-tools）。

  <项目>/<kg-dir>/                 图谱目录（默认 .claude/kg）
    ├── graph.json                 主索引（首次创建，升级时不覆盖）
    ├── VERSION                    已装版本（来自发行包 VERSION）
    ├── SOURCE                     发行仓库 git URL（供 kg_admin update 用）
    ├── entries/                   MD 深度文档目录（用户数据，升级时不覆盖）
    ├── tools/                     kg_core / kg_mcp_server / validate 等（覆盖到最新）
    └── templates/                 模板参考（覆盖到最新）
  <项目>/.claude/skills/kg-consult/SKILL.md   查询 skill
  <项目>/.claude/commands/kg-init.md          /kg-init 命令
  <项目>/.mcp.json                            注册 kg MCP server（合并）
  <项目>/.claude/settings.json                注册 PreToolUse hook（合并）

用法:
  python install.py                            # 安装到当前目录
  python install.py /path/to/project
  python install.py /path/to/project --kg-dir .claude/kg
  python install.py /path/to/project --repo <git_url>   # 记录发行仓库供升级用
  python install.py /path/to/project --refresh-tools    # 仅升级工具层（kg_admin update 内部调用）
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DIST = Path(__file__).resolve().parent


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("[错误] %s 不是合法 JSON，请先修复再重跑" % path)
        sys.exit(1)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_version(dist_dir):
    v = dist_dir / "VERSION"
    return v.read_text(encoding="utf-8").strip() if v.exists() else "未知"


def _write_text(dst, src, kg_rel):
    dst.write_text(src.read_text(encoding="utf-8").replace(".claude/kg", kg_rel), encoding="utf-8")


def deploy_tools(dist_dir, target, kg_rel, overwrite_skill_cmd):
    """覆盖工具层：tools/*.py + templates/ + skill + command + VERSION。
    overwrite_skill_cmd=False 时 skill/command 首次安装（已存在则跳过）；
    =True 时强制覆盖（升级语义）。绝不碰 graph.json/entries/日志/配置。"""
    kg_abs = target / kg_rel
    (kg_abs / "tools").mkdir(parents=True, exist_ok=True)
    (kg_abs / "templates").mkdir(exist_ok=True)

    n = 0
    for f in sorted((dist_dir / "tools").glob("*.py")):
        shutil.copy(f, kg_abs / "tools" / f.name)
        n += 1
    print("[更新] %s/tools/*.py（%d 个脚本）" % (kg_rel, n))

    for f in sorted((dist_dir / "templates").iterdir()):
        if f.is_file():
            shutil.copy(f, kg_abs / "templates" / f.name)
    print("[更新] %s/templates/" % kg_rel)

    # 可视化用的前端库（cytoscape），随工具层一起部署/升级
    vendor_src = dist_dir / "tools" / "vendor"
    if vendor_src.is_dir():
        vendor_dst = kg_abs / "tools" / "vendor"
        vendor_dst.mkdir(parents=True, exist_ok=True)
        m = 0
        for f in sorted(vendor_src.iterdir()):
            if f.is_file():
                shutil.copy(f, vendor_dst / f.name)
                m += 1
        print("[更新] %s/tools/vendor/（%d 个文件）" % (kg_rel, m))

    skill_dst = target / ".claude" / "skills" / "kg-consult" / "SKILL.md"
    skill_src = dist_dir / "skills" / "kg-consult.skill.md"
    if skill_src.exists():
        if overwrite_skill_cmd:
            skill_dst.parent.mkdir(parents=True, exist_ok=True)
            _write_text(skill_dst, skill_src, kg_rel)
            print("[更新] .claude/skills/kg-consult/SKILL.md")
        elif not skill_dst.exists():
            skill_dst.parent.mkdir(parents=True, exist_ok=True)
            _write_text(skill_dst, skill_src, kg_rel)
            print("[创建] .claude/skills/kg-consult/SKILL.md")
        else:
            print("[跳过] .claude/skills/kg-consult/SKILL.md 已存在（首次安装不覆盖）")

    cmd_dst = target / ".claude" / "commands" / "kg-init.md"
    cmd_src = dist_dir / "kg-init.md"
    if cmd_src.exists():
        if overwrite_skill_cmd:
            cmd_dst.parent.mkdir(parents=True, exist_ok=True)
            _write_text(cmd_dst, cmd_src, kg_rel)
            print("[更新] .claude/commands/kg-init.md")
        elif not cmd_dst.exists():
            cmd_dst.parent.mkdir(parents=True, exist_ok=True)
            _write_text(cmd_dst, cmd_src, kg_rel)
            print("[创建] .claude/commands/kg-init.md")
        else:
            print("[跳过] .claude/commands/kg-init.md 已存在")

    (kg_abs / "VERSION").write_text(read_version(dist_dir) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="安装/升级知识图谱系统")
    parser.add_argument("target", nargs="?", default=".", help="目标项目根（默认当前目录）")
    parser.add_argument("--kg-dir", default=".claude/kg", help="图谱目录（项目根相对路径）")
    parser.add_argument("--repo", default=None,
                        help="发行仓库 git URL，写入 SOURCE 供 kg_admin update 使用")
    parser.add_argument("--refresh-tools", action="store_true",
                        help="仅升级工具层（kg_admin update 内部调用；不动 graph 数据/entries/日志/.mcp.json/settings.json）")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    kg_rel = args.kg_dir.replace("\\", "/").rstrip("/")
    kg_abs = target / kg_rel

    # ---- 升级模式：只换工具层 ----
    if args.refresh_tools:
        if not (kg_abs / "graph.json").exists():
            print("[错误] %s 不是已安装的 kg 目录（无 graph.json）" % kg_abs)
            sys.exit(1)
        print("升级工具层: %s" % target)
        deploy_tools(DIST, target, kg_rel, overwrite_skill_cmd=True)
        print()
        print("工具层已更新到 %s" % read_version(DIST))
        print("未改动：graph*.json / entries/ / 日志 / .mcp.json / settings.json")
        print("重启 Claude Code 会话使新工具生效。")
        return

    # ---- 首次安装 ----
    print("目标项目: %s" % target)
    print("图谱目录: %s" % kg_rel)
    print()

    (kg_abs / "entries").mkdir(parents=True, exist_ok=True)
    gitkeep = kg_abs / "entries" / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    if (kg_abs / "graph.json").exists():
        print("[跳过] %s/graph.json 已存在（不覆盖用户数据）" % kg_rel)
    else:
        shutil.copy(DIST / "templates" / "graph.empty.json", kg_abs / "graph.json")
        print("[创建] %s/graph.json（空主索引，跑 /kg-init 初始化）" % kg_rel)

    deploy_tools(DIST, target, kg_rel, overwrite_skill_cmd=False)

    # 注册 MCP server（合并 .mcp.json）
    mcp_path = target / ".mcp.json"
    mcp = read_json(mcp_path, {})
    servers = mcp.setdefault("mcpServers", {})
    if "kg" in servers:
        print("[跳过] .mcp.json 已有 kg server（不覆盖）")
    else:
        servers["kg"] = {"command": "python",
                         "args": ["-X", "utf8", "%s/tools/kg_mcp_server.py" % kg_rel]}
        write_json(mcp_path, mcp)
        print("[注册] .mcp.json → kg MCP server")

    # 注册防漂移 hook（合并 settings.json）
    settings_path = target / ".claude" / "settings.json"
    settings = read_json(settings_path, {})
    hook_cmd = "python -X utf8 %s/tools/kg_guard_hook.py" % kg_rel
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    already = any("kg_guard_hook" in h.get("command", "")
                  for m in pre for h in m.get("hooks", []))
    if already:
        print("[跳过] settings.json 已有 kg_guard_hook（不覆盖）")
    else:
        pre.append({"matcher": "Edit|Write",
                    "hooks": [{"type": "command", "command": hook_cmd, "timeout": 10}]})
        write_json(settings_path, settings)
        print("[注册] .claude/settings.json → PreToolUse 拦截直接编辑图谱")

    # 记录发行仓库地址（供 kg_admin update）
    repo = args.repo or os.environ.get("KG_DIST_REPO")
    if repo:
        (kg_abs / "SOURCE").write_text(repo.strip() + "\n", encoding="utf-8")
        print("[记录] 发行仓库: %s（kg_admin update 将从此拉取升级）" % repo.strip())
    else:
        print("[提示] 未指定 --repo：kg_admin update 无法自动升级。")
        print("       补录: python %s/tools/kg_admin.py config --repo <git_url>" % kg_rel)

    print()
    print("=" * 60)
    print("安装完成（版本 %s）。" % read_version(DIST))
    print()
    print("下一步（Claude Code）:")
    print("  1. 重启 Claude Code 会话使 .mcp.json 生效")
    print("  2. 新项目跑 /kg-init 初始化图谱骨架")
    print("  3. 校验:  python %s/tools/validate.py" % kg_rel)
    print("  4. 检查更新: python %s/tools/kg_admin.py check" % kg_rel)


if __name__ == "__main__":
    main()
