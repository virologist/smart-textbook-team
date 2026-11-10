# SKILL_CHANGELOG — smart-textbook-team skill 版本演进

> 跟踪每个 skill 的版本演进、变更条目、兼容性说明、触发词增删。
> 起始版本：evo-11（团队 v2.0.0）；维护人：team-lead（糜编澜）---

## team-generation（动态专家团队生成，2026-10-30 新建）

### v1.0.0（批次 4，2026-10-30）

**背景**：诊断维度 D1 要求「按输入主题以逐章/逐节粒度动态坍缩生成资深专家团队，
且坍缩结果先与用户对齐确认后才生效」。此前团队构成完全静态（plugin.json 锁死 5 人），
换学科只能用 role-assembly profile 的映射表在 writer 内部换视角，无法真实生成新成员。

**确立**：
- 双层成员架构：静态层（常驻 5 人）+ 动态层（`运行态/dynamic-members.yaml`，WORK_ROOT 级）
- **「先对齐后生效」硬闸门**：`confirmed_by_user: true` 才可注册；装配器层面拒绝未确认成员
- 三维评估：知识覆盖深度 / 领域匹配度 / 输出准确性保障
- E3 替补：examines 覆盖不缩水；换人不重置打回计数（防换人洗计数）
- 动态成员禁止代行审查职责（生成者/审查者分离不可被动态层绕过）

**配套脚本**：`scripts/generate_team.py`（只出提案）
**装配器联动**：`--allow-dynamic-members` + `--work-root`（默认关闭）

**触发词新增**：`生成团队` / `动态成员` / `团队构成` / `专家坍缩` / `换成员` / `替补` / `team generation`


---

## manuscript-delivery（书稿交付规格，2026-10-30 新建）

### v1.3.0 → v1.4.0（R3 遗留 L1a · 习题位标记口径统一，2026-11-05）

**背景**：`agents/subject-writer.md` 规定 writer 在书稿里写
`[习题位 {节号}：{Bloom 层级}×{题数}]`，而本 skill §1.3 / `chapter-structure.md` /
`veterinary.md` / `check_manuscript.py` 的 `RE_EXERCISE` / `compute_metrics.py` C9
五处一律用 `[习题 {章}-{序}]` ⇒ writer 写的习题位**永远匹配不到** ⇒
判据 4.8 恒走「无标记」WARN ⇒ **习题位缺失/断号永不被拦**（实测证据见
`stt-diag-20261101/B/findings-B.md:202`）。

**变更**：
- §1.3 补「**习题位的两层语义**」表（设计层按节 / 书稿层按全章流水号），
  明确 legacy 是**设计层**写法、**不得落进书稿**。
- §1.3 习题位行补 **4.8b**；§4 判据表**新增 4.8b**（legacy 形式判 FAIL）。
- 配套：`count_net_words.py` 剔除口径扩到 canonical 形式；
  `compute_metrics.py` C9 让 canonical 与 legacy **都算「存在」**
  （结构只答「有没有」，格式由 4.8b 单独判，避免同一缺陷被重复计一次）。

**破坏性变更**：是 —— 书稿层习题位标记必须用 `[习题 {章}-{序}]`，
legacy 形式被 4.8b 判 FAIL；存量书稿需迁移（迁移规则 = 设计层节号顺序映射为全章流水号）。

### v1.2.0 → v1.3.0（批次 B4 · ADR-05 硬门槛落盘，2026-11-01）

**背景**：R5 五维评分此前是 LLM 自评散文（80 分红线不可审计、权重可伪造），
「可审性」在评审眼里 = 能不能拿出可核验的过程证据。ADR-05 把散文级硬数字
落到结构化文件 + 门禁读取。

**变更**：
- 判据表补 **4.14 R5 硬门槛**：`运行态/r5-score.json` 存在时——total≥80 ∧
  total==Σ(维度×权重)/100 ∧ 权重和==100 ∧ 每维 ≥1 证据位置；不存在 → N/A 不阻塞。
  脚本 `scripts/score_quality.py` 产出，check_manuscript 4.14 独立重算反伪造。
- 附带归位 frontmatter version 漂移（B5 加 v1.2.0 变更记录时漏同步版本号）。

**破坏性变更**：无（4.14 缺文件 N/A，不阻塞存量 WORK_ROOT）

### v1.1.0 → v1.2.0（批次 B5 · ADR-01 全书层，2026-11-01）

