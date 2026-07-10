# 开发计划：可复用能力目录 + 复用推荐（Capability Catalog & Reuse Scout）

状态：**开发中 / 设计已确认 / feature/capability-reuse 分支**
目标版本：v2.4.0（MINOR：新增工具与字段，向后兼容）
提出来源：现场反馈的一类需求分诊问题 + 四轮子代理对照实验（见 §9）

> **本文档全程使用开源模拟数据**（`examples/mock-src/RewardGrantType.java` 等虚构类），
> 不含任何真实项目的类名或语义。采用者把示例映射到自己项目的对应枚举即可。

---

## 0. 背景与要解决的问题

现有 kg 的 entry 只索引到**系统级**（如 auction / economy / mail）。但项目里普遍存在
"可配置能力目录"——枚举/常量族，每个成员是一种可配置行为，需求方用**描述**
而非**名字**来提需求。模拟示例：`RewardGrantType`（奖励发放方式）。

失败模式：需求方提"玩家上线时发个登录奖励"，LLM 若不深挖，可能当**新功能**开发，
而其实现成的 `LOGIN_GRANT`（登录时发放）配表即可。图谱当前无法把
"已有哪个现成能力可配"推荐出来。

本特性给 kg 增加一个**经验层**（能力目录）+ 一个**复用推荐**能力，
和现有"事实查询"是两个正交方向。

---

## 1. 特性定义：两个正交方向

| 维度 | 方向 A：事实查询（现有 kg_query） | 方向 B：复用推荐（本特性新增） |
|------|-----------------------------------|-------------------------------|
| 触发 | 任何要碰代码时 | 只在"要新造能力"时 |
| 消费者 | LLM 直接用 | **人**来判断（LLM 只转述） |
| 性质 | 事实（权威） | 经验（概率性推荐） |
| 错了的后果 | 走错文件，自纠 | 若被直接执行 → 残缺方案上线 |
| 数据 | entry 的 code / related | 新增：能力目录 members 的语义标签 |

**核心安全契约**：推荐结果**永不直接变代码**。它是给人的参考，人拍板后，
LLM 再走方向 A（kg_query + 读代码）去实现。推荐工具的返回形态要主动
引导"人工确认"（见 §3 D8）。

---

## 2. 已收敛的设计决策（讨论中已定）

- **D1 LLM 分析源码填写,人工确认录入**：开发过程中 LLM 检查源码发现符合 §6.3 规则的能力目录,
  从正在读的代码里整理事实字段(enum_value/id/name)+ 起草语义字段(scenarios/reuse_note),
  有缺口处给出选项让人补充,整理清楚后调 MCP 接口写入。**写入侧人在环里**:LLM 整理 → 展示给人 →
  人确认才记,防垃圾目录污染经验层(对应 D6)。
  
- **D2 结构校验替代源码交叉校验**：写接口做基础结构校验(必填字段、类型),不做"机器抽枚举对比"
  的交叉校验。事实字段的准确性由 **LLM 现读现填 + 人工确认 + 推荐本就是参考(D8)** 三道防线保证。
  `source`(文件+符号)作为溯源线索保留,便于人确认时核对,但不输入机器校验。

- **D3 不把 code 路径塞进目录**：触发点/分发点（消费该枚举的 Manager/派发处）
  让 agent 命中推荐后自己 grep 定位，不硬编码进目录（路径最易漂移）。

- **D4 推荐分级**：命中且需求无额外限定 = "可复用推荐"；命中但需求含
  方向/时序/条件等超出该能力语义的限定词 = "功能类似参考（带边界警告）"；
  不命中 = 静默。分级判据是**有无超出语义的限定词**，不是关键词匹配强弱。

- **D5 通用化**：不为某一个具体枚举写专用脚本。做一个**通用能力目录机制**，
  模拟数据 `RewardGrantType` 只是第一个录入实例。适用判据见 §6.3。

## 3. 设计决策（已确认）

- **D6 写入侧人在环里**（原 OPEN-1，已确认）：LLM 发现候选目录 → **询问用户** →
  用户确认才记。写入侧与推荐侧对称，都是"LLM 冒泡、人拍板"，防垃圾目录污染经验层。
- **D7 适用规则采用三条判据**（原 OPEN-2，已确认）：见 §6.3，第三条"**需求方**描述而非点名"
  为主判据。（措辞用"需求方"，不用"策划"。）
- **D8 推荐不给可直接照抄的配置串**（原 OPEN-3，已确认）：返回只给"能力名 + 场景 +
  去确认语义边界"，**不给** `grantType=LOGIN_GRANT` 这类可照抄串，从源头拿掉
  grab-and-code 的料。代价是人多做一步定位，换来安全。
