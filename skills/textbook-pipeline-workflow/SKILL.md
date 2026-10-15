---
name: textbook-pipeline-workflow
description: "13-state textbook authoring pipeline workflow: state definitions, phase gates, error escalation (E1-E5), handoff contract, and anti-hallucination closed loop. Load when orchestrating a full chapter or when any pipeline state/gate decision is unclear. Trigger words: 编排章节 / 流程卡在哪个阶段 / 下一步该干嘛 / 13态 / 状态机 / 门禁 / 返修回哪 / handoff 字段."
version: 1.2.0
---

# textbook-pipeline-workflow — 13 态教材编写流水线

> 转换自 content-forge v5 `schemas/state_machine_v2.yaml`（13 态 SSOT）。本 skill 是团队编排的权威流程参考，主理人与成员按需加载。

## 何时使用

- 启动/推进任一章节编写流程（W1 全流程）
- 判断当前处于哪个状态、下一步允许去哪
- 门禁不通过时决定返工目标
- 跨阶段交接时核对 handoff 契约

## 工作根目录约定（WORK_ROOT）

**所有路径相对 WORK_ROOT，由主理人在 CLARIFY 阶段确定并写入每个成员的任务指令。成员一律不猜路径；未收到 WORK_ROOT 的成员应回问主理人而非自行假设。**

```
{WORK_ROOT}/
├── 章节/{ch##}/
│   ├── chapter_design.md          # 教学设计（didactic-architect）
│   ├── draft.md                   # 章节正文（subject-writer）
│   ├── review/round{N}_report.md  # 审查报告（quality-examiner）
│   └── figures/{图号}.md          # 图表代码（visual-instructional-designer）
├── 知识库/retrieval/
│   ├── {ch##}_{英文slug}.md       # 检索摘要（literature-scout）
│   └── RETRIEVED.md               # 知识沉淀库（append，缓存优先来源）
└── 交付/{教材名}_{ch##}.md         # 最终交付稿（主理人装配）
```

命名规则：章节号两位数字（`ch01`）；topic 用英文小写连字符 slug；图按 `图 {章}-{序}` 编号。

## 13 态状态机

```
BOOTSTRAP → INTAKE → CLARIFY → SPECIFY → RETRIEVE → PRODUCE → VERIFY
  → PROOFREAD → CONSOLIDATION → VISUALIZE → ASSEMBLE → DELIVER → LEARN
```

| 状态 | 职责人 | 产出 | 下一合法态 | 门禁 |
|------|--------|------|-----------|------|
| BOOTSTRAP | 主理人 | 工作目录初始化 | INTAKE/SPECIFY | 目录/规则文件就绪 |
| INTAKE | 主理人 | 材料清单 | CLARIFY/SPECIFY | — |
| CLARIFY | 主理人 | 3 句话需求摘要 | SPECIFY | 关键信息齐全 |
| SPECIFY | didactic-architect | chapter_design.md | RETRIEVE | 门禁 1：设计覆盖知识域 |
| RETRIEVE | literature-scout | retrieval/{chapter}_*.md | PRODUCE | 门禁 2：覆盖率/冲突率/时效性 |
| PRODUCE | subject-writer | draft.md（R1→R2→R3） | VERIFY | 数据标签齐全 |
| VERIFY | quality-examiner | 4 轮审查报告 + verdict | PROOFREAD / RETRIEVE / PRODUCE | 4 轮全 pass |
| PROOFREAD | quality-examiner | 校对后稿 | CONSOLIDATION | 清洁无流程标注 |
| CONSOLIDATION | 主理人 | 统稿后全章 | VISUALIZE | 术语/编号一致 |
| VISUALIZE | visual-instructional-designer | 图表代码包 | ASSEMBLE | 图文一致 |
| ASSEMBLE | 主理人 | 装配稿 | DELIVER | 组件齐全 |
| DELIVER | 主理人 | 交付物 + 质量报告 | LEARN | present_files 完成 |
| LEARN | 主理人 | 经验沉淀记录 | （终态） | — |

### VERIFY 内部 4 轮循环（不是 4 个独立态）

R1 结构 → R2 深度 → R3 数据+引用 → R4 风格。任一轮 fail → 回 PRODUCE 返修；R4 pass → PROOFREAD。

## 检索门禁（三重规则）

- **门禁 1（SPECIFY 后）**：设计的知识域均有对应检索计划
- **门禁 2（RETRIEVE 后）**：
  - 覆盖率：设计所需数据点 ≥80% 有证据（或已标待核实）
  - 冲突率：多源冲突数据 <20%，冲突项已列明
  - 时效性：流行病学数据近 10 年占比 ≥80%
  - fail → 换关键词重检（≤2 轮）→ 仍 fail → 转用户手动指定