**背景**：单章交付链只管一章；多章成书时目录散、图号章内序、参考文献各编各号，
无人负责合成「一本书」。ADR-01 确立双层状态机 + 全书装配器（不新增成员）。

**变更**：
- 新增 §5.3 全书装配：`build_book.py` 合稿语义（图号全书序重排 / 参考文献去重合并
  + 全书重编号 / TOC 域 + 单节连续页码）
- 新增 skill `book-orchestration`（全书流程 SSOT：BOOK_* 5 相位 / book-spec /
  chapter-map / 门禁 5.1–5.5）
- 单章行为零改动；触发词增补：全书 / 整本 / 多章 / 合稿 / 成书 / book-spec

### v1.0.0（批次 2，2026-10-30）

**背景**：交付物形态此前无 SSOT。`team-lead.md` Phase ASSEMBLE 曾引用
`scripts/build_chapter.py` 作为 docx 模板，实测该文件从未存在、CHANGELOG 亦无此承诺
（属虚构引用）。本 skill 与其配套脚本兑现该承诺。

**确立**：
- **md 为源、docx 为交付**双格式铁律（docx 禁止手改，改则回 md 重建）
- md 结构契约：标题层级禁跳级 / frontmatter 七项 / 图位·题注·习题位·思政标记 /
  交叉引用可解析 / GB/T 7714 参考文献
- 内置教材版式默认 + 三级覆写（`--reference-doc` > 学科 profile > 内置）
- **双轨图表**：md 保留可渲染源码；docx 嵌栅格化 PNG（mmdc 三级降级，不静默丢图）
- 门禁 4 七项判据（标题/题注/交叉引用/参考文献/docx 层级/图数一致/净字数）

**配套脚本**：`scripts/build_manuscript.py`（构建）、`scripts/check_manuscript.py`（校验）

**实测修正**：
- 图位/题注/规格卡必须空行分隔（否则 pandoc 合并段落，题注居中失效）
- 图位占位标记 `[图 X-Y：…]` 在 docx 渲染态移除（避免与题注重复）
- 图表源码按**位置就近匹配**而非下标配对（防插错图）
- 陈旧资产过滤（assets/ 残留他章 PNG 不得计入图数）

**触发词新增**：`书稿` / `docx` / `交付格式` / `版式` / `题注` / `目录` / `参考文献格式` / `图表栅格化` / `manuscript`


---

## agent-harness-protocol（核心骨架，192 行起）

### v1.4.1 → v1.5.0（批次 B4 · ADR-05 硬门槛落盘，2026-11-01）

**背景**：预算可行化四缺陷（A-17/A-24/A-09/A-26）——80K 硬上限算术不可满足
（单 spawn 底噪 19–29K × 6 ≥114K）、tokens_per_phase 只覆盖 4 态、
`budget.cuts` 键规范要求了但模板不存在、信封只解析 5 字段。

**变更**：
- §2 黑板模板：`tokens_limit` 80K→**150K**；`tokens_per_phase` 4 态 → **全 13 态**；
  补 `cuts: []` 键（§3.1 削减落盘义务的承载位）
- §2 降级策略 / §3.1：补 **`--skip-skill-preload` 降级档**（预算 ≥80% 跳过非关键
  skill 预加载——原降级策略无可执行削减项，超限后无法回落到线内）
- §6.1 trace schema：补 `confidence` / `gate_verdict`（JSON 化 pass-fail 清单）/
  `issues` / `root_cause`（A/B/C/D）4 字段 + `--reject-key` 打回计数
  （`运行态/reject-counts.json` 机械累加，≥2 自动触发介入协议，`progress.py rejects` 读取）
- §1 落地说明：`--from-envelope` 5→**19 字段全解析**（`ENVELOPE_FIELDS_PARSED=n/19`）

**破坏性变更**：无（纯增量；80K→150K 是常量，一行可改回）

### v1.4.0 → v1.4.1（批次 B1 · ADR-04，2026-11-01）

**修正**：§6.3 尾部 schema 说明原写「PHASE_ORDER = 13 态 + VERIFY-R1~R4 子阶段」——
与实际 19 项不符，且把 R4 记在 VERIFY 前缀下（R4/R5 属 PROOFREAD 态）。
现改为「唯一权威 = `progress.py` 的 `PHASE_ORDER`，本节不复述枚举值」，一致性交
`scripts/check_phase_consistency.py` 机械校验（CI 第 8 道门禁）。

