# smart-textbook-team — 智能教材编写天团

> 转换自 content-forge v5 多 Agent 框架（tb-writer 项目），适配 WorkBuddy 专家团规范 v2.0。
> 版本 2.5.0 | 2026-11-01 | 作者 TZUVet ｜ 跨平台安装：`bash install.sh`（WorkBuddy / Claude Code / Claude Desktop / Cursor）
> 进化状态：evo-2 → evo-16 共 15 轮进化，静态契约基准 269 计分项全绿（1.000）+ 路由评测 40/40（1.000）+ CI 门禁 8 道全绿；**10 个 skill**（agent-harness-protocol / book-orchestration / citation-verify / learn-protocol / manuscript-delivery / multi-agent-patterns / scientific-figure / task-router / team-generation / textbook-pipeline-workflow）；主理人常驻核心 19.4KB
> **交付形态（v2.3.0）**：大学教材**书稿** —— `.md`（源，唯一编辑入口，**承载审稿修订语义**）+ `.docx`（交付格式 + Word 追踪修订审改载体，改后须回流 md）+ `_审阅.docx`（修订标记→Word 真修订）+ `.溯源.md`（自动生成），规格见 `skills/manuscript-delivery/SKILL.md`
> **跨专业（v2.2.2）**：学科知识已外置为 profile —— `references/profiles/{veterinary|computer-science|law}.md`，新增学科只需复制改写该文件，**规范本体零学科常量**（默认 veterinary）
> 真实运行基线（2026-10-15 e2e-p1）：ch08 PRODUCE-R2 + VERIFY-R2 端到端，7/7 引用 PubMed 实检 PASS，dispatch 1.000 / retry 0.50 / rework 0.000

## 团队定位

**十三态流水线编排**的智能教材编写团队：教学设计 → 文献检索 → 章节撰写 → 四轮审查 → 统稿交付，引用核验零容忍防幻觉。Harness 编排架构（消息信封 / 状态黑板 / 熔断 / 预算 / trace）+ Harness v2.0 ACP 对齐。

## 质量门禁（v2.0 进化要点）

1. **核验三要素**：引用可用 = 标识符存在 **+ 主题匹配** + 数据点可定位。
   「PMID 真实但研究主题与本章无关」判 P1 FAIL（实证案例：PMID:16809421 是肝病研究，曾差点混入禽病章节；ch06 实战又拦下 scout 自行补全「山东分离」）
2. **WORK_ROOT 约定**：所有路径相对主理人给定的工作根目录；成员不得猜路径，未收到则回问
3. **工具降级链统一**：scout 检索 = 五层（**Tier 0 本地知识源** ima/Obsidian/书籍md → Tier 1 英文学术库 → Tier 2 通用网页 → Tier 3 中文库 → Tier 4 权威机构 WOAH/Merck/兽药典）；examiner R3 引用核验 = 三级（PubMed MCP → `pubmed.ncbi.nlm.nih.gov/{PMID}/` → CrossRef）。每级给到工具路径/降级判据
4. **置信度可判定**：高 = Tier1 且 ≥2 源一致 / 中 = 单一可靠源 / 低 = 转载或 >10 年；判定不明就低不就高
5. **防过度补全自检**（evo-12 补丁）：scout 结构化提取后逐字核对限定词（地名/年份/宿主/数值）vs 原文，不可定位则删除/降 [估]/标 [待核实]
6. **R3 计时口径**（evo-12 补丁）：≤15 条按整批计，>15 条按节分批（≤10 条/批）恢复逐批计时
7. **引用统计口径**（evo-12 补丁）：按「处数」计 + 唯一标识符数并报，如「[实] 8 处（唯一 PMID 5 个）」

## 成员