## 错误升级协议（E1-E5）

| 级别 | 触发 | 动作 |
|------|------|------|
| E1 工具失败 | 单工具不可用 | 自动降级备用（如 PubMed→CrossRef），重试 ≤3 |
| E2 可恢复 | 流程受阻但可绕行 | 上报主理人，60s 无进展升级 E3 |
| E3 门禁失败 | P1 违规/幻觉引用 | 终止当阶段，等用户裁决 |
| E4 需人工 | 方向性决策 | 记录状态，通知用户 |
| E5 灾难 | 全链路不可用 | 熔断保存现场，上报 |

## Handoff 契约（跨阶段交接必含）

`{当前状态, 上一完成态, 轮次计数, 遗留 blocking 数, 读过的文件清单, 质量评分}`——缺字段视为无效交接，接收方拒收。

## 防幻觉闭环

```
SPECIFY → 门禁1 → 检索（四层降级）
PRODUCE → 每声明可溯源（[实]/[估]/[引]/[待核实]）
VERIFY R3 → citation-verify 逐条核验 → 查无此文即删
缺口 → H15：reviewer 上报 → 主理人派检索 → 回填 → 复核
```

## 与原 v5 状态机的差异说明

- 原 `tb-educator`/`designer` 两角色合并为 `visual-instructional-designer` 单成员
- 原 `tb-question-bank` 题库生成并入 subject-writer 职责（习题位标注 + 按需生成）
- 原 `tb-export-docx`（pandoc 导出）由主理人在 DELIVER 阶段按需执行，不设独立成员
- 13 态 SSOT 映射关系保留，成员职责按 WorkBuddy 团队协作模型（SendMessage 回传）重排

---

## 介入协议（Phase E 打回数 = 2 时，主理人按此执行）

> 从 team-lead 拆入（evo-11）。触发条件：同一问题打回数达到 2。

**打回计数口径**：
- 「打回轮次」按**同一问题**计：返修后复审，若该问题仍在（含改而未净），打回数 +1
- **计数键防逃逸**：同一问题 = `correlation_id + 问题指纹（blocking 违反项类型 + 证据位置）`，**跨 task_id 累计**——换 task_id（R2→R2b）不重置

**介入动作序列（按序执行，逐级升级）**：
1. **诊断归类**：读 examiner 该项 blocking 证据 + writer 返修响应，判定根因——{A 证据缺失 / B 理解偏差（指令歧义）/ C 能力边界 / D 故意抵抗（罕见）}
2. **按根因处置**：
   - A → 转 literature-scout 补检索后回填
   - B → 主理人重写返修指令（给具体改法示例，不复述 examiner 原话）
   - C → 主理人拆解为更小子步骤；**可给 ≤3 句改法示范（指出位置+方向），禁止输出可直接交付的连续正文**——整合仍由 writer 完成（代写边界条款）
   - D → 停下通知用户
3. 处置后送第 3 轮审查；第 3 轮仍失败 → 停下通知用户（附 3 轮证据链）

「3 轮无进展」= 同一问题 2 次介入处置后仍未通过 → 立即停止。
每轮打回与介入动作记入 `章节/{ch##}/review/interventions.md`（时间/问题/根因/处置/结果）。

---

## 统稿 checklist（Phase G 逐项过，任何一项不过回对应成员）

> 从 team-lead 拆入（evo-11）。

1. **术语一致**：全章同一概念无多种写法；对照教材术语表（如有）——可委托 examiner 抽查，主理人核结论
2. **编号连续**：图表号 `图{章}-{序}` 与习题位节号无跳号/错位
3. **引用格式统一**：全部 `[实]` 条目「来源: PMID/DOI」格式一致
4. **正文清洁**：无流程标注残留（TODO、写作过程说明、测试标记）
5. **遗留清单**：全部 `[待核实]` 汇总成表附交付物末尾
6. **净字数达标**：以 `scripts/count_net_words.py --target <目标>` SSOT 脚本值为准（P2-4），偏差超出 ±5% → 回 writer 补齐或经用户同意放宽（原「>20%」口径与验收门禁 1200±5% 矛盾，2026-10-15 统一）

装配：draft + 图表 + 习题 → `交付/{教材名}_{ch##}.md`（Markdown 优先，按需转 DOCX）。交付时附质量报告（引用核验率/覆盖度/[待核实] 清单/interventions 摘要）。
