---
name: task-router
version: 1.0.0
description: "Structured task dispatch for the Smart Textbook Team. Defines task_type enum (12 types) with member routing table, confidence scoring, escalation rules, and offline eval harness. Load BEFORE any member dispatch to make task→member routing explicit and auditable. Trigger words: 路由 / dispatch / 派活 / task_type / 谁来做 / 调谁."
---

# task-router — 结构化任务路由

> 解决"问法歧义→分派错位"问题。把 team-lead 的 6 行关键词路由表升级为 **task_type schema + 决策表 + 置信度升级**。
> 路由器本质：把"用户口语化问法"映射成 12 个标准 task_type 之一，再查表派活。

---

## 0. 何时使用

| 场景 | 是否加载 |
|---|---|
| 调度任何成员前 | ✅ 必加载（Phase B/C/D/E/F 每次 spawn 前） |
| 用户单问法路由（"X 是什么"） | ✅ 加载 |
| 已知成员 ID 直接 dispatch | ⚪ 可选（已知 task→member 对应可直接派，但仍建议标注 task_type 便于 trace）|
| 已 spawn 同 task 复审或返修 | ❌ 不需要（走 envelope 接力）|

---

## 1. task_type 枚举（12 类，SSOT）

| task_type | 中文 | 责任成员 | 输入信号 | 输出契约 |
|-----------|------|---------|---------|---------|
| `design-bloom` | 教学设计（Bloom + 块级 DAG） | didactic-architect | 教材名/受众/章节主题/课时数 | `chapter_design.md` |
| `design-review` | 教学设计复审 | didactic-architect | 现有 `chapter_design.md` | 设计评审 verdict |
| `retrieval-pmid` | 文献检索（PMID/DOI 优先） | literature-scout | 知识域关键词列表 / 缺口清单 | `retrieval/{ch}_{slug}.md` |
| `retrieval-standard` | 标准/法规检索（GB/WOAH/OIE） | literature-scout | 标准号 / 法规名 / 主题 | 标准溯源 + 现行版本核验 |
| `retrieval-wiki` | 知识沉淀（结构化入库） | literature-scout | 已核验的事实片段 | `RETRIEVED.md` 追加 |
| `write-skeleton` | 章节骨架（R1） | subject-writer | `chapter_design.md` + `retrieval/*` | `draft.md` (R1) 含要点占位 |
| `write-revise` | 章节充实（R2-R3） | subject-writer | `draft.md` (R1/R2) + 反馈 | `draft.md` (R2/R3) 含证据标签 |
| `review-structure` | 审查 R1（结构 / 框架） | quality-examiner | `draft.md` + `chapter_design.md` | R1 verdict + blocking |
| `review-depth` | 审查 R2（深度 / 内容） | quality-examiner | `draft.md` + 引用源 | R2 verdict + blocking |
| `review-citation` | 审查 R3（数据 + 引用核验） | quality-examiner | `draft.md` + 所有 `[实]/[引]` | R3 verdict + 引用核验表 |
| `review-style` | 审查 R4（风格 / 可读性） | quality-examiner | `draft.md` | R4 verdict + advisory |
| `visual-spec` | 图表规格 + 代码 | visual-instructional-designer | 图表位 `[图 X-X：...]` + `draft.md` | 规格卡 + Mermaid/SVG |
| `visual-review` | 图表审查（图与正文一致性）| visual-instructional-designer | 已产图表 + 最终 `draft.md` | 图文一致性 verdict |

> **扩展规则**：未覆盖的新场景（13+），按"输入信号"最相似者降级路由，并在 trace `task_type_custom=true` 标记。

---

## 2. 路由决策算法（4 步）

### Step 1：判定 task_type（必做）

```
输入：用户问法或任务描述
→ 匹配 §1 枚举的输入信号
→ 命中则标注 task_type
→ 不命中走 §3 升级规则
```

**匹配优先级**：精确匹配 > 关键词相似度 > 默认 fallback（见 Step 3）。

### Step 2：置信度评分（0-1）

| 评分依据 | 分值 |
|----------|------|
| 输入信号明确命中 task_type 描述 | +0.4 |
| 与已知样例（见 §4）语法高度相似 | +0.3 |
| task_type 默认责任成员当前空闲（无 blocking_open）| +0.2 |
| 任务边界清晰（输入/输出都明确）| +0.1 |

**总分 ≥ 0.7 → 直接 dispatch**
**总分 < 0.7 → 走 §3 升级**

### Step 3：默认 fallback（兜底用，不依赖置信度）

