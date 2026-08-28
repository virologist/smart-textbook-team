---
name: textbook-pipeline-workflow
description: "13-state textbook authoring pipeline workflow: state definitions, phase gates, error escalation (E1-E5), handoff contract, and anti-hallucination closed loop. Load when orchestrating a full chapter or when any pipeline state/gate decision is unclear."
version: 1.0.0
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
