---
name: path-ownership
description: "路径归属表（SSOT）——每个可写路径的唯一归属者、允许动作与冲突仲裁规则。harness SKILL.md §0「并行安全：路径表唯一归属」与「资源冲突」仲裁条款指向本表。spawn 前/并行派工前必读。"
version: 1.5.0
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
5. **同路径双写者须仲裁**（2026-11-04 P2 批次补）：`{图号}.png` 是本表唯一的双写者路径（designer 的 notebook 导出 vs 编排者的 mmdc 栅格化）。仲裁规则：
   - **数据图**（有 `{图号}.ipynb`）→ 归 designer 的 notebook 产物；`build_manuscript.py` 走「轨道B 直接收编」，**不再二次栅格化**（`rasterize()` 中 `kind == "data-png"` 分支先于 mmdc）；
   - **概念图**（无 `.ipynb`，源码在 md ```mermaid 代码块）→ 归编排者的 mmdc 栅格化产物；
   - 两侧**不得同时写同一个 `{图号}.png`**——若检测到数据图既有 notebook 产物又有 mmdc 产物，属越界产出，按 §3.2 处置（编排者保留数据图产物，mmdc 产物不落盘）。

## 2. 归属表

| 路径（相对 `{WORK_ROOT}/`） | 唯一归属者 | 允许动作 | 其他成员 |
|---|---|---|---|
| `章节/{ch##}/chapter_design.md` | didactic-architect | 写/改 | 只读 |
| `知识库/retrieval/{ch##}_{slug}.md` | literature-scout | 写/改 | 只读 |
| `知识库/retrieval/RETRIEVED.md` | literature-scout | **append**（禁覆盖/删） | 只读 |
| `章节/{ch##}/sections/{节号}.md` | subject-writer | 写/改（节级正文，批次 C4 新增） | 只读 |
| `章节/{ch##}/拼接清单.json` | smart-textbook-team-team-lead（由 `assemble_sections.py` 生成，E4 登记） | 写 | 只读 |
| `章节/{ch##}/合并检查清单.json` | smart-textbook-team-team-lead（由 `merge_sections.py` 生成，2026-11-04 P1 登记；记录 C1-C6 合并后必检结论 + 下游相位 `downstream_phase`） | 写 | 只读 |
| `章节/{ch##}/gaps.md` | didactic-architect | 写/改（缺口清单，批次 C9 新增） | 只读 |
| `章节/{ch##}/chapter_design_v1.md` | **smart-textbook-team-team-lead**（B3：门禁 1 后 `cp` 一次） | 写一次后**只读冻结**（共享锚基准） | **禁写**（含 architect；改它 = 篡改基线） |
| `章节/{ch##}/draft_r1_frozen.md` | **smart-textbook-team-team-lead**（B3：VERIFY-R1 pass 后 `cp` 一次） | 写一次后**只读冻结**（结构冻结点❄ 基准） | **禁写**（含 writer；改它 = 篡改基线） |
| `运行态/knowledge_anchor_{ch##}.json` | smart-textbook-team-team-lead（由 `parallel_gate.py anchor` 生成，B3） | 写（含 `baseline_ids`，门禁 2 读它） | 只读 |
| `运行态/visual_drift_{ch##}.json` | smart-textbook-team-team-lead（由 `parallel_gate.py visual-drift` 生成，B3） | 写（含变更率决策与 `learn_signal`） | 只读 |
| `章节/{ch##}/draft.md` | subject-writer | 写/改（版本 R1→R2→R3 递增；由 sections/ 拼接） | 只读；**examiner/designer 均不得直接修改**（修正意见走回传清单，由编排者转 writer） |
| `章节/{ch##}/review/round{N}_report.md` | quality-examiner | 写/改 | 只读 |
| `章节/{ch##}/review/r3_verification_log.md` | quality-examiner | append | 只读 |
| `章节/{ch##}/review/proofread.md` | quality-examiner | 写/改（校对后稿·带修订标记，v1.1.0） | 只读 |
| `章节/{ch##}/review/proofread_revisions.md` | quality-examiner | 写/改（修订记录+结论行，v1.1.0） | 只读 |
| `章节/{ch##}/review/interventions.md` | smart-textbook-team-team-lead | append | 只读 |
| `章节/{ch##}/figures/{图号}.md` | visual-instructional-designer | 写/改 | 只读 |
| `章节/{ch##}/figures/assets/{图号}.mmd` | visual-instructional-designer | 写（图表源码：Mermaid） | 只读 |
| `章节/{ch##}/figures/assets/{图号}.svg` | **smart-textbook-team-team-lead**（由 `build_manuscript.py` 从 md ```svg 代码块落盘，见 `write_source_assets()`） | 写（SVG 矢量直嵌 docx，不经 mmdc） | 只读 |
| `章节/{ch##}/figures/assets/{图号}.ipynb` | visual-instructional-designer | 写（数据图代码：原始数据+绘图同存，批次 C5 新增） | 只读 |
| `章节/{ch##}/figures/assets/{图号}.pdf` | visual-instructional-designer | 写（数据图印刷矢量：由 `{图号}.ipynb` cell4 导出，见 `skills/scientific-figure` §①③④） | 只读 |
| `章节/{ch##}/figures/assets/{图号}.png` | **双写者·需仲裁**（① designer：`{图号}.ipynb` cell4 导出预览图；② team-lead：`build_manuscript.py` 的 mmdc 栅格化产物） | 写 | 只读 |

> M3 修正记录（B6）：本行原写作 `.png/.pdf`——所声明的 PDF 产出属虚构职责（B-12，
> 反查无对应实现），已对齐 D-11 口径改为 PNG 栅格 + SVG 矢量直嵌。
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
- v1.3.0 [2026-11-04 P2 文档一致性批次]：
  - **修正 `.svg` 双归属冲突**（原 L39 designer 源码 vs L41 team-lead 导出，两行同时声明 `.svg` → 同一路径两个归属者 = 并行安全条款失效）。
    依据 `scripts/build_manuscript.py` 的真实写入行为裁定：`write_source_assets()` 把 md 中的 ```svg 代码块落盘为 `{图号}.svg`
    （`ext = "mmd" if kind == "mermaid" else "svg"`），写者是**编排者**而非 designer；
    且 `rasterize()` 对 `kind == "svg"` 直接 `a["png"] = a["src"]`（SVG 矢量直嵌 docx，不经 mmdc）→ `.svg` 不是栅格化产物。
    故拆为：`.mmd` 归 designer / `.svg` 归 team-lead。
  - **恢复 `.pdf` 归属**：原 L43 的 M3 修正记录称「PDF 产出属虚构职责（B-12）」并删掉 `.pdf` 归属，但
    `skills/scientific-figure` §① cell4 明确要求导出 `{图号}.pdf`（印刷矢量），CI「数据图执行级门禁」也断言
    `fig.savefig('1-1.pdf')` 真实产出 → `.pdf` **确有实现**，删除归属导致该路径无主（谁写都算越界）。
    现归 designer（与 `.ipynb` 同源，由 notebook 导出）。
  - **`.png` 显式标注为双写者**并新增 §1.5 仲裁规则：数据图归 notebook 产物（`rasterize()` 轨道B 先于 mmdc，
    不二次栅格化）；概念图归 mmdc 栅格化产物；两侧不得同时写同一 `{图号}.png`。
  - 覆盖路径数 20 → 22
- v1.4.0 [2026-11-04 P1 批次：拆分-合并链路]:
  - 新增 `章节/{ch##}/合并检查清单.json`（归属 smart-textbook-team-team-lead，
    由 `scripts/merge_sections.py` 生成）——该文件承载「超上下文拆分 → 合并 →
    合并后必检」（Q3 三动作）的结论，含 C1-C6 六项检查的 blocking/hints 分布、
    `sections_merged` 合并溯源、以及**下游相位** `downstream_phase`（默认 `VERIFY-R3`）。
    此前 `assemble_sections.py` 的 `拼接清单.json` 只覆盖**节内**自查，
    节与节之间的衔接（术语漂移/图位冲突/数据口径打架）无产物承载 → 无主路径。
  - 归属理由：合并由编排者执行（Q3「拆分分别执行完成后再合并」），检查清单是
    合并动作的产物，故与 `拼接清单.json` 同归编排者；成员只读。
  - 覆盖路径数 22 → 23
- v1.5.0 [2026-11-04 B3 批次：搭接并行]:
  - 新增 4 条路径：`chapter_design_v1.md` / `draft_r1_frozen.md`（两份**只读冻结快照**）
    + `运行态/knowledge_anchor_{ch##}.json` / `运行态/visual_drift_{ch##}.json`
    （`scripts/parallel_gate.py` 的两份决策报告）。
  - 归属理由：四者都是**主理人裁决动作**的产物，不是成员产出——快照由主理人在
    门禁 1 / VERIFY-R1 pass 当轮 `cp` 一次后冻结，报告由主理人跑裁决门生成。
    若归 architect/writer，会出现「并行中被写者覆盖基准」的撕裂（B3 升级 A/C 的核心风险）。
  - **§1 第 4 条并行前置检查的 B3 落地结论**：`SPECIFY-refine`（写 `chapter_design.md`，归 architect）
    与 RETRIEVE（写 `知识库/retrieval/*`，归 scout）目标归属不同；`VISUALIZE-spec`（写 `figures/`，
    归 designer）与 VERIFY-R2/R3 返修（写 `draft.md`，归 writer）目标归属不同 ⇒ 两组均**允许并行**。
    并行双方读的是只读冻结快照，不构成第二写者。
  - 覆盖路径数 23 → 27