- **D9 反馈闭环必须做**：推荐后人拍板(复用/新增/理解错了)，LLM 调 MCP 接口记录到
  `reuse_feedback.jsonl`。基于 feedback 聚合统计(推荐次数/采纳次数/采纳率)，
  并按阈值分级标注(推荐<3次="待验证" / ≥10次且采纳率>70%="高置信")。
  统计数据暴露给推荐流程(让人看到这个 member 的历史表现)和 kg-view 可视化。
  **经验层是数据驱动的，不是规则驱动的**——feedback 用于迭代 scenarios 质量、
  发现假朋友、识别缺口。

> 九项设计决策已定，§5 各 Phase 接口形状据此固定。

---

## 4. 改动映射到本仓库文件

| 文件 | 改动 |
|------|------|
| `tools/kg_core.py` | 新增：① 能力目录数据模型加载/校验 ② 粗排匹配逻辑(关键词) ③ feedback 读写 ④ 统计聚合 ⑤ 写入口 add_capability_catalog |
| `tools/kg_mcp_server.py` | 新增 3 个 MCP 工具：`kg_add_capability_catalog`(写) / `kg_scout_reuse`(推荐粗排) / `kg_report_reuse_outcome`(反馈) / `kg_get_reuse_stats`(统计，可选) |
| `tools/validate.py` | 扩展：能力目录的结构校验(不做源码交叉校验) |
| `skills/kg-consult.skill.md` | 扩展：新增"复用推荐步骤"(分诊闸门、转述纪律、反馈记录) |
| `tools/gen_graph_html.py` | (Phase 3 后补) 扩展：能力目录渲染成节点 |
| `templates/graph_view.html` | (Phase 3 后补) 扩展：能力目录节点样式 + 侧边栏统计展示 |
| `reuse_feedback.jsonl` | 新增文件(和 changelog 同级)：推荐反馈记录 |
| `VERSION` / `CHANGELOG.md` | bump 2.4.0 + 变更条目 |
| `DEVELOPMENT.md` / `DESIGN.md` | 补文档：经验层定位、两方向分工、反馈闭环机制 |

---

## 5. 分阶段实现计划（按优先级,可独立验证）

**第一批:核心功能（先上线）**

### Phase 1：写接口 + 反馈接口
- **kg_add_capability_catalog**：
  - 参数(硬 schema)：`domain, catalog_id, name_cn, source{file,symbol}, 
    members[{enum_value, id, name, scenarios[], reuse_note}], reason`
  - 内部：基础结构校验(必填字段/类型) → 写入图谱(作为 entry `type: concept` 的 `x_capability_members` 扩展字段)
  - 复用现有原子写 + changelog + 反向索引管线
  - **验收**：录入 `RewardGrantType`，缺必填字段被拒；写入后能在 catalog 里查到

- **kg_report_reuse_outcome**：
  - 参数：`requirement, catalog_id, member(enum_value), decision(reuse|new|misunderstood), note可选`
  - 内部：追加一条 JSONL 到 `reuse_feedback.jsonl`(和 changelog 同级)
  - **验收**：推荐后人拍板 → LLM 调此接口 → feedback 文件有新记录，字段完整

### Phase 2：推荐接口 + 统计接口
- **kg_scout_reuse**（推荐核心）：
  - 参数：`requirement`（需求描述），可选 `domain`
  - 内部：在所有 members 上用 requirement 对 name/scenarios/reuse_note 做**关键词匹配**(简单够用) 
    → 按相关度排序取 **top-5** → 只返回这 5 个 member(**扁平列表**,每个带所属 catalog 元信息) 
    → 自动过滤 deprecated 状态
  - 返回体不含可照抄配置串(D8),只给"能力名 + scenarios/reuse_note + match_reason"
  - **验收**：需求"连续登录7天发奖励" → 粗排命中 `LOGIN_GRANT` → 返回 1 个候选(§6.2 格式)

- **kg_get_reuse_stats**（统计聚合，可选实现）：
  - 参数：`catalog_id` 可选(不填返回全局统计)
  - 内部：读 `reuse_feedback.jsonl` → 聚合每个 member 的推荐次数/采纳次数/采纳率/最近推荐时间 
    → 按阈值分级标注(推荐<3次="待验证" / ≥10次且采纳率>70%="高置信")
  - **验收**：有 feedback 后调此接口 → 返回统计 JSON，分级标注正确

