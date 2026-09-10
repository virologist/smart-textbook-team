# smart-textbook-team — 智能教材编写天团

> 转换自 content-forge v5 多 Agent 框架（tb-writer 项目），适配 WorkBuddy 专家团规范 v2.0。
> 版本 2.0.0 | 2026-09-01 | 作者 TZUVet
> 进化状态：evo-2 (1.000) → evo-3/4/5/6/7/8/9/10/11/12 共 11 轮进化，154 项 → 347 项基准全绿；安全评级 C→B+；主理人 22KB→6.8KB（-69%）；最近 tag `evo-12a`（P2 候补合并）

## 团队定位

**十三态流水线编排**的智能教材编写团队：教学设计 → 文献检索 → 章节撰写 → 四轮审查 → 统稿交付，引用核验零容忍防幻觉。Harness 编排架构（消息信封 / 状态黑板 / 熔断 / 预算 / trace）+ Harness v2.0 ACP 对齐。

## 质量门禁（v2.0 进化要点）

1. **核验三要素**：引用可用 = 标识符存在 **+ 主题匹配** + 数据点可定位。
   「PMID 真实但研究主题与本章无关」判 P1 FAIL（实证案例：PMID:16809421 是肝病研究，曾差点混入禽病章节；ch06 实战又拦下 scout 自行补全「山东分离」）
2. **WORK_ROOT 约定**：所有路径相对主理人给定的工作根目录；成员不得猜路径，未收到则回问
3. **工具降级链统一**：scout 检索 = 四层（Tier 1 英文学术库 → Tier 2 通用网页 → Tier 3 中文库 → Tier 4 权威机构 WOAH/Merck/兽药典）；examiner R3 引用核验 = 三级（PubMed MCP → `pubmed.ncbi.nlm.nih.gov/{PMID}/` → CrossRef）。每级给到工具路径/降级判据
4. **置信度可判定**：高 = Tier1 且 ≥2 源一致 / 中 = 单一可靠源 / 低 = 转载或 >10 年；判定不明就低不就高
5. **防过度补全自检**（evo-12 补丁）：scout 结构化提取后逐字核对限定词（地名/年份/宿主/数值）vs 原文，不可定位则删除/降 [估]/标 [待核实]
6. **R3 计时口径**（evo-12 补丁）：≤15 条按整批计，>15 条按节分批（≤10 条/批）恢复逐批计时
7. **引用统计口径**（evo-12 补丁）：按「处数」计 + 唯一标识符数并报，如「[实] 8 处（唯一 PMID 5 个）」

## 成员

| 成员 ID | 花名 | 职责 |
|---------|------|------|
| smart-textbook-team-team-lead | 糜编澜（教材总编辑） | 13 态编排、三级门禁、熔断恢复、统稿交付；Harness 入口 |
| didactic-architect | 陶靖衍（教学设计架构师） | Bloom 分层、块级 DAG、苏格拉底追问、章节大纲 |
| literature-scout | 粟海琼（文献检索专员） | **四层降级检索**（Tier 1-4）、Wiki 沉淀、限定词自检（evo-12）、[待核实] 标注 |
| subject-writer | 祝书白（学科内容撰写师） | R1→R2→R3 多轮撰写、数据来源标签、思政融入、引用统计口径（evo-12） |
| quality-examiner | 严正词（质量控制审查官） | R1-R4 四轮审查、引用逐条核验（按批计 vs 整批计）、结构化裁决 |
| visual-instructional-designer | 绘章图（可视化教学设计师） | 图表规格、Mermaid/SVG 产图、图文一致性 |

## Skills

- `textbook-pipeline-workflow` — **13 态状态机**（A-N + H LEARN）、门禁、E1-E5 错误协议、handoff 契约、介入协议（evo-11 迁入）、统稿 checklist（evo-11 迁入）
- `citation-verify` — PMID/DOI 零容忍核验；输入不可信原则（evo-11：指令注入防护/缓存不豁免三要素/来源分级）
- `agent-harness-protocol` — **Harness 执行层骨架**（evo-11 自 team-lead 迁入）：消息信封、状态黑板、重试/超时/预算/熔断/trace、降级链、**角色矩阵与接口契约、任务分配三模式、冲突仲裁五类**
- `multi-agent-patterns` — 多代理协作公共模式（串行/并行/条件触发；铁律）
- `learn-protocol` — **LEARN 阶段协议**（evo-11 新建）：三步曲（数据收集 → 规则草案 → 候补池）+ 合并门禁 + 反模式

## 预设 Workflow

- W1 全流程编写（默认）：设计→检索→撰写→审查→可视化→交付
- W2 只审查：四轮审查 + 引用核验
- W3 只检索：文献证据供应
- W4 补图：图表设计与生成

## 进化里程碑（v2.0 团队档）

| 轮 | 主题 | 关键动作 |
|----|------|---------|
| evo-2 | Harness 雏形 | 消息信封 + 13 态调度 |
| evo-3/4 | 介入协议 + R3 分批 | 打回/超时/续跑机制 |
| evo-5/6 | LEARN 雏形 + 性能优化 | 候补池 + 延迟预算 |
| evo-7 | R3 延迟优化 | P0 快扫 + 短路 + 缓存复用 |
| evo-8/9 | RedTeam 对抗审查 | 10 攻击向量闭合，安全评级 C→B+ |
| evo-10 | 热修 | examines 必炸矛盾统一 + 打回 3 轮对齐 + ch06 真实候补入池 |
| evo-11 | P0 主理人重构 | team-lead 22.1KB→6.8KB（-69%），按需 skill 分层 |
| evo-12a | P2 候补合并 | ch06 三条实战候补合并进 scout/examiner/writer |

## 使用

WorkBuddy 专家中心选择「智能教材编写天团」即可启动。主理人糜编澜会先澄清需求（教材名/读者/章节/字数/时数），再按 SOP 推进。Skills 由编排者按需加载（progressive disclosure），常驻核心 ≤6KB。

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
| （v5 缺失） | skills/agent-harness-protocol + multi-agent-patterns + learn-protocol（evo-11 新增） |