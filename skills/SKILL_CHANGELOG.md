# SKILL_CHANGELOG — smart-textbook-team skill 版本演进

> 跟踪每个 skill 的版本演进、变更条目、兼容性说明、触发词增删。
> 起始版本：evo-11（团队 v2.0.0）；维护人：team-lead（糜编澜）

---

## agent-harness-protocol（核心骨架，192 行起）

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