### Phase 4：Skill 触发规则
- 扩展 `kg-consult.skill.md`：新增"复用推荐步骤"
  - **触发**：用户要"加一个 X""实现能做 Y 的功能"(造新行为,非改造)→ kg-consult skill 触发
  - **顺序**：**复用推荐前置**(分诊闸门,在事实查询前)→ LLM 判域 → 调 kg_scout_reuse
  - **匹配**：LLM 拿到 top-k 候选 → 通读 scenarios/reuse_note 做语义判断 → 按 D4 分级(recommend/reference)
  - **转述纪律**：**必须转述给人 + 给选项**(A复用/B新增/C理解错) → 等人拍板才进下一步
  - **反馈**：人拍板后 LLM 调 kg_report_reuse_outcome 记 feedback
  - **例外**：需求已点名具体机制 → 跳过 scout
- **验收**：模拟需求触发 skill → LLM 正确调 scout → 转述推荐 → 人拍板后记 feedback

### Phase 5：文档 + 发版
- 更新 DEVELOPMENT.md：补反馈闭环机制 + 两方向分工
- 更新 DESIGN.md：经验层定位 + 推荐安全契约
- bump VERSION=2.4.0；CHANGELOG 顶部加条目(MINOR：新增 3 工具 + 反馈机制，旧图谱兼容)
- commit + tag v2.4.0 + push

**第二批:可视化增强（已完成 ✅）**

### Phase 3：kg-view 可视化扩展 ✅
- `gen_graph_html.py` 扩展（已完成）：
  - `load_data` 识别能力目录（有 `x_capability_members`）→ type=capability_catalog，
    合并 `get_reuse_stats` 的复用统计到每个成员
  - 前端：能力目录渲染成**金边菱形**节点（区别于普通 entry）
  - 点击能力目录 → 详情面板显示：来源枚举 + 成员列表，每个成员带
    **统计徽章**(推荐 X · 复用 Y · 采纳率 Z% + 分级 待验证/一般/高置信)、
    reuse_note 边界警告、scenarios 标签；deprecated 成员置底半透明标注
- 能力目录通过 `related` 字段**手动关联**到 entry(先看效果,不行再改自动)
- **验收 ✅**：VizTest 2 例——load_data 输出能力目录节点+成员统计正确、
  静态 HTML 含全部标记；高置信/deprecated 排序验证通过

---

## 6. 数据模型与适用规则

### 6.1 能力目录（catalog）—— 模拟数据
```
catalog_id: "reward_grant_type"
name_cn:    "奖励发放方式"
domain:     "economy"
source:     { file: "examples/mock-src/RewardGrantType.java", symbol: "RewardGrantType" }
members: [
  { enum_value:"LOGIN_GRANT", id:3, name:"登录时发放",
    scenarios:["登录","上线发放","每日领取","签到"],           # LLM 分析代码填 + 人补充
    reuse_note:"无'连续/累计天数'维度；带'连续N天/累计'等计数条件的需求需新增计数逻辑" }
]
```
事实字段(enum_value/id/name)由 LLM 从正在读的代码里整理,语义字段(scenarios/reuse_note)由 LLM 起草 + 人补充确认。

### 6.2 推荐输出（scout 返回）—— 模拟数据
```
{
  "candidates": [
    {
      "catalog_id": "reward_grant_type",
      "catalog_name": "奖励发放方式",
      "domain": "economy",
      "member": {
        "enum_value": "LOGIN_GRANT",
        "id": 3,
        "name": "登录时发放",
        "scenarios": ["登录", "上线发放", "每日领取", "签到"],
        "reuse_note": "无'连续/累计天数'维度；带'连续N天/累计'等计数条件的需求需新增计数逻辑"
      },
      "match_reason": "scenarios 命中'登录',与需求'连续登录7天'相关"
    }
    // 粗排最多返回 top-5 个最相关 member(扁平列表),这个例子只有 1 个够相关
  ],
  "total_matched": 1,
  "hint": "以上是粗排后的相关候选。LLM 精细判断:需求是否有 reuse_note 警告的超限定词?按 D4 分级(recommend/reference)。"
}
```

接口只做粗排(关键词匹配 top-k),LLM 做精排(语义判断+分级)。不返回可照抄配置串(D8)。

### 6.3 适用规则（哪些目录该进经验层）—— 同时满足三条
1. **行为变体集合**：每个成员代表一种可配置的不同行为，不是纯数据标签。
2. **被分发/配表消费**：`switch(type)` / 配表字段选行为 / 脚本注册表。
3. **需求方描述而非点名**（主判据）：用"行为描述"提需求，不知道枚举名。

