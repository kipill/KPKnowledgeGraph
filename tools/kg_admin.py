#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_admin — 已安装项目的知识图谱自管理（类似 `claude update`）

子命令:
  version            打印本地已装版本
  check              对比本地版本与发行仓库最新 tag，报告有无更新
  update             拉取最新版本，就地升级工具层（绝不碰图谱数据）
  config [--repo X]  设置/查看发行仓库地址

需要 git 可用。发行仓库地址来自（优先级）:
  命令行 --repo > 环境变量 KG_DIST_REPO > .claude/kg/SOURCE（install --repo 写入）

升级安全边界——update 只覆盖: tools/*.py、skills/kg-consult/SKILL.md、
commands/kg-init.md、templates/*、VERSION。
绝不碰: graph*.json、entries/、changelog/querylog/reverse_index、.mcp.json、settings.json。
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

KG = Path(__file__).resolve().parent.parent            # .claude/kg
try:
    TARGET = KG.parents[1]                              # 项目根
    KG_REL = str(KG.relative_to(TARGET)).replace("\\", "/")
except IndexError:
    TARGET = KG.parent
    KG_REL = "."
VERSION_FILE = KG / "VERSION"
SOURCE_FILE = KG / "SOURCE"


def semver(v):
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def display(v):
    s = semver(v)
    return "%d.%d.%d" % s if s != (0, 0, 0) else str(v)


def fail(msg, code=1):
    print(msg)
    sys.exit(code)


def local_version():
    return VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else None


def source_url(cli_repo=None):
    url = cli_repo or os.environ.get("KG_DIST_REPO")
    if url:
        return url.strip()
    if SOURCE_FILE.exists():
        return SOURCE_FILE.read_text(encoding="utf-8").strip()
    return None


def _need_git():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        fail("错误: 需要 git（用于查询/拉取发行仓库版本）。请先安装 git。")


def latest_tag(url):
    """git ls-remote --tags 查询，无需 clone、无需认证。返回 (最新tag原始值, 全部tag列表)。"""
    r = subprocess.run(["git", "ls-remote", "--tags", url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail("无法访问发行仓库 %s:\n%s" % (url, r.stderr.strip()))
    tags = []
    for line in r.stdout.splitlines():
        m = re.search(r"refs/tags/(v?\d+\.\d+\.\d+)$", line)
        if m:
            tags.append(m.group(1))
    tags.sort(key=semver, reverse=True)
    return (tags[0] if tags else None), tags


def cmd_version(args):
    v = local_version()
    print("已装版本: %s" % (display(v) if v else "未知（可能为旧版安装，无 VERSION 文件）"))
    url = source_url(args.repo)
    print("发行仓库: %s" % (url or "（未配置，用 config --repo <url> 设置）"))


def cmd_check(args):
    _need_git()
    url = source_url(args.repo)
    if not url:
        fail("未配置发行仓库地址。用 'config --repo <git_url>' 设置，或设环境变量 KG_DIST_REPO。")
    cur = local_version()
    latest, tags = latest_tag(url)
    if not latest:
        fail("发行仓库 %s 没有版本 tag（需维护者打 vMAJOR.MINOR.PATCH tag）。" % url)
    print("本地版本: %s" % (display(cur) if cur else "未知"))
    print("最新版本: %s" % display(latest))
    if not cur or semver(cur) < semver(latest):
        print()
        print("→ 有新版本可用。升级: python %s update" % Path(sys.argv[0]).name)
    else:
        print()
        print("→ 已是最新。")


def cmd_update(args):
    _need_git()
    url = source_url(args.repo)
    if not url:
        fail("未配置发行仓库地址。用 'config --repo <git_url>' 设置。")
    cur = local_version()
    latest, _ = latest_tag(url)
    if not latest:
        fail("发行仓库 %s 没有版本 tag。" % url)
    if cur and semver(cur) >= semver(latest) and not args.force:
        print("已是最新版本: %s（用 --force 强制重装工具层）" % display(cur))
        return
    print("升级 %s → %s（来源: %s）" % (display(cur) if cur else "未知", display(latest), url))

    import tempfile
    with tempfile.TemporaryDirectory(prefix="kg_upgrade_") as td:
        clone_dir = Path(td) / "dist"
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", "--branch", latest, url, str(clone_dir)])
        if r.returncode != 0:
            fail("clone 失败（见上方 git 输出）")
        install = clone_dir / "install.py"
        if not install.exists():
            fail("发行仓库根缺少 install.py（仓库根应等于 dist 内容：install.py / tools/ / skills/ 等在根目录）")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        rr = subprocess.run(
            [sys.executable, "-X", "utf8", str(install), str(TARGET),
             "--kg-dir", KG_REL, "--refresh-tools"], env=env)
        if rr.returncode != 0:
            fail("工具层升级失败（见上方输出）")

    print()
    print("升级完成，当前版本: %s" % local_version())
    print("重启 Claude Code 会话使新工具生效。")


def cmd_config(args):
    if args.repo:
        SOURCE_FILE.write_text(args.repo.strip() + "\n", encoding="utf-8")
        print("已设置发行仓库: %s" % args.repo.strip())
    else:
        url = source_url()
        print("发行仓库: %s" % (url or "（未设置）"))
        print("设置: python %s config --repo <git_url>" % Path(sys.argv[0]).name)


def main():
    parser = argparse.ArgumentParser(description="知识图谱自管理（version/check/update/config）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_version = sub.add_parser("version", help="打印本地版本")
    p_version.add_argument("--repo", default=None, help="发行仓库 git URL（覆盖 SOURCE）")
    p_check = sub.add_parser("check", help="检查是否有新版本")
    p_check.add_argument("--repo", default=None, help="发行仓库 git URL（覆盖 SOURCE）")
    p_update = sub.add_parser("update", help="拉取最新版本升级工具层")
    p_update.add_argument("--repo", default=None, help="发行仓库 git URL（覆盖 SOURCE）")
    p_update.add_argument("--force", action="store_true", help="即使已是最新也重装工具层")
    p_config = sub.add_parser("config", help="设置/查看发行仓库地址")
    p_config.add_argument("--repo", default=None, help="发行仓库 git URL")
    args = parser.parse_args()
    {"version": cmd_version, "check": cmd_check,
     "update": cmd_update, "config": cmd_config}[args.cmd](args)


if __name__ == "__main__":
    main()