| 成员 ID | 花名 | 职责 |
|---------|------|------|
| smart-textbook-team-team-lead | 糜编澜（教材总编辑） | 13 态编排、三级门禁、熔断恢复、统稿交付；Harness 入口 |
| didactic-architect | 陶靖衍（教学设计架构师） | Bloom 分层、块级 DAG、苏格拉底追问、章节大纲 |
| literature-scout | 粟海琼（文献检索专员） | **五层降级检索**（Tier 0-4，Tier 0=本地知识源 ima/Obsidian/书籍md）、Wiki 沉淀、限定词自检（evo-12）、[待核实] 标注 |
| subject-writer | 祝书白（学科内容撰写师） | R1→R2→R3 多轮撰写、数据来源标签、思政融入、引用统计口径（evo-12） |
| quality-examiner | 严正词（质量控制审查官） | R1-R4 四轮审查、引用逐条核验（按批计 vs 整批计）、结构化裁决 |
| visual-instructional-designer | 绘章图（可视化教学设计师） | 图表规格、Mermaid/SVG 产图、图文一致性 |

## Skills

- `textbook-pipeline-workflow` — **13 态状态机**（A-N + H LEARN）、门禁、E1-E5 错误协议、handoff 契约、介入协议（evo-11 迁入）、统稿 checklist（evo-11 迁入）
- `citation-verify` — PMID/DOI 零容忍核验 + 中文法规/标准/公告源核验链（v1.3）；输入不可信原则（evo-11：指令注入防护/缓存不豁免三要素/来源分级）
- `agent-harness-protocol` — **Harness 执行层骨架**（evo-11 自 team-lead 迁入）：消息信封、状态黑板、重试/超时/预算/熔断/trace、降级链、开工/收尾三件套（P2-7）、**角色矩阵与接口契约、任务分配三模式、冲突仲裁五类**
- `task-router` — **13 类 task_type 路由**（v2.1 新增）：4 步路由算法、置信度合成、R1-R4 升级规则（与 pipeline E1-E5 错误分级分离）、40 用例离线评测（1.000）
- `multi-agent-patterns` — 多代理协作公共模式（串行/并行/条件触发；铁律）
- `learn-protocol` — **LEARN 阶段协议**（evo-11 新建）：三步曲（数据收集 → 规则草案 → 候补池）+ 合并门禁 + 反模式
- `manuscript-delivery` — **书稿交付规格**（v2.2.2 新增）：**md 为源、docx 为交付**的双格式铁律、md 结构契约、内置教材版式 + 三级覆写、**双轨图表**（md 保留可渲染源码 / docx 嵌栅格化 PNG，栅格化三级降级不静默丢图）、门禁 4 七项判据

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

- **WorkBuddy**：专家中心选择「智能教材编写天团」即可启动。主理人糜编澜会先澄清需求（教材名/读者/章节/字数/时数），再按 SOP 推进。Skills 由编排者按需加载（progressive disclosure），常驻核心 18.4KB。
- **导出发布包**：`bash scripts/package_release.sh`（自动校验四处版本声明自洽 → 打包 → 回读自检）；`--check` 只校验既有包是否落后于源仓。导出物默认落在 `tb-writer/smart-textbook-team.zip`（不入 git，二进制 3.4MB）。
- **跨平台**（Claude Code / Claude Desktop / Cursor）：`bash install.sh --dry-run` 预览 → `bash install.sh --target <平台>` 安装；git clone 后 `python3 scripts/assemble_spawn_prompt.py --list-members` 应列出 5 名成员（vendor 兜底开箱可用）。
- **包根定位与环境变量 `EXPERT_DIR`**（多机 / 非默认安装位必读）：脚本与装配器调用都靠 `EXPERT_DIR` 指到本包根目录。**优先级：显式 `export EXPERT_DIR=<包根>` > 按宿主安装根兜底**——WorkBuddy 装在 `$HOME/.workbuddy/plugins/marketplaces/my-experts/plugins/smart-textbook-team`，CodeBuddy 装在 `$HOME/.codebuddy/...`（同层级）。两套宿主部署位置不同，写死其一会让新机上首次 spawn 直接死锁且**零线索**，故一律先设环境变量。测试夹具的包根解析同此顺序，末位再回落到仓库自身（CI / 纯 clone 态）。

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