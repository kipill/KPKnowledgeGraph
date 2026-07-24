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


# ==================== 跨工具入口（Codex / Cursor） ====================
#
# 图谱的「网关」是 MCP，本身工具无关：Claude Code / Codex / Cursor 都支持 MCP。
# 三者差异只在「配置文件位置/格式」和「触发约定的载体」：
#   Claude Code : .mcp.json(既有)            + .claude/skills(skill 自动激活)
#   Codex       : .codex/config.toml(TOML)   + AGENTS.md(每会话自动读)
#   Cursor      : .cursor/mcp.json(JSON)     + .cursor/rules/*.mdc(自动注入)
# MCP 调用命令三者完全一致：python -X utf8 <kg_rel>/tools/kg_mcp_server.py
# 全部「合并/不覆盖」语义，绝不动用户已有的其它 server / rule。

def register_mcp_cursor(target, kg_rel):
    """Cursor 项目级 MCP：.cursor/mcp.json，结构与 .mcp.json 相同（mcpServers.kg）。"""
    path = target / ".cursor" / "mcp.json"
    conf = read_json(path, {})
    servers = conf.setdefault("mcpServers", {})
    if "kg" in servers:
        print("[跳过] .cursor/mcp.json 已有 kg server（不覆盖）")
        return
    servers["kg"] = {"command": "python",
                     "args": ["-X", "utf8", "%s/tools/kg_mcp_server.py" % kg_rel]}
    write_json(path, conf)
    print("[注册] .cursor/mcp.json → kg MCP server（Cursor）")


def register_mcp_codex(target, kg_rel):
    """Codex 项目级 MCP：.codex/config.toml 追加 [mcp_servers.kg] 表。
    幂等靠文本标记检测（不引入 TOML 写库，守零依赖）。trust 交给 Codex 首次提示，
    不代写 trust_level（其 semantics 因版本/全局配置而异，误写反而有害）。"""
    path = target / ".codex" / "config.toml"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "[mcp_servers.kg]" in existing:
        print("[跳过] .codex/config.toml 已有 [mcp_servers.kg]（不覆盖）")
        return
    block = (
        "\n[mcp_servers.kg]\n"
        'command = "python"\n'
        'args = ["-X", "utf8", "%s/tools/kg_mcp_server.py"]\n' % kg_rel
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing + block, encoding="utf-8")
    print("[注册] .codex/config.toml → [mcp_servers.kg]（Codex）")
    print("       ⚠ Codex 首次在本项目会提示信任(trust)才加载项目级 MCP，按提示确认即可。")


def _merge_agents_md(target, dist_dir, kg_rel):
    """把 templates/AGENTS.kg.md 合并进项目根 AGENTS.md（Codex 触发约定载体）。
    用 <!-- KG:BEGIN --> / <!-- KG:END --> 标记整段管理：已存在则整段替换（升级），
    不存在则追加到文件末尾；无 AGENTS.md 则新建。绝不动标记外的用户内容。"""
    src = dist_dir / "templates" / "AGENTS.kg.md"
    if not src.exists():
        return
    section = src.read_text(encoding="utf-8").replace(".claude/kg", kg_rel).rstrip() + "\n"
    path = target / "AGENTS.md"
    begin, end = "<!-- KG:BEGIN", "<!-- KG:END -->"
    if not path.exists():
        path.write_text(section, encoding="utf-8")
        print("[创建] AGENTS.md（kg 触发约定，Codex 用）")
        return
    cur = path.read_text(encoding="utf-8")
    if begin in cur and end in cur:
        head = cur[: cur.index(begin)]
        tail = cur[cur.index(end) + len(end):]
        path.write_text(head + section.rstrip("\n") + tail, encoding="utf-8")
        print("[更新] AGENTS.md → kg 约定段（整段替换）")
    else:
        sep = "" if cur.endswith("\n\n") else ("\n" if cur.endswith("\n") else "\n\n")
        path.write_text(cur + sep + section, encoding="utf-8")
        print("[追加] AGENTS.md → kg 触发约定段（保留原有内容）")


def deploy_cross_tool(target, dist_dir, kg_rel):
    """铺跨工具入口：Codex/Cursor 的 MCP 配置 + 触发约定文件。
    全部「合并/不覆盖 + 幂等」：MCP 配置已存在则跳过（绝不覆盖用户配置），
    触发约定文件（AGENTS.md 段 / cursor rules）是生成物，按标记整段替换/覆盖。
    因此首次安装与 kg_admin update「补缺失」共用同一逻辑——update 调用时只会
    补上尚不存在的配置，不动任何已有项。"""
    register_mcp_cursor(target, kg_rel)
    register_mcp_codex(target, kg_rel)
    _merge_agents_md(target, dist_dir, kg_rel)
    # Codex skill：.agents/skills/<name>/SKILL.md（Codex 认 SKILL.md 开放标准，按需自动加载）。
    # 与 Claude Code 的 skill 同源（skills/*.skill.md），Codex 从 cwd 向上扫 .agents/skills 到 repo 根。
    # 实测（Codex 0.144.6）：.agents/skills 与 .codex/skills 都会扫，两处都放会重复加载，只铺前者。
    for skill_src in sorted((dist_dir / "skills").glob("*.skill.md")):
        name = skill_src.name[: -len(".skill.md")]
        skill_dst = target / ".agents" / "skills" / name / "SKILL.md"
        skill_dst.parent.mkdir(parents=True, exist_ok=True)
        _write_text(skill_dst, skill_src, kg_rel)
        print("[部署] .agents/skills/%s/SKILL.md（Codex 触发约定）" % name)
    # Cursor 规则：.cursor/rules/kg.mdc（生成物，升级覆盖）
    rule_src = dist_dir / "templates" / "cursor-kg.mdc"
    if rule_src.exists():
        rule_dst = target / ".cursor" / "rules" / "kg.mdc"
        rule_dst.parent.mkdir(parents=True, exist_ok=True)
        rule_dst.write_text(
            rule_src.read_text(encoding="utf-8").replace(".claude/kg", kg_rel),
            encoding="utf-8")
        print("[部署] .cursor/rules/kg.mdc（Cursor 触发约定）")


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

    # 部署所有 skills/*.skill.md → .claude/skills/<name>/SKILL.md
    for skill_src in sorted((dist_dir / "skills").glob("*.skill.md")):
        name = skill_src.name[: -len(".skill.md")]
        skill_dst = target / ".claude" / "skills" / name / "SKILL.md"
        if overwrite_skill_cmd:
            skill_dst.parent.mkdir(parents=True, exist_ok=True)
            _write_text(skill_dst, skill_src, kg_rel)
            print("[更新] .claude/skills/%s/SKILL.md" % name)
        elif not skill_dst.exists():
            skill_dst.parent.mkdir(parents=True, exist_ok=True)
            _write_text(skill_dst, skill_src, kg_rel)
            print("[创建] .claude/skills/%s/SKILL.md" % name)
        else:
            print("[跳过] .claude/skills/%s/SKILL.md 已存在（首次安装不覆盖）" % name)

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


