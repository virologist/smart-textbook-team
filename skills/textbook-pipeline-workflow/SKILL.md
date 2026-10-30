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
│   ├── sections/{节号}.md         # 节级正文（subject-writer）——大章节强制（批次 C4）
│   ├── draft.md                   # 章节正文（由 sections/ 拼接，subject-writer）
│   ├── review/round{N}_report.md  # 审查报告（quality-examiner）
│   │   └── r3_verification_log.md # 引用核验明细 → 溯源表来源
│   └── figures/{图号}.md          # 图表代码（visual-instructional-designer）
│       └── assets/{图号}.ipynb    # 数据图的原始数据+绘图代码（批次 C5）
├── 知识库/retrieval/
│   ├── {ch##}_{英文slug}.md       # 检索摘要（literature-scout）
│   └── RETRIEVED.md               # 知识沉淀库（append，缓存优先来源）
├── 运行态/                        # 黑板 / trace / 进度 / 动态成员注册表
│   ├── workflow-state.yaml        # 状态黑板 SSOT
│   ├── progress.md                # 续跑检查点（progress.py）
│   ├── trace.jsonl                # 每次成员调用一行
│   ├── dynamic-members.yaml       # 动态成员注册表（confirmed_by_user: true 才生效）
│   └── team-proposal-{ch##}.yaml  # 动态团队提案（未确认前不生效）
├── 学习/候补/{日期}_{ch##}_候补.yaml   # LEARN 候补池（≥3 候选或用户 ack 才合并）
└── 交付/
    ├── {教材名}_{ch##}.md         # 书稿【源格式】（主理人装配；唯一编辑入口）
    ├── {教材名}_{ch##}.docx       # 书稿【交付格式】（由 md 生成，禁止手改）
    └── {教材名}_{ch##}.溯源.md     # 溯源表（章节→证据→引用→文本位置；批次 C3）
```

> **交付形态（2026-10-30 修订）**：交付物是**大学教材书稿**，`.md` 为源、`.docx` 为交付格式。
> 规格 SSOT = `skills/manuscript-delivery/SKILL.md`；构建 = `scripts/build_manuscript.py`；
> 校验 = `scripts/check_manuscript.py`（门禁 4）。
> 原目录树只有 `.md` 一档，docx 长期只是「按需转」的软承诺且无实现（实测包内 0 命中 docx）。
>
> **目录树补全（批次 C4/C3，2026-10-30）**：此前本树只有 3 支（章节/知识库/交付），
> 而 `运行态/`（6 份 skill 引用）与 `学习/候补/`（learn-protocol 引用）**从未进过目录树**——
> 目录树是 WORK_ROOT 的 SSOT，缺支 = 成员按 SSOT 找不到运行态文件。
> 另：`sections/`（节级正文）、`assets/*.ipynb`（数据图代码）、`*.溯源.md`（溯源表）为新增支。

命名规则：章节号两位数字（`ch01`）；topic 用英文小写连字符 slug；图按 `图 {章}-{序}` 编号；
节号沿用教学设计的节号（如 `1.1`，落盘为 `sections/1.1.md`）。

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
| PRODUCE | subject-writer | sections/{节号}.md → draft.md（R1→R2→R3） | VERIFY | **门禁 3**（见下，2026-10-29 补判据） |
| VERIFY | quality-examiner | 审查报告（R1-R5）+ verdict | PROOFREAD / RETRIEVE / PRODUCE | 4 轮全 pass |
| PROOFREAD | quality-examiner | 校对后稿 | CONSOLIDATION | 清洁无流程标注 |
| CONSOLIDATION | 主理人 | 统稿后全章 | VISUALIZE | 术语/编号一致 |
| VISUALIZE | visual-instructional-designer | 图表代码包 | ASSEMBLE | 图文一致 |
| ASSEMBLE | 主理人 | 装配稿 + docx（md 源 → 双格式） | DELIVER | 组件齐全 + docx 构建成功 |
| DELIVER | 主理人 | 交付物 + 质量报告 | LEARN | **门禁 4 全 pass** + present_files 完成 |
| LEARN | 主理人 | 经验沉淀记录 | （终态） | — |

### VERIFY 内部审查循环（R1-R4 四轮 + R5 质量评分，不是独立态）

R1 结构 → R2 深度 → R3 数据+引用 → R4 风格+图文 → R5 质量评分（五维+80分红线）。任一轮 fail → 回 PRODUCE 返修；R5 pass → PROOFREAD。

## 检索门禁（三重规则）

- **门禁 1（SPECIFY 后）**：设计的知识域均有对应检索计划
- **门禁 2（RETRIEVE 后）**：
  - 覆盖率：设计所需数据点 ≥80% 有证据（或已标待核实）
  - 冲突率：多源冲突数据 <20%，冲突项已列明
  - 时效性：流行病学数据近 10 年占比 ≥80%
  - fail → 换关键词重检（≤2 轮）→ 仍 fail → 转用户手动指定

### 门禁 3（PRODUCE 后 · 内容门禁，2026-10-29 补）

> 此前 13 态表里 PRODUCE 行写「数据标签齐全」但**无判据、无 fail 处置**，VERIFY 的 4 轮审查实际承担了本应在进审查前就拦掉的低级缺陷（结构不全/字数不达/角色团未声明）→ 审查轮次被浪费。门禁 3 是可计算的前置闸。

主理人在 PRODUCE 收产出后、spawn examiner 之前**必须**过这四项，全 pass 才进 VERIFY：

| # | 判据 | 可计算口径 | fail 处置 |
|---|------|-----------|----------|
| 3.1 | **数据标签完整率** | 正文中凡含数值触发词（发病率/病死率/死亡率/剂量/浓度/免疫程序/日龄/效价/阳性率 等）的陈述，必须带 `[实]`/`[估]`/`[引]`/`[待核实]` 之一；**无标签率 = 0** | 回 writer 补标签；**禁止**由主理人代标 |
| 3.2 | **净字数达标** | `python3 scripts/count_net_words.py --target <目标> <draft.md>`，偏差 ≤±5%。**脚本值为唯一权威**，writer 自报值不作为判据 | 超 ±5% → 回 writer 补齐/删减；或经用户同意放宽并记录 |
| 3.3 | **角色团声明完整** | draft frontmatter 含 `角色团:`，每角色必带 `role_id`（kebab-case）+ `role_name` + `examines`（≥1 项）；role_id 取自 `references/role-assembly.md` | 缺/空 → blocking（role-assembly §5） |
| 3.4 | **图表位与习题位编号连续** | `[图 {章}-{序}]` 无跳号；习题位节号与设计 §C 一致 | 回 writer 对齐 |

**fail 一律回 PRODUCE 返修，不得带着 fail 进 VERIFY**；同一项 fail 2 次 → 按介入协议（A/B/C/D 根因）处置。门禁 3 结论记入 `运行态/progress.md` 的 PRODUCE 行摘要
（`progress.py` 已支持 `PRODUCE`/`VERIFY` 粗粒度别名 → 自动落到 PRODUCE-R3/VERIFY-R4 行）。

### 3.6 节级推进协议（批次 C4，2026-10-30 · 维度「编写/审稿/校稿颗粒度」）

> **缺口**：此前 PRODUCE 只能整章推进（`draft.md` 一把写），VERIFY 只能整章审
> （4 轮全在整章上）。单章 5 万字级稿子一次进 4 轮审查 → 上下文必然裁剪、
> 审查颗粒过粗（一个段落的用词问题与一个章节的结构问题在同一尺度上被裁决）。
> 用户明确要求：**以单个段落、单个节为最小单位推进单章，再做文件级拼接与跨章串联审稿**。

**触发条件**：章节字数目标 **> 8000 字** → **强制**节级推进；≤8000 字可整章推进。

**执行序列**：

```
① 节级撰写    subject-writer 逐节写 → 章节/{ch##}/sections/{节号}.md
② 节级自查    逐节过门禁 3.1/3.2/3.4 的**节内子集**（标签/字数/编号/交叉引用）
③ 文件级拼接  按 chapter_design §C 的节序拼接 → 章节/{ch##}/draft.md
              （拼接必须记录来源节号，便于返修定位）
④ 整章审查    quality-examiner R1-R4 在 draft.md 上跑（一次，不按节重复跑 4 轮）
⑤ 跨章串联审  多章成书时 → scripts/check_cross_chapter.py（术语/数据矛盾/重复）
```

**规则**：
- **节级自查不过，不得拼接**（避免把带缺陷的节拼成整章再返工）；
- **整章审查仍只跑一次**（节级不是「每个节跑 4 轮」，那会让审查轮次爆炸）；
- 返修时**只回改对应节**，不重写整章（返修粒度 = 节）；
- 门禁 3.2 净字数在**拼接后**统一校验（节级只做相对量级自查）；
- 路径归属：`章节/{ch##}/sections/` 归 subject-writer 写（须登记进 path-ownership 表）。

**可观察判据**：大章节若只见整章 `draft.md` 而无 `sections/` 目录 → 门禁 3 advisory
（记录「建议节级推进」）； Examiner R1 应能核到节级文件。

### 外部学科规范注入协议（B7，2026-10-30）

> **缺口**：13 态门禁此前全部是**学科中立的结构性判据**（覆盖率/标签/字数/编号），
> 没有任何一条能校验「本章内容是否符合该专业的**专业规范**」——
> 跨专业复用时，专业准确性这一维度实际上无人看守。

**注入方式（三选一，优先级从高到低）**：

| 来源 | 位置 | 适用 |
|---|---|---|
| 1. 学科 profile | `references/profiles/{discipline}.md` §2 术语权威源 / §3 核验源清单 | 默认路径，随包分发 |
| 2. 用户提供的标准文档 | `{WORK_ROOT}/学科标准/{文件名}.md`（教学大纲/课程标准/行业规范） | 用户有明确依据时 |
| 3. profile 外挂规范 | `{WORK_ROOT}/学科标准/profile-overrides.md` | 对内置 profile 做局部修正 |

**门禁 3 的专业规范挂载点（3.5）**：
若上述任一来源提供了**可判定条目**（术语表 / 必须覆盖的知识点清单 / 禁用表述清单），
主理人在过门禁 3 时**追加**该项：

| # | 判据 | 口径 | fail |
|---|------|------|------|
| 3.5 | 专业规范符合性 | 对照注入的术语表/知识点清单逐条检查；**未提供可判定条目则该项自动 N/A（不阻塞）** | 回 writer 修正 |

**硬规则**：
- 外部规范**只作判据，不作内容来源**——不得把外部文档内容直接复制进正文（那是检索与撰写阶段的职责，且涉及著作权）
- 外部规范缺失或不可判定 → 门禁 3.5 记 N/A 并在质量报告声明，**不得因此阻塞交付**
- 规范之间存在冲突 → 按 profile > 用户文档 > overrides 的优先级取，并在 interventions.md 记录冲突点

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
SPECIFY → 门禁1 → 检索（五层降级，Tier 0 本地知识源先行）
PRODUCE → 每声明可溯源（[实]/[估]/[引]/[待核实]）
VERIFY R3 → citation-verify 逐条核验 → 查无此文即删
缺口 → H15：reviewer 上报 → 主理人派检索 → 回填 → 复核
```

## 与原 v5 状态机的差异说明

- 原 `tb-educator`/`designer` 两角色合并为 `visual-instructional-designer` 单成员
- 原 `tb-question-bank` 题库生成并入 subject-writer 职责（习题位标注 + 按需生成）
- 原 `tb-export-docx`（pandoc 导出）由主理人在 **ASSEMBLE** 阶段执行，不设独立成员；
  实现为 `scripts/build_manuscript.py`（pandoc + python-docx + mermaid 栅格化，含三级降级）。
  （2026-10-30 修订：该职责此前被写成「按需执行」但无任何实现，且 team-lead 引用了
  不存在的 `scripts/build_chapter.py` 与虚构的 CHANGELOG 出处——现已兑现并勘误）
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