**兼容性**：仅删错述、加引用，无协议行为变化。

### v1.3.0 → v1.4.0（evo-13, 2026-09-01）

**新增**：
- §1.1 **跨 agent 消息 boundary filter**（对标 G6 缺陷）—— 跨 agent 文本一律视作「受审数据」；识别 10 类指令性短语 + self-assertion 防护；不可豁免
- §2 **Token 预算规则**（对标 G3 缺陷）—— 三重阈值（软上限/章节硬上限/累计上限）+ 降级策略（关闭并行 + R3 降深度）+ LEARN 回流
- §2 黑板 yaml 增字段：`tokens_used` / `tokens_limit` / `tokens_per_phase`

**引用文献**：12-Factor AgentOps V「外部验证」 + Hermes Authority scoping + Beam.ai `budgetCapTokens` + AutoGen `TokenUsageTermination`

**触发词新增**：`boundary filter` / `token 预算` / `tokens 耗尽` / `降级而非熔断`

**测试覆盖**：13 项 V 类（V1a/b/c 边界过滤 + V2a/b/c token 字段 + V3a 降级 + V4a handoff + V5×5 模式映射），集成进 tests/test_orchestration_v2.py

**破坏性变更**：无（纯增量）

---

### v1.2.0 → v1.3.0（evo-11, 2026-09-01）

**新增**：§0 角色矩阵 + 接口契约 + 任务分配三模式 + 冲突仲裁五类（自 team-lead 迁入）

### v1.1.0 → v1.2.0（evo-9）

**新增**：副作用越界校验 + 打回计数防逃逸 + 死锁解锁 + 降级疲劳监测

### v1.0.0 → v1.1.0（红队实证补丁）

**新增**：防投毒校验（写权限声明 ≠ 强制，靠对账机制）

---

## textbook-pipeline-workflow（13 态 SSOT）

### v1.2.0 → v1.2.1（批次 B1 · ADR-04 状态机归一，2026-11-01）

**修正**：§13 态表新增权威源指针——相位枚举唯一权威 = `scripts/progress.py` 的 `PHASE_ORDER`
（19 相位），本节降为**业务视图**，只引用不复述；R5 落盘相位名由 VERIFY 前缀改为 `PROOFREAD-R5`
（R4/R5 属 PROOFREAD 态）；§门禁 3 的别名落盘说明同步（旧别名把 VERIFY 指向 R5 的语义错位已修，
`VERIFY` 现指 `VERIFY-R3`）。

**判据联动**：`scripts/check_phase_consistency.py` 机械校验「文档相位字面量 ⊆ PHASE_ORDER」，
不一致即 CI 红。

**兼容性**：文案改动，13 态业务语义与门禁触发条件零变化。

### v1.1.0 → v1.2.0（evo-11, 2026-09-01）

**新增**：介入协议（Phase E 打回数 = 2）+ 统稿 checklist

### v1.0.0（起点）

**定义**：13 态状态机 + 检索门禁 + 错误升级 E1-E5 + Handoff 契约 + 防幻觉闭环

---

## citation-verify（PMID/DOI 零容忍核验）

### v1.1.0 → v1.2.0（evo-11）

**新增**：输入不可信原则（指令注入防护 + 缓存不豁免三要素 + 来源分级）

### v1.0.0（起点）

**定义**：核验三要素（标识符存在 + 主题匹配 + 数据点可定位）

---

## learn-protocol（LEARN 阶段协议）

### v1.0.0（evo-11, 2026-09-01 创建）

**定义**：LEARN 三步曲（数据收集 → 规则草案 → 候补池）+ 合并门禁（≥3 OPEN 或用户 ack）+ 反模式

---

## multi-agent-patterns（5 大协作模式）

### v1.0.0 → v1.1.0（evo-11）

**新增**：中文触发词（并行串行判据 / 协作模式怎么选）

### v1.0.0（起点）

**定义**：Generator-Critic / Plan-Execute-Reflect / Evidence Spiral / Retry-with-Strategy-Switch / Fan-out Fan-in + 反模式

---

## 后续演进路线（参考评测 v2 报告）