- ✅ 符合：奖励发放方式、通知触发方式、任务条件类型等"行为变体枚举"
- ❌ 不符合：伤害类型、地图对象类型、协议消息枚举等纯数据标签（属事实层，归 kg_query）

---

## 7. 校验规则（validate.py 扩展）
- 基础结构校验：必填字段(catalog_id/name_cn/domain/members)存在、类型正确。
- `members` 非空，每个 member 至少有 `enum_value`(其余字段可选)。
- `scenarios` 为空的 member = INFO（未启用推荐匹配,提示补语义字段）。
- `source` 存在时作为溯源线索保留,便于人工核对,但**不做源码交叉校验**(D2 已改)。

## 8. 版本与跨项目发布闭环
1. 在 KPKnowledgeGraph 改 `tools/` + `skills/`，本地测（Phase 1-2 接口 + §9 回归）。
2. bump `VERSION` → 2.4.0；`CHANGELOG.md` 顶部加条目（MINOR：新增 3 工具 + 反馈机制 + 能力目录字段，旧图谱兼容）。
3. `git add -A && git commit -m "release v2.4.0: 能力目录 + 复用推荐 + 反馈闭环" && git tag v2.4.0 && git push && git push --tags`
4. 使用方项目侧：`python .claude/kg/tools/kg_admin.py update`（数据不动，仅升级工具）。
5. 验证：录入模拟数据 `RewardGrantType`，跑 §9 回归确认推荐行为正确 + feedback 记录生效。
   （真实项目采用时，把示例映射到自己项目的对应枚举，回归结构不变。）

## 9. 验证策略（回归用例，用模拟数据表达）
四轮子代理对照实验的结论，用模拟数据 `RewardGrantType` 固化为回归基准：

- **RC-1 正向复用**：需求"玩家上线时发每日登录奖励" → scout 粗排返回 LOGIN_GRANT → LLM 判定 recommend → 转述给人 → 人选复用 → 记 feedback(decision=reuse)。
- **RC-2 假朋友（关键）**：需求"玩家**连续登录7天**后发奖励" → scout 粗排返回 LOGIN_GRANT → LLM 读 reuse_note 发现"无连续/累计天数维度"、需求含"连续7天"超限定词 → 判定 **reference + 边界警告** → 转述"可复用发放触发,但连续天数计数需新增"。
  （ground truth：发放方式枚举无"连续/累计天数"维度，正确答案是需新增计数逻辑。）
- **RC-3 已点名跳过**：需求点名"用 LOGIN_GRANT" → scout 不触发(kg-consult skill 识别已点名)。
- **RC-4 事实准确性**：录入的 members 事实字段由 LLM 从实际代码整理 + 人工确认,source 溯源线索完整。
- **RC-5 反馈闭环（新增）**：推荐后人拍板 → LLM 调 kg_report_reuse_outcome 记 feedback → reuse_feedback.jsonl 有新记录(字段完整:requirement/catalog_id/member/decision/ts) → 调 kg_get_reuse_stats 返回统计(推荐次/采纳次/采纳率) → 分级标注正确(推荐<3="待验证" / ≥10且采纳率>70%="高置信")。

> RC-2 是本特性的**安全红线**：推荐制造"激进错判"（把该新增的当配表）的风险，
> 必须被边界警告拦住。上线前此用例必须通过。
>
> 原始实验（真实项目内部进行）与此同构：动作命中现成能力、但需求多一个
> 该能力配不出来的限定词。此处用模拟数据复现同一结构，不含任何专有信息。

> RC-2 是本特性的**安全红线**：推荐制造"激进错判"（把该新增的当配表）的风险，
> 必须被边界警告拦住。上线前此用例必须通过。
>
> 原始实验（真实项目内部进行）与此同构：动作命中现成能力、但需求多一个
> 该能力配不出来的限定词。此处用模拟数据复现同一结构，不含任何专有信息。

## 10. 风险与非目标
- **风险**：经验层召回率 = 目录覆盖度 × scenarios 质量。scenarios 人工缺失 →
  推荐失效退回原始问题。缓解：validate 报覆盖缺口 + 增量补录。
- **风险**：写入侧规则若太严，候选目录漏记 → 推荐无米下锅。缓解：写入侧宁滥勿缺，人过滤。
- **非目标**：不做"校验需求方点名的类型是否用错"（那是另一个特性，别和推荐混）。
- **非目标**：不自动改代码；推荐永远经人决策。

---

## 附：开工前置
- 设计决策 §3（D6/D7/D8）已确认。
- 从 Phase 1（枚举解析函数）起步——它最底层、单测即可验、不依赖任何其他阶段。
