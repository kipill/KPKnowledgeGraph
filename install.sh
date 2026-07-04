#!/usr/bin/env bash
# 知识图谱系统一键安装脚本（bash 薄封装，逻辑在 install.py）
#
# 用法:
#   ./install.sh                            # 安装到当前目录
#   ./install.sh /path/to/project           # 安装到指定项目
#   ./install.sh /path/to/project --kg-dir .claude/kg
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "错误: 需要 Python 3（工具脚本运行时依赖），请先安装" >&2
  exit 1
fi
exec "$PY" -X utf8 "$SCRIPT_DIR/install.py" "$@"