| 优先级 | 改进点 | 来源 |
|--------|--------|------|
| P0（已完成） | G1 reducer 规则（实际由 evo-7 落地，patch 语义表）/ G3 token budget / G6 boundary filter | evo-13 |
| P1 | G2 L2 Supervisor 自动触发 / G5 Termination keyword 兜底 / G7 OpenTelemetry 标准化 / 新增 error-recovery skill | evo-13 报告第七节 |
| P2 | 新增 human-approval skill / state-patch-protocol skill / init_skill.py + validate_skill.py 模板工具 / 跨章节并发架构 | 远期 |

---

## task-router（任务路由，v2.10.1 批次漏登记 · 本次回填）

### v1.2.0 → v1.3.0（★G3 v2.10.1，2026-11-06）

**变更**：task_type 枚举 16→17 类（新增 `review-section` 节级审查——波次收口检查，
不新增相位）；影子实现（test_router_eval.py）同步分支 + 2 正样例 + 2 不截胡反例。
**纪律⑥（v2.10.4 J3 补）**：review-section 验收须 `contract_check --task-type review-section
--section {节号}` 激活条件产物必查。

---

## v2.10.x 系列（第六、七轮升维批次 · 各 skill 版本位已升但本登记漏 → 回填）

### agent-harness-protocol v1.7.0 → v1.8.0（★G4 v2.10.1）
信封 19→21 字段：`reasoning_chain`（decision/criteria_refs/evidence_refs/computation/
alternatives_considered）+ `divergence`（parties/issue/resolution/rule_ref）；
record_trace 增同名参数（非法 JSON exit 2，缺失 WARN 渐进）。

### citation-verify v1.6.0 → v1.7.0 → v1.8.0
- v1.7.0（★G6）：方法 4d 第④锚形态 `[实]（std-skill:{skill名}:{条目}）`；
- v1.8.0（★J2 v2.10.4）：方法 4 增「疫情/流行病学统计源」行（主题对数据源错=数值无源；
  R7 ch_02 32135031 实证病灶进判据表；标签 `[实·疫情统计]`）。

### textbook-pipeline-workflow v1.5.0 → v1.6.0（★G3 v2.10.1）
§3.7 节级审查回路（review-section <800 字跳过 / 判据不新增 / ≤2 轮 / 段级抽查
100% 数值段 + 30% 定性段）。

### team-generation v1.0.0 → v2.0.0（★G1 v2.10.1）
三级坍缩（chapter/section/block）；--scope/--section/--blocks 互检 fail-fast；
per-scope 闸门；节级坍缩提示义务；v2.10.3 补 `--declined-trace` 机械锚。

### learn-protocol（signal_type 枚举 7→8，★J7 v2.10.4）
+`citation_r7_flagged`：R7「部分支持」锚点 → 候补池通路。

### 新增 skill：book-orchestration（全书编排，B5 批次，此前漏登记）
BOOK_* 5 相位消费协议；§6.1 章内节级调度。

### 新增参考规范（references/，v2.11.0 ★E1/C 本批）
- `skill-mounting.md`：自定义/标准类判据 skill 挂载规范（目录/frontmatter/命名隔离/
  卸载无残留/B7 铁律继承/隐性依赖附表）；
- `decision-lanes.md`：裁决车道分级（绿/黄/红）+ 进化安全规范（红道全链/黄道/禁改项）。

---

## v2.11.2 系列（★L 批次，2026-11-08 · audit 后补登记修正）

### verify_citations_r7 v1.0.0 → v1.1.0（★L1）
判据数据外置：三词典（120/32/73）+ 数值单位表 → references/profiles/
r7-entities-veterinary.json（schema r7-entities/v1）；脚本只留加载/判定逻辑，
坏文件显式 raise。判定行为零漂移（16 检查项回归锁定）。修复 CI 学科中立门禁
自 2026-11-04 的 22 处 HARD 回潮红灯。判据载体的版本从此随 profile 数据文件走。

### citation-verify v1.8.0（判据载体变更说明）
其 R7 执行体（scripts/verify_citations_r7.py）的实体/主题/单位判据改由
profile 数据文件承载；§7b 覆盖链（★K v2.10.5）语义不变：profile 有配置则覆盖
默认数据，无则回落 + WARN。


---

## v2.11.3 系列（★M 批次，2026-11-08）

### manuscript-delivery v1.4.0（门禁 4.12d 执行体变更说明 · 判据载体 citation-verify §4d）
第④锚 `std-skill:{skill名}:{条目}` 在 check_manuscript.py `_has_retrievable_anchor`
机械落地（RE_STD_SKILL 三段齐全即认锚）——补齐 G6（v2.10）文档声称与机械实现的
缺口；①②③ 形态判定不变（10 例正负双向回归锁定）。

