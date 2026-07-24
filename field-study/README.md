# KPKnowledgeGraph 实地观测（Field Study）

对 KPKnowledgeGraph 在真实项目中的长期使用效果做结构化观测，积累成可复现的数据集，作为开发者的参考基准。

> 本目录随发行包开源。被测项目身份已脱敏为「案例项目A」，仅保留 `billing` / `gateway` 这类通用领域名（它们本身是通用术语，对开发者有参考价值）。

## 目的

回答三个开发者最关心的问题：

1. **装上以后真的会被用起来吗？** —— 查询量、查询密度（命中/查询）、需求→查询转化。
2. **查出来的东西准不准？** —— 反馈准确率、反馈覆盖。
3. **图在长肉还是只长骨架？** —— 变更活跃度、entry 查询覆盖率、未触达 entry 占比。

## 记录什么

每条快照逐字段对齐 `kg_core.py` 的 `KG.stats()["summary"]`，保证**可由一条命令复现**，不存在人工编造的口径。

| 字段 | 含义 | 来源 |
|---|---|---|
| `total_entries` | entry 总数（不含 `_` 前缀占位） | `graph-*.json` |
| `total_queries` | 累计查询次数（含 query / catalog） | `querylog.jsonl` |
| `total_hits` | 总命中数 = 所有 entry 命中次数之和（一次 query 可命中多个） | `querylog.jsonl` |
| `total_feedback` | 反馈条数 = 准确 + 不准 | `querylog.jsonl` |
| `feedback_accurate` | 标记为准确的反馈数 | `querylog.jsonl` |
| `feedback_inaccurate` | 标记为不准的反馈数 | `querylog.jsonl` |
| `accuracy` | 准确率 = accurate / feedback（无反馈时为 `null`） | 计算 |
| `queried_entries` | 至少被命中过一次的 entry 数 | `querylog.jsonl` |
| `never_queried_entries` | 从未被查过的 entry 数（删/合并候选） | `querylog.jsonl` |
| `total_changes` | 累计变更次数（add/update/relation/pitfall/verify/domain/cross_relation） | `changelog.jsonl` |

### 派生指标（用于横纵向对比）

| 指标 | 公式 | 健康含义 |
|---|---|---|
| 查询命中密度 | `total_hits / total_queries` | 落在 3–8 为甜区；<1 说明索引坏，>10 说明召回太宽 |
| entry 覆盖率 | `queried_entries / total_entries` | 衡量图的「活 entry」比例，长期应 >60% |
| 反馈率 | `total_feedback / total_queries` | 反映用户标记习惯，>30% 即活跃 |
| 变更密度 | `total_changes / total_entries` | >1 说明在持续加 relation/pitfall，不是加完就丢 |
| 未触达占比 | `never_queried_entries / total_entries` | 长期偏高需清理噪音 |

## 怎么记（可复现命令）

在**被测项目根目录**下运行（用项目自带的 `tools/kg_core.py`）：

```bash
cd <项目根>
python -X utf8 -c "
import sys, json
sys.path.insert(0, '.claude/kg/tools')
from kg_core import KG
kg = KG(r'<项目根绝对路径>', r'<项目根绝对路径>\.claude\kg')
print(json.dumps(kg.stats()['summary'], ensure_ascii=False, indent=2))
"
```

输出即 `summary` 全字段。把结果追加到：

- `snapshots.jsonl` —— 机器可读，一行一条（见下方 schema）。
- `observations.md` —— 人类可读，更新汇总表 + 写一段本期备注。

### `snapshots.jsonl` 单条 schema

```json
{
  "id": "FS-NNN",
  "date": "YYYY-MM-DD",
  "project": "案例项目A",
  "domains": ["billing", "gateway", "..."],
  "summary": { "...": "kg.stats()['summary'] 原样" },
  "derived": { "hits_per_query": 5.0, "coverage_pct": 65.5, "feedback_rate_pct": 75.0, "changes_per_entry": 1.76, "never_queried_pct": 34.5 },
  "since_prev": { "new_queries": null, "new_entries": null, "new_changes": null, "delta_note": "首期无前序" },
  "notes": "本期发生了什么 / 异常 / 值得注意的点"
}
```

`id` 单调递增（`FS-001`、`FS-002`…）；`since_prev` 仅从第二期起填，记录相对上一期的增量。

## 节奏

**事件驱动**：当用户主动提起「记一下 kg 数据 / 看看效果 / field-study」时，跑一次命令、追加一条。不强制固定周期，因此时间序列可能疏密不均——这是预期，备注里写清触发事由即可（如「完成支付重构后」「上线一周回顾」）。

## 文件

- `README.md` —— 本规范（方法论）。
- `snapshots.jsonl` —— 原始数据集（一行一期）。
- `observations.md` —— 人类可读的汇总表 + 每期备注。
- `analysis.md` ——（积累若干期后补）跨期趋势分析与给开发者的结论。
