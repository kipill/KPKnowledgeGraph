#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识图谱可视化生成器 / 动态查看 server

两种模式:
  1. 静态导出（默认）: python gen_graph_html.py [--root ...] [--output ...]
     生成自包含的 graph_view.html（cytoscape 内联、数据内联），可离线打开/分享。
  2. 动态查看: python gen_graph_html.py --serve [--port N] [--no-open]
     起本地 http server（仅 127.0.0.1，自动选可用端口），浏览器实时查看图谱，
     并支持在页面上把 draft 边标记为 verified——写操作经 kg_core.verify_edge，
     自带校验 / changelog / 反向索引重建，与 AI 调 kg MCP 工具完全等价（守治理层）。

cytoscape.js 随发行包本地提供（tools/vendor/cytoscape.min.js），无外网依赖。
"""

import argparse
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_core import KG, KGError, resolve_kg_dir  # noqa: E402

CYTOSCAPE_VERSION = "3.28.1"
VENDOR_JS = Path(__file__).resolve().parent / "vendor" / "cytoscape.min.js"

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


def _project_name(kg_dir: Path, root: Path) -> str:
    main_graph = json.loads((kg_dir / "graph.json").read_text("utf-8"))
    return main_graph.get("project") or root.name


def _fill_placeholders(html: str, project: str, nc: int, ec: int,
                       total_queries: int, accuracy, cytoscape_tag: str, bootstrap: str) -> str:
    acc_text = ("%.0f%%" % (accuracy * 100)) if accuracy is not None else "暂无反馈"
    return (html
            .replace("__PROJECT__", project)
            .replace("__CYTOSCAPE_TAG__", cytoscape_tag)
            .replace("__QC__", str(total_queries))
            .replace("__ACC__", acc_text)
            .replace("__NC__", str(nc))
            .replace("__EC__", str(ec))
            .replace("__BOOTSTRAP__", bootstrap))


# ==================== HTML 模板 ====================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>知识图谱 · __PROJECT__</title>
__CYTOSCAPE_TAG__
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
.hint{font-size:11px;color:#8b949e;line-height:1.5;margin-top:8px;padding:6px 8px;background:#0d1117;border-radius:6px;border:1px solid #21262d}
/* 节点/边统一 tooltip */
.kg-tooltip{position:fixed;z-index:1200;display:none;max-width:460px;min-width:180px;background:rgba(22,27,34,0.98);border:1px solid #30363d;border-radius:10px;padding:14px 16px;box-shadow:0 12px 32px rgba(0,0,0,.55),0 0 0 1px rgba(0,0,0,.2);pointer-events:none;font-size:14px;line-height:1.55;color:#c9d1d9;backdrop-filter:blur(4px)}
.kg-tooltip .tt-hd{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:13px;font-weight:700;color:#58a6ff}
.kg-tooltip .tt-hd .tt-arrow{font-weight:400;color:#8b949e}
.kg-tooltip .tt-body{word-break:break-word;margin-bottom:8px}
.kg-tooltip .tt-meta{display:flex;align-items:center;gap:10px;font-size:12px;font-weight:600;color:#8b949e}
.kg-tooltip .tt-tag{display:inline-flex;align-items:center;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px}
.kg-tooltip .tt-tag.verified{background:rgba(46,160,67,.15);color:#3fb950}
.kg-tooltip .tt-tag.draft{background:rgba(210,153,34,.15);color:#e3b341}
.kg-tooltip .tt-tag.domain{background:#21262d;color:#c9d1d9}
.kg-tooltip .tt-tag.type{background:#30363d;color:#c9d1d9}
.kg-tooltip::after{content:'';position:absolute;width:0;height:0;border:8px solid transparent}
.kg-tooltip.pos-bottom::after{top:-16px;left:20px;border-bottom-color:rgba(22,27,34,0.98)}
.kg-tooltip.pos-top::after{bottom:-16px;left:20px;border-top-color:rgba(22,27,34,0.98)}
.kg-tooltip.pos-right::after{left:-16px;top:20px;border-right-color:rgba(22,27,34,0.98)}
.kg-tooltip.pos-left::after{right:-16px;top:20px;border-left-color:rgba(22,27,34,0.98)}
/* draft 边验证 modal */
.modal-overlay{position:fixed;inset:0;z-index:2000;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.55)}
.modal-box{width:420px;max-width:92vw;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px;box-shadow:0 12px 32px rgba(0,0,0,.55)}
.modal-title{font-size:18px;font-weight:700;color:#58a6ff;margin-bottom:14px}
.modal-body p{margin-bottom:10px;font-size:14px;color:#c9d1d9}
.modal-body .vm-ctx{color:#8b949e;font-size:13px;line-height:1.5;padding:8px;background:#0d1117;border-radius:6px;border:1px solid #21262d}
.modal-body label{display:block;margin:14px 0 6px;font-size:13px;color:#8b949e}
.modal-body input{width:100%;padding:9px 10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px}
.modal-body input:focus{outline:none;border-color:#58a6ff}
.vm-error{display:none;color:#f85149;font-size:13px;margin-top:10px;padding:8px;background:rgba(248,81,73,.1);border-radius:6px}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}
.modal-actions button{padding:8px 16px;border-radius:6px;border:1px solid #30363d;cursor:pointer;font-size:13px}
.modal-actions .btn-secondary{background:#21262d;color:#c9d1d9}
.modal-actions .btn-secondary:hover{background:#30363d}
.modal-actions .btn-primary{background:#238636;color:#fff;border-color:#238636}
.modal-actions .btn-primary:hover{background:#2ea043}
</style>
</head>
<body>
<div id="hdr">
  <h1>⬡ 知识图谱</h1>
  <span class="sub">__PROJECT__ &nbsp;·&nbsp; __NC__ 个系统 &nbsp;·&nbsp; __EC__ 条关联 &nbsp;·&nbsp; 累计查询 __QC__ 次 &nbsp;·&nbsp; 反馈准确率 __ACC__</span>
  <div style="margin-left:auto;display:flex;gap:8px">
    <button class="hbtn" onclick="doLayout()">重排</button>
    <button class="hbtn" onclick="doFit()">适应</button>
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
        <div class="lr"><div class="ld"></div><span>draft（点击边可标记为已验证）</span></div>
      </div>
    </div>
    <div id="det-hdr">节点详情</div>
    <div id="det"><div class="emp">点击节点查看详情<br>悬停节点/边查看放大提示框</div></div>
    <div class="st" style="margin:10px 0 4px">运营汇总</div>
    <div id="sum"></div>
  </div>
  <div id="cy-wrap"><div id="cy"></div></div>
</div>

<!-- 统一浮动提示框 -->
<div id="tt" class="kg-tooltip">
  <div class="tt-hd"><span id="tt-from"></span><span class="tt-arrow">→</span><span id="tt-to"></span></div>
  <div class="tt-body" id="tt-body"></div>
  <div class="tt-meta">
    <span class="tt-tag" id="tt-tag1"></span>
    <span class="tt-tag domain" id="tt-tag2"></span>
    <span class="tt-tag type" id="tt-tag3"></span>
  </div>
</div>

<!-- draft 边验证 modal -->
<div id="verify-modal" class="modal-overlay" style="display:none">
  <div class="modal-box">
    <div class="modal-title">验证关联</div>
    <div class="modal-body">
      <p><strong id="vm-from"></strong> → <strong id="vm-to"></strong></p>
      <p class="vm-ctx" id="vm-ctx"></p>
      <label for="vm-reason">原因（写入 changelog，必填）：</label>
      <input type="text" id="vm-reason" value="通过可视化页面标记为已验证" />
      <div class="vm-error" id="vm-error"></div>
    </div>
    <div class="modal-actions">
      <button class="btn-secondary" onclick="closeVerifyModal()">取消</button>
      <button class="btn-primary" onclick="submitVerify()">标记为已验证</button>
    </div>
  </div>
</div>

<script>
let cy=null;
let active=null;
let nodeMap={};

function render(D){
  if(cy){ cy.destroy(); cy=null; }
  nodeMap={};
  D.nodes.forEach(n=>nodeMap[n.id]=n);
  const TYPE_SHAPE={system:'round-rectangle',module:'rectangle',service:'ellipse',api:'diamond',entity:'hexagon'};
  const TYPE_LABEL={system:'系统',module:'模块',service:'服务',api:'接口',entity:'实体'};

  const els=[];
  D.nodes.forEach(n=>els.push({data:{id:n.id,label:n.name_cn,domain:n.domain,color:n.color,type:n.type,typeLabel:TYPE_LABEL[n.type]||n.type,summary:n.summary,pitfalls:n.pitfalls,code:n.code,stats:n.stats},position:{x:n.pos.x,y:n.pos.y}}));
  D.edges.forEach(e=>els.push({data:{id:e.id,source:e.source,target:e.target,context:e.context,confidence:e.confidence,ec:e.edgeColor,ls:e.lineStyle}}));

  cy=cytoscape({
    container:document.getElementById('cy'),
    elements:els,
    style:[
      {selector:'node',style:{
        'background-color':'data(color)',
        'label':'data(label)',
        'color':'#fff',
        'text-valign':'center','text-halign':'center',
        'font-size':'12px','font-weight':'600',
        'width':126,'height':40,
        'shape':'round-rectangle',
        'text-wrap':'wrap','text-max-width':'106px',
        'text-outline-color':'#000','text-outline-opacity':.3,'text-outline-width':1,
      }},
      {selector:'node[type="module"]',style:{shape:'rectangle',width:118,height:36,'border-width':2,'border-color':'#fff','border-opacity':.25}},
      {selector:'node[type="service"]',style:{shape:'ellipse',width:132,height:46}},
      {selector:'node[type="api"]',style:{shape:'diamond',width:96,height:96,'font-size':'11px','text-max-width':'80px'}},
      {selector:'node[type="entity"]',style:{shape:'hexagon',width:112,height:44}},
      {selector:'node:selected',style:{'border-width':3,'border-color':'#58a6ff'}},
      {selector:'node.faded',style:{opacity:.12}},
      {selector:'edge',style:{
        'width':1.8,
        'line-color':'data(ec)',
        'target-arrow-color':'data(ec)',
        'target-arrow-shape':'triangle',
        'curve-style':'bezier',
        'opacity':.8,
        'line-style':'data(ls)',
      }},
      {selector:'edge.faded',style:{opacity:.04}},
      {selector:'edge:selected',style:{width:3,opacity:1}},
    ],
    layout:{name:'preset',fit:true,padding:60}
  });

  // Domain filter buttons
  const df=document.getElementById('df'); df.innerHTML='';
  Object.entries(D.domains).forEach(([d,info])=>{
    const b=document.createElement('button');
    b.className='dbtn';b.dataset.d=d;
    b.style.setProperty('--dc',info.color);
    b.innerHTML=`<div class="ddot"></div><span class="dname">${d}</span><span class="dcnt">${info.count}</span>`;
    b.title=info.desc||'';
    b.onclick=()=>filterDomain(d);
    df.appendChild(b);
  });

  // Tooltip elements
  const tt=document.getElementById('tt');
  const ttFrom=document.getElementById('tt-from');
  const ttTo=document.getElementById('tt-to');
  const ttBody=document.getElementById('tt-body');
  const ttTag1=document.getElementById('tt-tag1');
  const ttTag2=document.getElementById('tt-tag2');
  const ttTag3=document.getElementById('tt-tag3');

  function showTooltip(){tt.style.display='block';}
  function hideTooltip(){tt.style.display='none';tt.className='kg-tooltip';}
  function positionTooltip(x,y){
    const pad=14;
    const rect=tt.getBoundingClientRect();
    const vw=window.innerWidth,vh=window.innerHeight;
    let left=x+pad,top=y+pad,cls='pos-bottom';
    if(left+rect.width>vw-pad){left=x-rect.width-pad;cls='pos-left';}
    if(top+rect.height>vh-pad){top=y-rect.height-pad;cls=cls==='pos-left'?'pos-left':'pos-top';}
    if(left<pad)left=pad;
    if(top<pad)top=pad;
    tt.style.left=left+'px';
    tt.style.top=top+'px';
    tt.className='kg-tooltip '+cls;
  }
  function setEdgeTooltip(d,clientX,clientY){
    const src=nodeMap[d.source],tgt=nodeMap[d.target];
    ttFrom.textContent=src?src.name_cn:d.source;
    ttTo.textContent=tgt?tgt.name_cn:d.target;
    ttFrom.style.color=src?src.color:'#58a6ff';
    ttTo.style.color=tgt?tgt.color:'#58a6ff';
    ttBody.textContent=d.context||'暂无描述';
    ttTag1.textContent=d.confidence==='verified'?'verified（已验证）':'draft（待验证）';
    ttTag1.className='tt-tag '+(d.confidence==='verified'?'verified':'draft');
    ttTag2.textContent=(src?src.domain:'')+' → '+(tgt?tgt.domain:'');
    ttTag2.className='tt-tag domain';
    ttTag3.style.display='none';
    showTooltip();
    requestAnimationFrame(()=>positionTooltip(clientX,clientY));
  }
  function setNodeTooltip(d,clientX,clientY){
    ttFrom.textContent=d.label;
    ttFrom.style.color=d.color;
    ttTo.textContent='';
    ttBody.innerHTML=(d.summary||'暂无描述')+'<div style="margin-top:8px;font-size:12px;color:#8b949e">'+d.domain+' · '+(d.typeLabel||d.type)+'</div>';
    ttTag1.textContent=d.typeLabel||d.type;
    ttTag1.className='tt-tag type';
    ttTag2.textContent=d.domain;
    ttTag2.className='tt-tag domain';
    ttTag3.style.display='none';
    showTooltip();
    requestAnimationFrame(()=>positionTooltip(clientX,clientY));
  }

  cy.on('mouseover','edge',function(e){setEdgeTooltip(e.target.data(),e.originalEvent.clientX,e.originalEvent.clientY);});
  cy.on('mousemove','edge',function(e){if(tt.style.display==='block')positionTooltip(e.originalEvent.clientX,e.originalEvent.clientY);});
  cy.on('mouseout','edge',function(e){hideTooltip();});

  cy.on('mouseover','node',function(e){setNodeTooltip(e.target.data(),e.originalEvent.clientX,e.originalEvent.clientY);});
  cy.on('mousemove','node',function(e){if(tt.style.display==='block')positionTooltip(e.originalEvent.clientX,e.originalEvent.clientY);});
  cy.on('mouseout','node',function(e){hideTooltip();});

  // Node click → detail panel
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

  // Click empty background → clear detail
  cy.on('tap',function(e){
    if(e.target===cy)document.getElementById('det').innerHTML='<div class="emp">点击节点查看详情<br>悬停节点/边查看放大提示框</div>';
  });

  // Click a draft edge → mark as verified (POST /api/verify_edge)
  cy.on('tap','edge',onEdgeTap);

  // 运营汇总
  (function(){
    const s=D.summary||{};
    const acc=(s.accuracy===null||s.accuracy===undefined)?'暂无':Math.round(s.accuracy*100)+'%';
    let h='';
    h+=`<div class="ci">累计查询 ${s.total_queries||0} 次 · 总命中 ${s.total_hits||0} 次</div>`;
    h+=`<div class="ci">反馈 ${s.total_feedback||0} 条：准确 ${s.feedback_accurate||0} / 不准 ${s.feedback_inaccurate||0} · 准确率 ${acc}</div>`;
    h+=`<div class="ci">entry 被查过 ${s.queried_entries||0} / 共 ${s.total_entries||0} · 从未查过 ${s.never_queried_entries||0}</div>`;
    h+=`<div class="ci">总变更 ${s.total_changes||0} 次</div>`;
    document.getElementById('sum').innerHTML=h;
  })();

  if(active){ filterDomain(active); }
}

function doLayout(){ if(cy) cy.layout({name:'preset',fit:true,padding:60,animate:true,animationDuration:400}).run(); }
function doFit(){ if(cy) cy.fit(undefined,40); }

function filterDomain(d){
  if(!cy) return;
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
  if(!cy) return;
  cy.elements().removeClass('faded');
  document.querySelectorAll('.dbtn').forEach(b=>b.classList.remove('on'));
}

// 动态模式：从 server 拉数据后渲染
function loadData(){
  return fetch('/api/data').then(r=>r.json()).then(render);
}

// Verify modal（draft 边点击验证）
let pendingVerify = null;
const verifyModal = document.getElementById('verify-modal');
const vmFrom = document.getElementById('vm-from');
const vmTo = document.getElementById('vm-to');
const vmCtx = document.getElementById('vm-ctx');
const vmReason = document.getElementById('vm-reason');
const vmError = document.getElementById('vm-error');

function openVerifyModal(d){
  pendingVerify = {source: d.source, target: d.target};
  const src=nodeMap[d.source], tgt=nodeMap[d.target];
  vmFrom.textContent = src ? src.name_cn : d.source;
  vmTo.textContent = tgt ? tgt.name_cn : d.target;
  vmCtx.textContent = d.context || '';
  vmReason.value = '通过可视化页面标记为已验证';
  vmError.textContent = '';
  vmError.style.display = 'none';
  verifyModal.style.display = 'flex';
  setTimeout(()=>vmReason.focus(), 0);
}

function closeVerifyModal(){
  pendingVerify = null;
  verifyModal.style.display = 'none';
}

function submitVerify(){
  if(!pendingVerify) return;
  const reason = vmReason.value.trim();
  if(!reason){
    vmError.textContent = '原因不能为空';
    vmError.style.display = 'block';
    return;
  }
  vmError.style.display = 'none';
  fetch('/api/verify_edge',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({from_id:pendingVerify.source,to_id:pendingVerify.target,reason:reason})})
    .then(r=>r.json())
    .then(j=>{
      if(j.ok){ closeVerifyModal(); loadData(); }
      else { vmError.textContent = j.error || '标记失败'; vmError.style.display = 'block'; }
    })
    .catch(err=>{ vmError.textContent = '请求失败：'+err; vmError.style.display = 'block'; });
}

verifyModal.addEventListener('click',function(e){ if(e.target===verifyModal) closeVerifyModal(); });
document.addEventListener('keydown',function(e){ if(e.key==='Escape') closeVerifyModal(); });

// 点 draft 边 → 标记已验证（写操作走 /api/verify_edge → kg_core.verify_edge）
function onEdgeTap(e){
  const d=e.target.data();
  if(d.confidence!=='draft') return;  // 只 draft 边可标记
  openVerifyModal(d);
}

__BOOTSTRAP__
</script>

</body>
</html>"""