---

## v2.11.1 补登记（★M6 追认，2026-11-08 · 此前批次漏登记）

> 本节为八轮审计 D 项「登记漂移复发」的补丁：2.11.1 七项核销中改动了 SKILL.md
> 正文的项，按 decision-lanes §3.1 红道纪律在此追认登记。

### textbook-pipeline-workflow v1.6.0（★B v2.11.1）
§介入协议末尾新增「打回包五要素模板」（【单元|判定|原因|证据|SCOPE】）——
SCOPE 的三条散落等价约束字段化，不新增语义；覆盖全部 5 条退回路径。

### book-orchestration（★F2 v2.11.1）
§2 步骤③b：样章验证→批量放大协议（CHAPTER_SCHEDULE 首批只跑样章；合格三判据；
`notes=sample-chapter-approved` 后放大；不合格禁放大——notes CLI 落点 v2.11.4 ★M4 补齐）。

### scientific-figure（★J5 v2.11.1）
cell1 图说明行补 `[实]（std-skill:{skill名}:{条目}）` 锚形态引用（判据不作内容源）；
该锚的机械认锚于 v2.11.3 ★M2 在 check_manuscript.py 落地。

---

## v2.14.0 系列（★改造批次，2026-11-10 · 统一 CLI + 确定性门禁 + 红道登记）

> 本批**未改动任何 `SKILL.md` 的 frontmatter version**，故无 skill 版本位变更，
> 各 skill 的 F3「变更记录节 v{version} 对齐」不受影响。此处登记的是
> **脚本层 / 编排层**的新增能力，供红道追溯。

### 新增统一 CLI（`scripts/stt.py`）

- 包根解析由「`for r in .workbuddy .codebuddy` 兜底循环 ×5 处」收敛为脚本自身
  `__file__` 派生（换机首 spawn 死锁零线索的病灶）。
- 子命令：`env` / `gate --phase` / `spawn` / `net-words` / `verify`。
- `team-lead.md`「强制三步」step-1 改为 `stt.py spawn` 一行，其余协议文字原样保留。
- 门禁相位映射：`design` / `retrieve` / `produce` / `proofread` / `cross` / `consistency`。

### 新增确定性判据（三处「文字无检查」缺口）

- `check_gate_design.py`（门禁 1）：知识域非空 / 时数 ≥ 1 / 含知识块锚区块；
  退出码 0 通过 / 1 判据 FAIL / 2 输入缺失（显式报错，禁止静默吞错）。
- `check_gate_retrieval.py`（门禁 2）：覆盖率 ≥ 80% / 时效性近 10 年 ≥ 80% /
  冲突项 WARN 交人工。数据型行以「含数值」识别，**通用层零学科常量**——
  学科词下沉 `references/profiles/`，不在通用门禁里写死。
- `check_redlane_registry.py`（红道登记）：R1–R5 版本各处声明自洽 + R6 CHANGELOG
  顶部须等于当前发布版本。补上 `IMMUNE_FILES` 免检 + 「登记无执行体」的缺口。
  权威源与 `package_release.sh` 一致（两份 plugin.json / marketplace.json×2 /
  install.sh / README.md）。

### 通用工程纪律（本批实测固化，供后续复用）

- 测试临时产物**禁止写进仓库内**：repo 扫描类门禁（学科中立 / 静态契约）会扫到
  产物里的绝对路径而误报；一律放 `/tmp`。
- 反向例须断言「输出不伪装成通过」：输入缺失判 `exit 2` 还不够，
  还须断言显式报错文字、且不含「0 项未通过 / 全部通过」。
- 任何「版本已登记」类判据，权威路径须与打包脚本同源，不得读包内不存在的路径。

### 测试

新增 5 个测试文件 / 18 用例（含 spawn 真实任务包端到端）；全量回归全绿。

---

## v2.13.1 系列（★挂起项收口批次，2026-11-10 · 架构师审计 D-2/D-3/U-6 + K-1..K-6 入库）