| 输入含以下关键词 | task_type |
|----------------|-----------|
| "设计" + "Bloom" / "大纲" | `design-bloom` |
| "检索" / "PMID" / "DOI" | `retrieval-pmid` |
| "标准" / "GB" / "WOAH" / "法规" | `retrieval-standard` |
| "写" / "起草" / "改" / "润色" | `write-revise` 或 `write-skeleton` |
| "审查" / "检查" / "核验"（数据/引用）| `review-citation` |
| "审查"（结构/深度）| `review-structure` / `review-depth` |
| "图" / "Mermaid" / "SVG" / "chart" | `visual-spec` |
| 其他模糊问法 | **升级 team-lead** |

### Step 4：派活前确认（dispatch checklist）

- [ ] task_type 已标注（写入 envelope `payload.task_type`）
- [ ] 责任成员当前 phase + blocking_open 已查（黑板查询）
- [ ] WORK_ROOT 已传入成员指令
- [ ] context_refs 路径已给（≤500 token 内联）
- [ ] 期望产出（输出契约）已声明
- [ ] 预期轮次 + 超时预算已声明
- [ ] 成员必须加载的 skill 已声明（如 `citation-verify` 对 `review-citation`）

---

## 3. 升级规则（confidence < 0.7）

### E1: 候选歧义（同一问法命中 ≥2 个 task_type）

**例**：用户说"看一下这章的引用"——可能是 `review-citation` 也可能是 `retrieval-standard` 补充。

**处置**：team-lead 追加 1 问澄清（≤1 轮）：
- "是已有 draft 的引用核验（review-citation），还是新检索标准（retrieval-standard）？"

### E2: 未知任务（无任何命中）

**处置**：team-lead 主动追加澄清询问用户，不直接 dispatch。

### E3: 成员当前阻塞（blocking_open 非空）

**处置**：换等价成员（无）+ 在 trace 记录 `outcome=BLOCKED` + 上报用户。

### E4: 跨 task_type 复合任务

**例**："帮我审一下这章，顺便补一下图"——含 `review-structure` + `visual-spec`。

**处置**：拆为两个独立 task 串行或并行（按依赖），**禁止合并为一个 member call**（违反职责边界）。

---

## 4. 已知样例（路由器训练样本）

| 用户问法（原文） | task_type | 置信度 |
|-----------------|-----------|--------|
| "设计第 6 章禽流感鉴别诊断" | `design-bloom` | 0.95 |
| "查一下 GB 19438 的现行版次" | `retrieval-standard` | 0.95 |
| "检索 H5N1 致病性最新文献" | `retrieval-pmid` | 0.90 |
| "写禽流感章节的骨架" | `write-skeleton` | 0.85 |
| "把 draft 充实一下，加证据标签" | `write-revise` | 0.85 |
| "审查 ch06 的结构" | `review-structure` | 0.90 |
| "核验所有 [实] 标签的 PMID/DOI" | `review-citation` | 0.95 |
| "画一张疫区封锁的决策树" | `visual-spec` | 0.90 |

> **离线 eval 基线**：20+ 用例命中率应 ≥ 80%（Apollo 类比：首过 20%→80%）。低于此基线即判定 router 需升级。

---

## 5. 与 dispatch 的接口

```yaml
envelope:
  v: "2.0"
  from: "smart-textbook-team-team-lead"
  to: "{member_id}"
  type: TASK
  task_id: "{ch##}-{phase}-{round}"     # 例: ch06-PRODUCE-R2
  correlation_id: "{ch##}"
  payload:
    task_type: "review-citation"        # ← 新增：本路由器的核心输出
    routing_confidence: 0.92            # ← 新增：便于 trace 与离线 eval
    routing_signals: ["PMID", "核验"]    # ← 新增：哪些信号触发了路由
    required_skills: ["citation-verify"]
    input: { ... 业务数据 ... }
    output_contract: { ... 期望产出 ... }
  context_refs: [...]
  state_patch: { ... 黑板增量 ... }
  ts: "ISO8601"
```

---

## 6. 离线评估（test_router_eval）

每章 DELIVER 后跑 `tests/test_router_eval.py`：
- 20+ 路由器训练样本（§4）
- 计算命中率 = 正确分派数 / 总样本
- 输出基线报告 → `docs/evals/router_baseline.md`

**门槛**：命中率 < 80% → 路由器需扩展（加更多训练样本或调整权重）。

---

## 7. Changelog

- v1.0.0 [2026-09-18] 初版：12 task_type 枚举 + 4 步决策算法 + 置信度升级 + 离线 eval harness