# ==================== 静态导出 ====================

def gen_static(root: Path, kg_dir: Path, out_path: Path) -> int:
    if not VENDOR_JS.exists():
        print("ERROR: 找不到 cytoscape 本地文件: %s" % VENDOR_JS)
        print("       serve 模式或静态导出都需要它随发行包部署。")
        return 1
    cyto_inline = VENDOR_JS.read_text("utf-8")
    if "</script" in cyto_inline.lower():
        print("ERROR: cytoscape.min.js 含 </script 序列，无法安全内联")
        return 1

    kg = KG(root, kg_dir)
    stats = kg.stats()
    summary = stats["summary"]
    data = load_data(kg.kg_dir, stats["per_entry"])
    data["summary"] = summary
    nc, ec = len(data["nodes"]), len(data["edges"])

    html = _fill_placeholders(
        HTML_TEMPLATE,
        project=_project_name(kg.kg_dir, root),
        nc=nc, ec=ec,
        total_queries=stats["total_queries"],
        accuracy=summary["accuracy"],
        cytoscape_tag="<script>%s</script>" % cyto_inline,
        bootstrap="render(%s);" % json.dumps(data, ensure_ascii=False),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print("已生成: %s" % out_path)
    print("  nodes: %d, edges: %d, 累计查询: %d, 准确率: %s"
          % (nc, ec, stats["total_queries"], summary["accuracy"]))
    print("  自包含单文件，cytoscape 已内联，可离线打开")
    return 0


# ==================== 动态查看 server ====================

def build_page_html(root: Path, kg_dir: Path) -> str:
    """serve 模式 / 路由每次构造：页眉服务端渲染，body 由前端 fetch /api/data。"""
    kg = KG(root, kg_dir)
    stats = kg.stats()
    summary = stats["summary"]
    data = load_data(kg.kg_dir, stats["per_entry"])
    nc, ec = len(data["nodes"]), len(data["edges"])
    return _fill_placeholders(
        HTML_TEMPLATE,
        project=_project_name(kg.kg_dir, root),
        nc=nc, ec=ec,
        total_queries=stats["total_queries"],
        accuracy=summary["accuracy"],
        cytoscape_tag='<script src="/static/cytoscape.min.js"></script>',
        bootstrap="loadData();",
    )


class KGHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, handler, root, kg_dir):
        super().__init__(addr, handler)
        self.root = root
        self.kg_dir = kg_dir
        self.vendor_js = VENDOR_JS


class KGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默默认访问日志
        pass

    def _touch(self):
        self.server.last_request_time = time.time()

    def _send(self, code, ctype, body: bytes, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        self._touch()
        path = self.path.split("?", 1)[0]
        if path == "/":
            try:
                html = build_page_html(self.server.root, self.server.kg_dir)
            except KGError as e:
                self._json(500, {"ok": False, "error": str(e)}); return
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
        elif path == "/static/cytoscape.min.js":
            vj = self.server.vendor_js
            if vj.exists():
                self._send(200, "application/javascript; charset=utf-8", vj.read_bytes(), cache=True)
            else:
                self._send(404, "text/plain; charset=utf-8", b"cytoscape.min.js not found")
        elif path == "/api/data":
            try:
                kg = KG(self.server.root, self.server.kg_dir)
                stats = kg.stats()
                data = load_data(kg.kg_dir, stats["per_entry"])
                data["summary"] = stats["summary"]   # load_data 不含 summary，这里补
                self._json(200, data)
            except KGError as e:
                self._json(400, {"ok": False, "error": str(e)})
        else:
            self._send(404, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self):
        self._touch()
        path = self.path.split("?", 1)[0]
        if path != "/api/verify_edge":
            self._send(404, "text/plain; charset=utf-8", b"Not found"); return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            kg = KG(self.server.root, self.server.kg_dir)
            # 唯一写动作：转调 kg_core.verify_edge，校验/changelog/反向索引全走 _commit
            entry = kg.verify_edge(payload.get("from_id"), payload.get("to_id"), payload.get("reason"))
            self._json(200, {"ok": True, "entry": entry})
        except KGError as e:
            self._json(400, {"ok": False, "error": str(e)})
        except Exception as e:
            self._json(400, {"ok": False, "error": "请求处理失败: %s" % e})


def serve(root: Path, kg_dir: Path, port: int, open_browser: bool, idle_timeout: int = 1800) -> int:
    # 启动自检：图谱目录错误立即退出（照搬 kg_mcp_server 模式）
    try:
        KG(root, kg_dir)
    except KGError as e:
        print("启动失败: %s" % e, file=sys.stderr)
        return 1
    if not VENDOR_JS.exists():
        print("警告: 未找到 cytoscape 本地文件 %s，页面将无法渲染图谱" % VENDOR_JS, file=sys.stderr)

    addr = ("127.0.0.1", port or 0)   # port=0 → OS 分配可用端口，避免冲突
    httpd = KGHTTPServer(addr, KGHandler, root, kg_dir)
    actual_port = httpd.server_address[1]
    url = "http://127.0.0.1:%d" % actual_port
    httpd.last_request_time = time.time()   # 用于空闲超时判断

    # 空闲超时守护线程：默认 30 分钟无请求自动停止，避免 skill/AI 意外退出后 server 残留
    watcher = None
    if idle_timeout and idle_timeout > 0:
        def _idle_watcher():
            while True:
                time.sleep(5)
                if time.time() - httpd.last_request_time > idle_timeout:
                    print("\n[%d 秒无请求，自动停止 server]" % idle_timeout, file=sys.stderr)
                    sys.stdout.flush()
                    httpd.shutdown()
                    break
        watcher = threading.Thread(target=_idle_watcher, daemon=True)
        watcher.start()

    print("知识图谱可视化 server 已启动")
    print("  打开: %s" % url)
    print("  仅本机访问（127.0.0.1）。Ctrl+C 停止。", end="")
    if idle_timeout and idle_timeout > 0:
        print(" %d 分钟无请求自动停止。" % (idle_timeout // 60))
    else:
        print()
    print("  点 draft 边（虚线）可标记为已验证。")
    sys.stdout.flush()
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser(description="知识图谱可视化（静态导出 / 动态查看 server）")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根（默认当前目录）")
    parser.add_argument("--kg", type=Path, default=None, help="图谱目录（默认自动探测 .claude/kg 或 tools/qx_rag）")
    parser.add_argument("--output", type=Path, default=None,
                        help="静态模式输出文件（默认 <图谱目录>/graph_view.html）")
    parser.add_argument("--serve", action="store_true", help="启动动态查看 server（默认生成静态 HTML）")
    parser.add_argument("--port", type=int, default=0, help="server 端口（默认 0 = 自动选可用端口）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--idle-timeout", type=int, default=1800,
                        help="空闲多少秒后自动停止（默认 1800=30 分钟，0 禁用）")
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        kg_dir = resolve_kg_dir(root, args.kg)
    except KGError as e:
        print("ERROR: %s" % e)
        return 1

    if args.serve:
        return serve(root, kg_dir, args.port, not args.no_open, idle_timeout=args.idle_timeout)

    out_path = ((root / args.output).resolve() if args.output else kg_dir / "graph_view.html")
    return gen_static(root, kg_dir, out_path)


if __name__ == "__main__":
    raise SystemExit(main())
