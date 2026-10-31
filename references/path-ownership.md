---
name: path-ownership
description: "路径归属表（SSOT）——每个可写路径的唯一归属者、允许动作与冲突仲裁规则。harness SKILL.md §0「并行安全：路径表唯一归属」与「资源冲突」仲裁条款指向本表。spawn 前/并行派工前必读。"
version: 1.0.0
---

# 路径归属表（path-ownership）

> **为什么存在**：`skills/agent-harness-protocol/SKILL.md` §0 的两处条款——「并行安全：同一文件同一时刻只有一个写者（**路径表唯一归属**）」与「资源冲突：路径表唯一归属；后写者阻塞重定向」——都引用了「路径表」，但本表此前**不存在**，仲裁规则指向空气（横向归因 ②）。本文件即那张表。

## 1. 归属原则

1. **一路径一写者**：每个路径有且仅有一个归属者；非归属者写入 = 越界产出，按 harness「契约三原则②」视同未产出，编排者拒收。
2. **只读不写**：归属者可写；其他成员最多只读。
3. **编排者例外**：`smart-textbook-team-team-lead` 可写全部 `交付/`、`运行态/` 与 `章节/{ch##}/review/interventions.md`（介入记录属编排权），但**不得写成员产出文件**（代写边界条款）。
   > **2026-10-30 批次 D 修正**：旧表把 `figures/assets/` 整目录归 designer，
   > 但实际写入方是 `build_manuscript.py`（编排者在 ASSEMBLE 阶段执行）→ **表与实现冲突**
   > → designer 明明没写却被判越界。现按**文件类型**细分：源码（.mmd/.svg）与
   > 数据图代码（.ipynb）归 designer，栅格化产物（.png/.pdf）归编排者。
4. **并行派工前置检查**：派两个及以上成员并行前，编排者须核对本表——目标路径归属不同才允许并行；归属相同则必须串行。

## 2. 归属表

| 路径（相对 `{WORK_ROOT}/`） | 唯一归属者 | 允许动作 | 其他成员 |
|---|---|---|---|
| `章节/{ch##}/chapter_design.md` | didactic-architect | 写/改 | 只读 |
| `知识库/retrieval/{ch##}_{slug}.md` | literature-scout | 写/改 | 只读 |
| `知识库/retrieval/RETRIEVED.md` | literature-scout | **append**（禁覆盖/删） | 只读 |
| `章节/{ch##}/sections/{节号}.md` | subject-writer | 写/改（节级正文，批次 C4 新增） | 只读 |
| `章节/{ch##}/gaps.md` | didactic-architect | 写/改（缺口清单，批次 C9 新增） | 只读 |
| `章节/{ch##}/draft.md` | subject-writer | 写/改（版本 R1→R2→R3 递增；由 sections/ 拼接） | 只读；**examiner/designer 均不得直接修改**（修正意见走回传清单，由编排者转 writer） |
| `章节/{ch##}/review/round{N}_report.md` | quality-examiner | 写/改 | 只读 |
| `章节/{ch##}/review/r3_verification_log.md` | quality-examiner | append | 只读 |
| `章节/{ch##}/review/proofread.md` | quality-examiner | 写/改（校对后稿·带修订标记，v1.1.0） | 只读 |
| `章节/{ch##}/review/proofread_revisions.md` | quality-examiner | 写/改（修订记录+结论行，v1.1.0） | 只读 |
| `章节/{ch##}/review/interventions.md` | smart-textbook-team-team-lead | append | 只读 |
| `章节/{ch##}/figures/{图号}.md` | visual-instructional-designer | 写/改 | 只读 |
| `章节/{ch##}/figures/assets/{图号}.mmd/.svg` | visual-instructional-designer | 写（图表源码） | 只读 |
| `章节/{ch##}/figures/assets/{图号}.ipynb` | visual-instructional-designer | 写（数据图代码：原始数据+绘图同存，批次 C5 新增） | 只读 |
| `章节/{ch##}/figures/assets/{图号}.png/.pdf` | **smart-textbook-team-team-lead**（由 `build_manuscript.py` 栅格化/导出） | 写 | 只读 |
| `交付/`（全部） | smart-textbook-team-team-lead | 写/改（含审阅版 docx、溯源表、校稿结论节转写；v1.1.0） | **禁写** |
| `运行态/workflow-state.yaml` | smart-textbook-team-team-lead（写 `phase`/`circuit`/`budget`）；成员仅增量 patch `artifacts.<自己字段>` | 见左 | 只 patch 自身 `artifacts` 子树 |
| `运行态/progress.md` | smart-textbook-team-team-lead；成员经 `scripts/progress.py update` 写自己 phase 行 | upsert 自身 phase 行 | 禁改他人 phase 行、禁 init |
| `运行态/trace.jsonl` | 全体 append（各自 `record_trace.py`） | append | append（append-only，不冲突） |
| `运行态/dynamic-members.yaml` | smart-textbook-team-team-lead | 写/改（**须 `confirmed_by_user: true` 才生效**，批次 D 补登记） | 禁写 |
| `运行态/team-proposal-{ch##}.yaml` | smart-textbook-team-team-lead（由 `generate_team.py` 生成） | 写 | 禁写 |
| `学习/候补/` | smart-textbook-team-team-lead | 写/改 | 只读 |
| `学习/团队档案/` | smart-textbook-team-team-lead | 写/改（动态成员归档，批次 D 补登记） | 只读 |
| `.harness-runs/{task_id}/` | 由装配器与当次成员写 | 写 | 只读 |

