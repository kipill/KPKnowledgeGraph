#!/usr/bin/env python3
"""
知识图谱可视化生成器

读取所有 graph-*.json，生成可在浏览器本地打开的 HTML 可视化。
需要网络连接（加载 Cytoscape.js CDN）。

用法:
  python gen_graph_html.py
  python gen_graph_html.py --root <project_root>
  python gen_graph_html.py --output <path>
"""

import json
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, resolve_kg_dir, KGError  # noqa: E402

# 域颜色按域名排序循环分配，保证任意项目的域都有区分度
PALETTE = [
    "#e74c3c", "#e67e22", "#2ecc71", "#3498db", "#f1c40f",
    "#9b59b6", "#95a5a6", "#1abc9c", "#e84393", "#718096",
]

# ==================== 数据加载 ====================

def load_data(kg_dir: Path, per_stats=None) -> dict:
    per_stats = per_stats or {}
    main_graph = json.loads((kg_dir / "graph.json").read_text("utf-8"))

    nodes, edges, seen_edges = [], [], set()
    domains_info = {}

    for idx, domain_path in enumerate(sorted(kg_dir.glob("graph-*.json"))):
        domain_graph = json.loads(domain_path.read_text("utf-8"))
        domain = domain_path.stem.replace("graph-", "")
        color = PALETTE[idx % len(PALETTE)]
        desc = main_graph.get("domains", {}).get(domain, {}).get("desc", "")

        entries = domain_graph.get("entries", {})
        if domain not in domains_info:
            domains_info[domain] = {"color": color, "count": 0, "desc": desc}

        for entry_id, entry in entries.items():
            if entry_id.startswith("_"):
                continue
            domains_info[domain]["count"] += 1
            nodes.append({
                "id": entry_id,
                "name_cn": entry.get("name_cn", entry_id),
                "domain": domain,
                "color": color,
                "type": entry.get("type", "system"),
                "summary": entry.get("summary", ""),
                "pitfalls": entry.get("persistence_pitfalls", []),
                "stats": {
                    "hits": per_stats.get(entry_id, {}).get("query_hits", 0),
                    "acc": per_stats.get(entry_id, {}).get("accurate", 0),
                    "bad": per_stats.get(entry_id, {}).get("inaccurate", 0),
                    "change_count": per_stats.get(entry_id, {}).get("change_count", 0),
                    "changes": per_stats.get(entry_id, {}).get("changes", []),
                },
                "code": entry.get("code", {}),
            })

            for rel in entry.get("related", []):
                target = rel.get("to")
                if not target:
                    continue
                eid = f"{entry_id}>{target}"
                if eid in seen_edges:
                    continue
                seen_edges.add(eid)
                conf = rel.get("confidence", "draft")
                edges.append({
                    "id": eid,
                    "source": entry_id,
                    "target": target,
                    "context": rel.get("context", ""),
                    "confidence": conf,
                    "edgeColor": "#2ea043" if conf == "verified" else "#d29922",
                    "lineStyle": "solid" if conf == "verified" else "dashed",
                })

    # ── 计算网格位置（按域分行，域内节点水平排列）──
    H_STEP = 160   # 节点中心水平间距
    V_STEP = 110   # 节点中心垂直间距

    domain_order = list(dict.fromkeys(n["domain"] for n in nodes))
    nodes_by_domain = {d: [n["id"] for n in nodes if n["domain"] == d] for d in domain_order}
    max_cols = max((len(v) for v in nodes_by_domain.values()), default=0)

    pos_map = {}
    for row_i, domain in enumerate(domain_order):
        cols = nodes_by_domain[domain]
        row_w = (len(cols) - 1) * H_STEP
        max_w = (max_cols - 1) * H_STEP
        x_off = (max_w - row_w) / 2          # 行居中对齐
        for col_i, nid in enumerate(cols):
            pos_map[nid] = {"x": x_off + col_i * H_STEP, "y": row_i * V_STEP}

    for node in nodes:
        node["pos"] = pos_map[node["id"]]

    return {"nodes": nodes, "edges": edges, "domains": domains_info}