### check_test_prompts.py（★D-2 豁免机制 + ★D-3 确定性）
- **D-2 豁免机制**（架构师 §9.3 方案 2）：新增模块常量 `EXEMPT_SKILLS: dict[str, str]`
  （skill 名 → 必填理由），三护栏：①豁免键须在包内真实存在（禁预留占位）；
  ②理由非空（豁免可审计）；③豁免数 > 0 时输出提醒（防长期遗忘成永久免检后门）。
  **当前表为空 = 机制就位、不放水**。新增豁免属判据改动，须经管家节点确认。
- **D-3 确定性遍历**：`build_pool` 的 `rglob` 改 `sorted()`，对齐包内同构门禁
  （check_doc_consistency / check_cross_refs）惯例；行为零变化（集合判定不受序影响），
  可复现性加固。
- 测试 19 → 22 用例（+3：合法豁免生效 / 幽灵豁免键被拦 / 空理由豁免被拦）。

### harness-gate.yml（★U-6 吞错修复）
学科中立 step 的 audience-profiles 探针还原：`git checkout/restore ... || true`
（对未跟踪文件报 pathspec 错但 exit 0，三重吞信号，探针残留静默污染工作区——
架构师 /tmp/gitprobe 实测）→ 改为 `cp` 文件备份还原 + `grep` 校验探针行已消失，
失败即 `exit 1`。同文件其他 `|| true`（:395/:555/:1019）有下游断言兜底，非还原动作，
保留。整段 run 块本地实测 rc=0，探针零残留。

### 配套（wiki 底座，tb-writer 项目侧）
架构师 §18 拟入库条目 K-1..K-6 经 wiki-creator 编译进 `<项目>/.wiki-creator/`：
主题 `gate-criteria-design`（门禁判据设计）6 页，backlinks 21，lint 全清
（0 未互链 / 0 无来源 / 0 重复 slug / 0 主题孤儿）。

---


## v2.13.0 系列（★S3-S7 批次，2026-11-10 · darwin 审计第二批落地）

### multi-agent-patterns v1.1.0 → v1.2.0（★S3）
新增「人在回路（到上限/触限时的停机契约）」小节：5 个模式各自的**既有上限值**
（3 轮 / 2 轮 / 2 轮 / 同方式 2 次+换策略 1 次 / 分支 ≤5）统一绑定到四要素
「停机动作 / 交付物 / 交回谁 / 用户可做的决定」；「通用反模式清单」补 2 条
（触限后只停机不交代 / 把「用户没回话」当同意继续）。上限值零杜撰（机械校验）。

### scientific-figure v1.0.0 → v1.1.0（★S3）
新增「§5 人在回路（撞上限/撞严禁时的停机契约）」：§3 严禁 6 条逐条绑定停机动作与
降级形式（含无实测数据 → 示意数据降级契约）；§4 复核清单 7 项逐条绑定判定与失败处置；
停机包 4 类附件；交回谁用包内真实 agent name（visual-instructional-designer /
quality-examiner / smart-textbook-team-team-lead）。

### task-router v1.3.0 → v1.4.0（★S3）
新增「§8 人在回路（派活前后与 ESC 升级的停机契约）」：§2 Step 4 dispatch checklist
全部 7 项 + §3 ESC1–ESC4 逐条绑定四要素；阈值唯一来源 §2 Step 2 的 70 分线，
未新造阈值；ESC3 换人仍过用户闸门；§8 末尾声明「只补停机契约、不改路由语义」，
tests/test_router_eval.py 影子实现无需同步（路由枚举/关键词/优先级零改动）。

### citation-verify v1.8.0 → v1.9.0（★S3+S4）
§方法5「全部失败」由 2 行扩写为 5 段（触发条件/判否动作/是否阻断交付/交付物要求/
交回谁+用户可决定三条路）。口径：逐条独立不互相阻断，但「全部核验项失败」的章
**不得进入交付门禁**——显式标注为**人工裁决口径**（check_manuscript.py 实测无
「全章零通过即 FAIL」判项，不虚构机械门禁）；补「变更记录」小节。

### agent-harness-protocol v1.8.0 → v1.9.0（★S5+S6+S7 存量）
渐进式披露：顶部新增「路由表（做 X 读 §N）」18 行查找表；§6.2 + §6.5（223 行）
完整执行体下沉 → `references/harness-protocol-details.md`（新建 265 行，逐字保留，
机械核验双 True），主文件留指针 + 退出码摘要；主文件 864 → 648 行。
补「## 变更记录」节（v1.8.0 存量条目，S7 批次）。