## 3. 资源冲突仲裁（与 harness §0「冲突仲裁五类」对齐）

1. **同路径同时刻两写者** → 后写者**阻塞**（`BLOCKED`）并上报编排者，由编排者重定向到临时路径或改为串行；**禁止**同时写、禁止后写覆盖。
2. **非归属者已越界写入** → 产出视同未产出，编排者拒收并记入 `interventions.md`；文件由归属者决定保留/回滚。
3. **归属者缺席（成员 BLOCKED 未解除）** → 按 harness E3 处置；确需换人时，只有编排者可临时改派，且改派后路径归属随派工转移（不出现双写者）。
4. **目录级 vs 文件级冲突**：目录归属（如 `figures/`）内的新文件由该目录归属者创建；其他成员需要新增文件时上报编排者转派，不自建。

## 4. 变更记录

- v1.0.0 [2026-10-29] 初版：补上被 harness §0 引用但从未存在的「路径表」（横向归因 ②）；覆盖 15 条路径与 4 条仲裁规则。
- v1.1.0 [2026-10-30] 批次 C4/D 补正：
  - 新增 `sections/{节号}.md`（节级正文，归属 writer）
  - 新增 `figures/assets/{图号}.ipynb`（数据图代码，归属 designer）
  - **修正** `figures/assets/` 归属冲突：按文件类型细分（源码 vs 栅格化产物）
  - 新增 `运行态/dynamic-members.yaml`、`运行态/team-proposal-*.yaml`、`学习/团队档案/` 登记
  - 修正 `学习/候补/` → `学习/候补/`（拼音残留 typo，D-9）
  - 覆盖路径数 15 → 20
- v1.2.0 [2026-10-31] 修订态交付链（v1.1.0 方案甲）：
  - 新增 `review/proofread.md` + `review/proofread_revisions.md`（校稿三件套，归属 quality-examiner——修复 PROOFREAD「校对后稿」无人产出断链）
  - `交付/` 归属者动作扩写：含审阅版 docx 构建、溯源表自动生成、校稿结论节转写
  - 交付 docx 的 Word 修订态审改属审稿场景例外；**回流动作（--apply-revisions）归编排者**（docx 审改不改归属，改而不回流才违规）