# ==================== HTML 模板 ====================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>知识图谱 · __PROJECT__</title>
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#0d1117;color:#c9d1d9;height:100vh;display:flex;flex-direction:column;overflow:hidden}
#hdr{padding:8px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:12px;flex-shrink:0}
#hdr h1{font-size:16px;color:#58a6ff;font-weight:700}
.sub{font-size:12px;color:#8b949e}
.hbtn{padding:4px 12px;background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;cursor:pointer;font-size:12px}
.hbtn:hover{background:#30363d}
#main{display:flex;flex:1;overflow:hidden}
#sb{width:252px;background:#161b22;border-right:1px solid #30363d;display:flex;flex-direction:column;overflow:hidden;flex-shrink:0}
#sb-top{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:14px}
#cy-wrap{flex:1;background:#0d1117}
#cy{width:100%;height:100%}
.st{font-size:11px;font-weight:700;color:#8b949e;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px}
.dbtn{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:6px;border:1px solid transparent;cursor:pointer;font-size:12px;background:transparent;color:#c9d1d9;transition:all .15s;width:100%;text-align:left}
.dbtn:hover{background:#21262d}
.dbtn.on{background:#21262d;border-color:var(--dc)}
.ddot{width:8px;height:8px;border-radius:50%;background:var(--dc);flex-shrink:0}
.dname{flex:1}
.dcnt{font-size:11px;color:#8b949e;background:#21262d;padding:1px 6px;border-radius:10px}
.lr{display:flex;align-items:center;gap:8px;font-size:12px;color:#8b949e;margin:3px 0}
.lv{width:24px;height:2px;background:#2ea043}
.ld{width:24px;height:0;border-top:2px dashed #d29922}
#det-hdr{padding:8px 12px;border-top:1px solid #30363d;border-bottom:1px solid #30363d;font-size:11px;color:#8b949e;background:#161b22;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
#det{flex:1;padding:10px 12px;overflow-y:auto;min-height:180px;max-height:360px}
#det .emp{color:#8b949e;font-size:13px;text-align:center;padding:30px 0}
.dn{font-size:15px;font-weight:700;margin-bottom:2px}
.dm{font-size:11px;color:#8b949e;margin-bottom:8px}
.ds{font-size:12px;color:#c9d1d9;line-height:1.5;margin-bottom:10px;padding:8px;background:#0d1117;border-radius:6px;border:1px solid #21262d}
.dsec{font-size:11px;font-weight:700;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin:8px 0 4px}
.pit{border-left:3px solid #da3633;padding:5px 8px;margin:3px 0;font-size:12px;line-height:1.4;background:#161b22;border-radius:0 4px 4px 0}
.ci{font-size:11px;color:#58a6ff;padding:2px 0;font-family:monospace;word-break:break-all}
.ci.sub{color:#8b949e}
</style>
</head>
<body>
<div id="hdr">
  <h1>⬡ 知识图谱</h1>
  <span class="sub">__PROJECT__ &nbsp;·&nbsp; __NC__ 个系统 &nbsp;·&nbsp; __EC__ 条关联 &nbsp;·&nbsp; 累计查询 __QC__ 次 &nbsp;·&nbsp; 反馈准确率 __ACC__</span>
  <div style="margin-left:auto;display:flex;gap:8px">
    <button class="hbtn" onclick="doLayout()">重排</button>
    <button class="hbtn" onclick="cy.fit(undefined,40)">适应</button>
    <button class="hbtn" onclick="resetFilter()">全部</button>
  </div>
</div>
<div id="main">
  <div id="sb">
    <div id="sb-top">
      <div><div class="st">域筛选</div><div id="df"></div></div>
      <div>
        <div class="st">图例</div>
        <div class="lr"><div class="lv"></div><span>verified（已验证）</span></div>
        <div class="lr"><div class="ld"></div><span>draft（待验证）</span></div>
      </div>
    </div>
    <div id="det-hdr">节点详情</div>
    <div id="det"><div class="emp">点击节点查看详情</div></div>
    <div class="st" style="margin:10px 0 4px">运营汇总</div>
    <div id="sum"></div>
  </div>
  <div id="cy-wrap"><div id="cy"></div></div>
</div>
<script>
const D=__DATA__;
const els=[];
D.nodes.forEach(n=>els.push({data:{id:n.id,label:n.name_cn,domain:n.domain,color:n.color,type:n.type,summary:n.summary,pitfalls:n.pitfalls,code:n.code,stats:n.stats},position:{x:n.pos.x,y:n.pos.y}}));
D.edges.forEach(e=>els.push({data:{id:e.id,source:e.source,target:e.target,context:e.context,confidence:e.confidence,ec:e.edgeColor,ls:e.lineStyle}}));

const cy=cytoscape({
  container:document.getElementById('cy'),
  elements:els,
  style:[
    {selector:'node',style:{
      'background-color':'data(color)',
      'label':'data(label)',
      'color':'#fff',
      'text-valign':'center','text-halign':'center',
      'font-size':'11px','font-weight':'600',
      'width':120,'height':38,
      'shape':'round-rectangle',
      'text-wrap':'wrap','text-max-width':'100px',
      'text-outline-color':'#000','text-outline-opacity':.3,'text-outline-width':1,
    }},
    {selector:'node:selected',style:{'border-width':3,'border-color':'#58a6ff'}},
    {selector:'node.faded',style:{opacity:.12}},
    {selector:'edge',style:{
      'width':1.5,
      'line-color':'data(ec)',
      'target-arrow-color':'data(ec)',
      'target-arrow-shape':'triangle',
      'curve-style':'bezier',
      'opacity':.75,
      'line-style':'data(ls)',
    }},
    {selector:'edge.faded',style:{opacity:.04}},
    {selector:'edge:selected',style:{width:3,opacity:1}},
  ],
  layout:{name:'preset',fit:true,padding:60}
});

function doLayout(){cy.layout({name:'preset',fit:true,padding:60,animate:true,animationDuration:400}).run();}

// Domain filter
let active=null;
function filterDomain(d){
  if(active===d){resetFilter();return;}
  active=d;
  document.querySelectorAll('.dbtn').forEach(b=>b.classList.toggle('on',b.dataset.d===d));
  cy.nodes().forEach(n=>n.toggleClass('faded',n.data('domain')!==d));
  cy.edges().forEach(e=>{
    const s=cy.getElementById(e.data('source')).data('domain');
    const t=cy.getElementById(e.data('target')).data('domain');
    e.toggleClass('faded',s!==d&&t!==d);
  });
}
function resetFilter(){
  active=null;
  cy.elements().removeClass('faded');
  document.querySelectorAll('.dbtn').forEach(b=>b.classList.remove('on'));
}

// Build domain buttons
const df=document.getElementById('df');
Object.entries(D.domains).forEach(([d,info])=>{
  const b=document.createElement('button');
  b.className='dbtn';b.dataset.d=d;
  b.style.setProperty('--dc',info.color);
  b.innerHTML=`<div class="ddot"></div><span class="dname">${d}</span><span class="dcnt">${info.count}</span>`;
  b.title=info.desc||'';
  b.onclick=()=>filterDomain(d);
  df.appendChild(b);
});

// Edge tooltip on hover
cy.on('mouseover','edge',function(e){
  const ctx=e.target.data('context');
  const conf=e.target.data('confidence');
  if(ctx) e.target.style({'label':ctx,'font-size':'9px','color':'#c9d1d9','text-background-color':'#161b22','text-background-opacity':1,'text-background-padding':'3px'});
});
cy.on('mouseout','edge',function(e){
  e.target.style({'label':'','text-background-opacity':0});
});

// Node click
cy.on('tap','node',function(e){
  const d=e.target.data();
  let h=`<div class="dn" style="color:${d.color}">${d.label}</div>`;
  h+=`<div class="dm">${d.domain} · ${d.type} · <code>${d.id}</code></div>`;
  h+=`<div class="ds">${d.summary||'暂无描述'}</div>`;
  if(d.pitfalls&&d.pitfalls.length){
    h+=`<div class="dsec">⚠ 持久化注意点</div>`;
    d.pitfalls.forEach(p=>{h+=`<div class="pit">${p}</div>`;});
  }
  if(d.code&&Object.keys(d.code).length){
    h+=`<div class="dsec">📁 关键代码</div>`;
    Object.entries(d.code).forEach(([k,v])=>{
      if(typeof v==='string'&&!v.endsWith('/')){
        h+=`<div class="ci" title="${v}">● ${v.split('/').pop()}</div>`;
      }else if(Array.isArray(v)){
        const show=v.slice(0,4);
        show.forEach(f=>{if(typeof f==='string')h+=`<div class="ci" title="${f}">○ ${f.split('/').pop()}</div>`;});
        if(v.length>4)h+=`<div class="ci sub">...共 ${v.length} 个</div>`;
      }
    });
  }
  const st=d.stats||{};
  h+=`<div class="dsec">📊 使用数据</div>`;
  h+=`<div class="ci">查询命中 ${st.hits||0} 次 &nbsp;·&nbsp; 反馈 准确 ${st.acc||0} / 不准 ${st.bad||0}</div>`;
  if(st.changes&&st.changes.length){
    h+=`<div class="dsec">🕘 变更历史（共 ${st.change_count} 次，最近 ${st.changes.length} 条）</div>`;
    st.changes.forEach(c=>{h+=`<div class="pit" style="border-color:#30363d">${(c.ts||'').slice(0,10)} [${c.op}] ${c.reason||''}</div>`;});
  }
  document.getElementById('det').innerHTML=h;
});

cy.on('tap',function(e){
  if(e.target===cy)document.getElementById('det').innerHTML='<div class="emp">点击节点查看详情</div>';
});

// 运营汇总
(function(){
  const s=D.summary||{};
  const acc=(s.accuracy===null||s.accuracy===undefined)?'暂无':Math.round(s.accuracy*100)+'%';
  let h='';
  h+=`<div class="ci">累计查询 ${s.total_queries||0} 次 &nbsp;·&nbsp; 总命中 ${s.total_hits||0} 次</div>`;
  h+=`<div class="ci">反馈 ${s.total_feedback||0} 条：准确 ${s.feedback_accurate||0} / 不准 ${s.feedback_inaccurate||0} &nbsp;·&nbsp; 准确率 ${acc}</div>`;
  h+=`<div class="ci">entry 被查过 ${s.queried_entries||0} / 共 ${s.total_entries||0} &nbsp;·&nbsp; 从未查过 ${s.never_queried_entries||0}</div>`;
  h+=`<div class="ci">总变更 ${s.total_changes||0} 次</div>`;
  document.getElementById('sum').innerHTML=h;
})();
</script>
</body>
</html>"""


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser(description="生成知识图谱可视化 HTML")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--kg", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    project_root = args.root.resolve()
    try:
        kg_dir = resolve_kg_dir(project_root, args.kg)
    except KGError as e:
        print(f"ERROR: {e}")
        return 1
    out_path = ((project_root / args.output).resolve() if args.output
                else kg_dir / "graph_view.html")

    if not kg_dir.exists():
        print(f"ERROR: 图谱目录不存在: {kg_dir}")
        return 1

    print("读取图谱数据...")
    stats = KG(project_root, args.kg).stats()
    total_queries = stats["total_queries"]
    summary = stats["summary"]
    data = load_data(kg_dir, stats["per_entry"])
    data["summary"] = summary
    nc, ec = len(data["nodes"]), len(data["edges"])
    print(f"  nodes: {nc}, edges: {ec}, 累计查询: {total_queries}, 准确率: {summary['accuracy']}")

    main_graph = json.loads((kg_dir / "graph.json").read_text("utf-8"))
    project_name = main_graph.get("project") or project_root.name

    html = HTML_TEMPLATE
    html = html.replace("__PROJECT__", project_name)
    html = html.replace("__QC__", str(total_queries))
    acc = summary["accuracy"]
    html = html.replace("__ACC__", ("%.0f%%" % (acc * 100)) if acc is not None else "暂无反馈")
    html = html.replace("__NC__", str(nc))
    html = html.replace("__EC__", str(ec))
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))

    out_path.write_text(html, encoding="utf-8")
    print(f"已生成: {out_path}")
    print("  用浏览器打开该文件即可（需网络加载 Cytoscape.js）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
