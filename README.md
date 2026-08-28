# smart-textbook-team — 智能教材编写天团

> 转换自 content-forge v5 多 Agent 框架（tb-writer 项目），适配 WorkBuddy 专家团规范 v2.0。
> 版本 1.2.0 | 2026-08-28 | 作者 TZUVet
> 进化状态：A-Evolve 三轮进化 **0.830 → 1.000**（git tag: evo-2），154 项评测全通过

## 团队定位

十三态流水线编排的智能教材编写团队：教学设计 → 文献检索 → 章节撰写 → 四轮审查 → 统稿交付，引用核验零容忍防幻觉。

## 质量门禁（v1.2 进化要点）

1. **核验三要素**：引用可用 = 标识符存在 **+ 主题匹配** + 数据点可定位。
   「PMID 真实但研究主题与本章无关」判 P1 FAIL（实证案例：PMID:16809421 是肝病研究，曾差点混入禽病章节）
2. **WORK_ROOT 约定**：所有路径相对主理人给定的工作根目录；成员不得猜路径，未收到则回问
3. **工具降级链显式化**：PubMed MCP → `pubmed.ncbi.nlm.nih.gov/{PMID}/` → CrossRef，每级给到 URL 模板
4. **置信度可判定**：高 = Tier1 且 ≥2 源一致 / 中 = 单一可靠源 / 低 = 转载或 >10 年；判定不明就低不就高

## 成员

| 成员 ID | 花名 | 职责 |
|---------|------|------|
| smart-textbook-team-team-lead | 糜编澜（教材总编辑） | 13 态编排、三级门禁、熔断恢复、统稿交付 |
| didactic-architect | 陶靖衍（教学设计架构师） | Bloom 分层、块级 DAG、苏格拉底追问、章节大纲 |
| literature-scout | 粟海琼（文献检索专员） | 四层降级检索、Wiki 沉淀、[待核实] 标注 |
| subject-writer | 祝书白（学科内容撰写师） | R1→R2→R3 多轮撰写、数据来源标签、思政融入 |
| quality-examiner | 严正词（质量控制审查官） | R1-R4 四轮审查、引用逐条核验、结构化裁决 |
| visual-instructional-designer | 绘章图（可视化教学设计师） | 图表规格、Mermaid/SVG 产图、图文一致性 |

## Skills

- `textbook-pipeline-workflow` — 13 态状态机、门禁、E1-E5 错误协议、handoff 契约（转换自 schemas/state_machine_v2.yaml）
- `citation-verify` — PMID/DOI 零容忍核验（转换自 skills/knowledge/citation-verify）

## 预设 Workflow

- W1 全流程编写（默认）：设计→检索→撰写→审查→可视化→交付
- W2 只审查：四轮审查 + 引用核验
- W3 只检索：文献证据供应
- W4 补图：图表设计与生成

## 使用

WorkBuddy 专家中心选择「智能教材编写天团」即可启动。主理人糜编澜会先澄清需求（教材名/读者/章节/字数/时数），再按 SOP 推进。

## 与原 v5 框架的映射

| 原 v5 | 本团队 |
|-------|--------|
| tb-chief-editor | smart-textbook-team-team-lead（糜编澜） |
| tb-didactic-planner | didactic-architect（陶靖衍） |
| tb-researcher | literature-scout（粟海琼） |
| tb-writer | subject-writer（祝书白） |
| tb-reviewer | quality-examiner（严正词） |
| tb-educator + designer | visual-instructional-designer（绘章图） |
| schemas/state_machine_v2.yaml | skills/textbook-pipeline-workflow |
| skills/knowledge/citation-verify | skills/citation-verify |