### learn-protocol / textbook-pipeline-workflow（★S7 存量，正文零改动）
各补「## 变更记录」节（v2.1.0 / v1.6.0 条目），frontmatter version 不动（语义未变）。

### manuscript-delivery（★S7 F3 首战命中）
补 v1.4.0 变更记录条目——frontmatter v1.4.0 与记录最新 v1.3.0 错位的**存量真实病灶**，
被新门禁 F3 首次运行即拦下（该判据价值的直接实证）。

### 配套执行体（★S7 + ★T5 修复）
- `scripts/check_skill_frontmatter.py` 新建（F1–F5 五判据，零依赖）+
  `tests/test_check_skill_frontmatter.py` 19 用例（5 正向 + 14 反向）。
- `scripts/check_test_prompts.py` T5 判据修复两条**假阴性逃逸**：
  ① 子串逃逸（`check_foo.py` ⊂ `check_doc_consistency.py` 被判存在）→
  改为「文件名查真实文件系统 + 其余标识符查 token 精确集合」；
  ② 门禁自证（自身 docstring 反例名进池）→ 门禁自身与被检文件均不入 token 池。
  `tests/test_check_test_prompts.py` 16 → 19 用例（新增子串假名 / docstring 反例名 /
  真实命令不误杀三条反向例）。
- **通则升级**：内容真实性判据 = 排除被检文件 + 排除判据自身文本 + 精确匹配非子串。

---


## v2.12.0 系列（★S 批次，2026-11-10 · darwin 8 维审计落地 S1+S2）

> 本批按 `references/decision-lanes.md` §3.1 红道全链执行：diff 预览 → 实现 →
> 反向例测试 → 全量 pytest + CI 全绿 → SKILL_CHANGELOG 登记 → 版本四处自洽 → 推送。

### book-orchestration → v1.0.0（★S2 · 三项缺陷修复）

**背景**：2026-11-10 darwin 8 维审计实测——`book-orchestration` 是 10 个 Skill 中
**唯一 frontmatter 缺 `version`**、**唯一无「变更记录」小节**、且 **D3 边界覆盖最薄**
（关键词密度 0.57%、`fallback/兜底/降级/回退` 0 次命中、有序步计数 0）的一个。

**变更**：
- `frontmatter` 补 `version: 1.0.0`（此前 10 个 Skill 中唯一缺失项）。
- 新增 `## 变更记录` 小节（格式对齐 team-generation：`- v{版本} [{YYYY-MM-DD}] {摘要}`）。
- 新增 `### 2.1 命令失败处置` 表：五条命令（`progress.py book init` / `book-status` /
  `update --phase` / `check_book.py --strict` / `build_book.py`）的**退出码 → 全书层动作**映射；
  含「同一命令连续失败 2 次即停并附完整错误输出上报管家节点裁决」
  （对齐 multi-agent-patterns「换策略而非重复」纪律）与**红道停机口径**
  （BOOK_DELIVER 放行 / 样章批准 / 合稿覆盖 三类失败一律停下上报，
  不得以「先交付后补」推进）。
- 车道口径 SSOT 仍为 `references/decision-lanes.md`；本节只列**命令级**退出码，
  不复述车道定义，避免出现第二权威源。

### 其余 9 个 Skill（★S1 · 契约评测用例补齐，SKILL.md 正文零改动）

新增 `skills/{book-orchestration|learn-protocol|manuscript-delivery|scientific-figure|
task-router|team-generation}/test-prompts.json`（每份 3 条，覆盖正常/异常/边界三型），
使 10 个 Skill **全部**具备契约评测用例。此前仅 4 个有
（agent-harness-protocol / citation-verify / multi-agent-patterns / textbook-pipeline-workflow）。
用例集是**评测资产**，不改变 SKILL.md 正文语义，故各 Skill 版本位不动。

配套新增门禁 `scripts/check_test_prompts.py`（T1 存在性 / T2 结构 / T3 条数 /
T4 字段 / T5 引用真实性）+ 反向例测试 `tests/test_check_test_prompts.py`（16 用例）。

### ★门禁设计教训（自证循环）

T5 首版把 `test-prompts.json` 自身读进证据池 ⇒ 被检文件自证（用例里写什么池里就有什么）
⇒ 判据恒绿。由反向例测试当场暴露，修复：`POOL_EXCLUDE_NAMES` 排除被检对象。
**通则**：任何「内容真实性」判据必须显式排除被检文件，否则必成自证循环。
