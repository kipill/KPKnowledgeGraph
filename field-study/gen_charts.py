#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实地观测折线图生成器（纯标准库，零依赖）。

从 snapshots.jsonl 读各期数据，按**真实采样日期**为 X 轴（间距反映实际时间差，
诚实呈现采样节奏，不是等距排列）生成两张 SVG：
  usage.svg   —— 使用强度：累计查询 + 总命中（计数，Y 轴从 0 起）
  quality.svg —— 质量：反馈准确率 + entry 覆盖率（百分比，Y 轴 0-100）

用法： python gen_charts.py            # 生成到 field-study/ 目录
每加一期快照后重跑本脚本，README 引用的图即更新（与 field-study「一条命令复现」一致）。
SVG 用 prefers-color-scheme 适配 GitHub 明/暗主题；系列色固定、两主题都清晰。
"""

import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAP = HERE / "snapshots.jsonl"

# 系列色：色盲友好、明暗底都醒目
BLUE = "#3b82f6"
AMBER = "#f59e0b"

W, H = 680, 320
ML, MR, MT, MB = 56, 108, 44, 52   # 右留白给行末标签
PW, PH = W - ML - MR, H - MT - MB


def load():
    rows = [json.loads(l) for l in SNAP.read_text("utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: r["date"])
    return rows


def _days(rows):
    d0 = date.fromisoformat(rows[0]["date"])
    return [(date.fromisoformat(r["date"]) - d0).days for r in rows]


def _nice_ceiling(v):
    """把最大值向上取到「好看」的刻度上限。"""
    if v <= 10:
        return 10
    step = 10 ** (len(str(int(v))) - 1)
    return int((v // step + 1) * step)


def _style():
    # 关键颜色全部内联到元素属性（GitHub 一定保留），<style> 只做暗色主题覆盖——
    # 万一 sanitizer 剥了 <style>，也只是回退到内联的浅色值，图仍完全可读。
    return (
        "<style>"
        "@media (prefers-color-scheme:dark){"
        ".gridln{stroke:#30363d}.axisln{stroke:#6e7681}.lbl{fill:#8b949e}}"
        "</style>"
    )


def gen_chart(rows, series, title, y_max, y_fmt, out_name):
    """series: [(label, key_path, color, value_fmt, scale)]，key_path 用 . 分隔取
    summary/derived；scale 把原始值换算到绘图量纲（如 accuracy 0-1 → 0-100 传 100，
    已是百分数的覆盖率传 1）。value_fmt 收原始值格式化显示。"""
    days = _days(rows)
    dmax = max(days) or 1

    def sx(d):
        return ML + (d / dmax) * PW

    def sy(v):
        return MT + PH - (v / y_max) * PH

    # font-family 内联在根 <g>；文字颜色内联浅色 + class="lbl"（暗色由 <style> 覆盖）
    GRID, AXIS, LBL = "#d0d7de", "#8b949e", "#57606a"
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" role="img" aria-label="{title}">',
         _style(),
         '<g font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">']
    s.append(f'<text class="lbl" fill="{LBL}" x="{ML}" y="24" font-size="15" '
             f'font-weight="600">{title}</text>')

    # 横向网格 + Y 轴刻度（5 档）
    for i in range(6):
        v = y_max * i / 5
        y = sy(v)
        s.append(f'<line class="gridln" stroke="{GRID}" stroke-width="1" '
                 f'x1="{ML}" y1="{y:.1f}" x2="{ML+PW}" y2="{y:.1f}"/>')
        s.append(f'<text class="lbl" fill="{LBL}" x="{ML-8}" y="{y+4:.1f}" '
                 f'font-size="11" text-anchor="end">{y_fmt(v)}</text>')

    # X 轴基线
    s.append(f'<line class="axisln" stroke="{AXIS}" stroke-width="1.5" '
             f'x1="{ML}" y1="{MT+PH}" x2="{ML+PW}" y2="{MT+PH}"/>')

    # X 轴：真实日期 + 期号（间距按实际天数）
    for r, d in zip(rows, days):
        x = sx(d)
        s.append(f'<line class="gridln" stroke="{GRID}" stroke-width="1" '
                 f'x1="{x:.1f}" y1="{MT+PH}" x2="{x:.1f}" y2="{MT+PH+5}"/>')
        s.append(f'<text class="lbl" fill="{LBL}" x="{x:.1f}" y="{MT+PH+20}" '
                 f'font-size="11" text-anchor="middle">{r["date"][5:]}</text>')
        s.append(f'<text class="lbl" fill="{LBL}" x="{x:.1f}" y="{MT+PH+35}" '
                 f'font-size="9.5" text-anchor="middle" opacity="0.7">{r["id"]}</text>')

    # 各系列折线 + 数据点 + 数值标签 + 行末系列名
    for label, path, color, vfmt, scale in series:
        keys = path.split(".")
        vals = []
        for r in rows:
            node = r
            for k in keys:
                node = node[k]
            vals.append(node)
        # vals 保留原始值用于标签；绘图坐标用 scale 换算到 y_max 量纲
        pts = [(sx(d), sy(v * scale)) for d, v in zip(days, vals)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        s.append(f'<polyline points="{poly}" fill="none" stroke="{color}" '
                 f'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for (x, y), v in zip(pts, vals):
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>')
            s.append(f'<text x="{x:.1f}" y="{y-9:.1f}" font-size="11" font-weight="600" '
                     f'text-anchor="middle" fill="{color}">{vfmt(v)}</text>')
        ex, ey = pts[-1]
        s.append(f'<text x="{ex+10:.1f}" y="{ey+4:.1f}" font-size="12" font-weight="600" '
                 f'fill="{color}">{label}</text>')

    s.append("</g></svg>")
    (HERE / out_name).write_text("\n".join(s), encoding="utf-8")
    print("已生成:", HERE / out_name)


def main():
    rows = load()
    n = len(rows)

    hits_max = _nice_ceiling(max(r["summary"]["total_hits"] for r in rows))
    gen_chart(
        rows,
        [("总命中", "summary.total_hits", AMBER, lambda v: f"{int(v)}", 1),
         ("累计查询", "summary.total_queries", BLUE, lambda v: f"{int(v)}", 1)],
        "使用强度（沿采样时间轴）",
        hits_max, lambda v: f"{int(v)}", "usage.svg")

    gen_chart(
        rows,
        [("准确率", "summary.accuracy", BLUE, lambda v: f"{v*100:.0f}%", 100),
         ("覆盖率", "derived.coverage_pct", AMBER, lambda v: f"{v:.0f}%", 1)],
        "质量指标（沿采样时间轴）",
        100, lambda v: f"{int(v)}%", "quality.svg")

    print(f"共 {n} 期快照。")


if __name__ == "__main__":
    main()