def _hook_refers_guard(h):
    """PreToolUse[].hooks[] 里的一项是否指向 kg_guard_hook.py（兼容 shell 形式与 exec 形式）。"""
    if "kg_guard_hook" in h.get("command", ""):
        return True
    return any("kg_guard_hook" in str(a) for a in (h.get("args") or []))


def _hook_is_canonical(h):
    """已是最新 exec 形式：command=python，args 含 ${CLAUDE_PROJECT_DIR}.../kg_guard_hook.py。"""
    if h.get("command") != "python":
        return False
    return any("CLAUDE_PROJECT_DIR" in str(a) and "kg_guard_hook" in str(a)
               for a in (h.get("args") or []))


def ensure_guard_hook(settings, kg_rel):
    """把 kg_guard_hook 注册成最新形式；幂等。
    返回 'register'（新装）/ 'upgrade'（旧相对路径形式原地升级）/ 'skip'（已是最新）。

    早期版本注册成 shell 形式相对路径 `python -X utf8 .claude/kg/tools/kg_guard_hook.py`，
    会随会话 cwd 解析：cd 进子目录后 hook 找不到脚本，Python 退出码非 0 被 Claude Code 当作拦截，
    脚本内部的 fail-open 根本没机会跑。改用 exec 形式 + ${CLAUDE_PROJECT_DIR}：
    Claude Code 自己把占位符替换成项目根绝对路径再 spawn，不依赖任何 shell 变量展开，
    Windows（PowerShell/Git Bash）与 Unix 通用，且锚定项目根、不受 cd 影响。
    """
    hook = {
        "type": "command",
        "command": "python",
        "args": ["-X", "utf8",
                 "${CLAUDE_PROJECT_DIR}/%s/tools/kg_guard_hook.py" % kg_rel],
        "timeout": 10,
    }
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for matcher in pre:
        for h in matcher.get("hooks", []):
            if _hook_refers_guard(h):
                if _hook_is_canonical(h):
                    return "skip"
                h.clear()
                h.update(hook)
                return "upgrade"
    pre.append({"matcher": "Edit|Write", "hooks": [hook]})
    return "register"


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
        # 补齐跨工具入口（Codex/Cursor）：只补缺失，已有配置一律跳过、绝不覆盖
        deploy_cross_tool(target, DIST, kg_rel)
        print()
        print("工具层已更新到 %s" % read_version(DIST))
        print("未改动：graph*.json / entries/ / 日志 / .mcp.json / settings.json"
              " / 已存在的 .codex、.cursor MCP 配置")
        print("重启会话使新工具生效（Claude / Codex / Cursor）。")
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

    # 注册防漂移 hook（合并 settings.json；幂等，旧相对路径形式自动升级）
    settings_path = target / ".claude" / "settings.json"
    settings = read_json(settings_path, {})
    action = ensure_guard_hook(settings, kg_rel)
    if action == "register":
        write_json(settings_path, settings)
        print("[注册] .claude/settings.json → PreToolUse 拦截直接编辑图谱"
              "（${CLAUDE_PROJECT_DIR} 锚定项目根，子目录下也生效）")
    elif action == "upgrade":
        write_json(settings_path, settings)
        print("[更新] .claude/settings.json → kg_guard_hook 改用 ${CLAUDE_PROJECT_DIR} 锚定"
              "（修复 cd 进子目录后 hook 找不到脚本的崩溃）")
    else:
        print("[跳过] settings.json 已有 kg_guard_hook（已是最新形式）")

    # 跨工具入口：Codex（.codex/config.toml + AGENTS.md）+ Cursor（.cursor/mcp.json + rules）
    deploy_cross_tool(target, DIST, kg_rel)

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
    print()
    print("其它 AI 工具（同一套 MCP + 触发约定，已一并铺好）:")
    print("  · Codex  : 重启后读 .codex/config.toml 载入 kg MCP；")
    print("             .agents/skills/kg-consult/SKILL.md（按需自动加载）+ AGENTS.md 指针")
    print("             （首次会提示信任本项目才加载项目级 MCP，按提示确认）")
    print("  · Cursor : 重启后读 .cursor/mcp.json 载入 kg MCP；.cursor/rules/kg.mdc 已含约定")
    print("  注意:Codex/Cursor 无 PreToolUse hook，防直接改图谱靠 AGENTS/rules 约定自律。")


if __name__ == "__main__":
    main()
