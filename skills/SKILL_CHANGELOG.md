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
