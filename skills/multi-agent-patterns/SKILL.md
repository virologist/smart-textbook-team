---
name: multi-agent-patterns
description: "Loop and collaboration patterns for multi-agent orchestration: generator-critic, plan-execute-reflect, evidence spiral, retry-strategy-switch, fan-out/fan-in. Each pattern includes applicability, convergence criteria, hard iteration limits, and anti-patterns. Load when designing or debugging any multi-agent collaboration flow. Trigger words: 串行还是并行 / 循环不收敛 / 扇出聚合 / fan-out / generator-critic / 重试换策略 / 协作模式怎么选."
version: 1.1.0
---

# multi-agent-patterns — 多代理协作与循环模式库

> 第一原则：**任何循环都必须有显式收敛判据与迭代上限**。无上限的循环等于停摆风险——这不是保守，是 3 轮不收敛就烧掉整个预算的现实。

## 何时使用

- 设计任何涉及 ≥2 个代理的协作流程
- 某个流程反复不收敛、或不知道该不该继续循环
- 需要判断「这个任务该并行还是串行」

---

## 模式一：Generator-Critic（生成—批评）

**结构**：Generator 产出 → Critic 独立评判 → 不合格则带证据返修 → 循环

**适用**：内容生产 + 质量控制（本团队：writer ↔ examiner）

**收敛判据**：`verdict = pass`，即无 P0/P1 blocking 项

**上限**：3 轮。第 3 轮仍失败 → 停止，通知用户并附完整 3 轮证据链

**关键约束**
- Generator 与 Critic **必须是不同代理**——自判等于没判
- Critic 输出必须是**结构化裁决**（verdict/blocking/advisory/evidence），不是「感觉还行」
- 返修指令必须**具体到行号与期望**，不是复述 Critic 原话
- Critic 只标三类阻断（正确性缺陷 / 需求未满足 / 数据完整性破坏）；风格偏好一律 advisory

**反模式**：Critic 顺手把内容改了（越界）；返修指令模糊导致同一问题反复出现（应在第 2 次即切换策略）

---

## 模式二：Plan-Execute-Reflect（计划—执行—回看）

**结构**：Planner 出规格 → Executor 按规格实现 → 回看覆盖度

**适用**：需求模糊、需要结构化拆解的场景（本团队：architect → writer → examiner 覆盖度回看）

**收敛判据**：设计规格中全部要素被覆盖且达标（本团队：design §B 知识块全覆盖 + Bloom 层级达成）

**上限**：2 轮

**关键约束**：Planner 不产出执行细节数据，只产出规格与验收标准；回看只看「契约内是否达成」，不追加契约外要求

---

## 模式三：Evidence Spiral（证据螺旋，H15）

**结构**：执行中发现证据缺口 → 标 `[待核实]` → 专职 Retriever 补检索 → 回填复核

**适用**：任何需要外部事实支撑的生产（本团队：教材数据与引用）

**收敛判据**：`[待核实]` 清零，或用户明确接受遗留清单

**上限**：2 轮

**关键约束**：**缺口必须标注而非编造**——这是防幻觉的最后防线。回填后必须复核（不是填完就算过）

---

## 模式四：Retry-with-Strategy-Switch（重试—换策略）

**结构**：失败 → 同方式重试 → 仍失败 → **换策略** → 再失败 → 升级用户

**适用**：任务级失败处理

**收敛判据**：任务闭合（成功或明确放弃）

**上限**：同方式 2 次 + 换策略 1 次 = 3 次

**策略切换映射（根因 → 动作）**

| 根因 | 判据 | 换什么策略 |
|------|------|-----------|
| A 证据缺失 | 需要的数据检索库里没有 | 转 Retriever 补检索，不逼 Generator 硬编 |
| B 理解偏差 | 指令歧义导致跑偏 | 编排者重写指令 + 给具体改法示例 |
| C 能力边界 | 任务超出角色定义 | 拆解为更小子步骤，或给参考片段（仍由该成员整合） |
| D 不可抗力 | 工具全挂 / 红线内容 | 直接停止，通知用户 |

**反模式**：同一句话重复发 3 次期待不同结果（这不是重试，是噪音）

---

## 模式五：Fan-out / Fan-in（扇出—聚合）

**结构**：一个任务拆成 N 个无依赖子任务并行 → 各自产出到不同路径 → 编排者聚合

**适用**：多知识点检索、多图并行设计、R3 分批核验

**收敛判据**：全部分支返回，或有分支明确失败

**上限**：分支数 ≤ 5（超出后聚合成本高于并行收益）

**关键约束**
1. 分支间**无数据依赖**方可扇出
2. 每个分支写**独立路径**，禁止同文件并发写
3. 用 `correlation_id` 聚合，**不做交叉合并**（分支产出保持原样，合并决策权在编排者）
4. 部分分支失败时：其余分支结果保留，只重跑失败分支

---

## 模式选型速查

| 场景 | 用哪个 |
|------|--------|
| 内容需要质量把关 | Generator-Critic |
| 需求模糊需拆解 | Plan-Execute-Reflect |
| 需要外部事实支撑 | Evidence Spiral |
| 任务失败要重试 | Retry-with-Strategy-Switch |
| 多个独立子任务 | Fan-out / Fan-in |

---

## 并行 vs 串行判据（决策树）

```
下游是否需要上游的输出？
├─ 是 → 串行
└─ 否 → 是否写同一文件？
         ├─ 是 → 串行（或重定向路径后并行）
         └─ 否 → 并行（分支数 ≤5，用 correlation_id 聚合）
```

## 通用反模式清单

- 循环无上限或无收敛判据
- Critic 与 Generator 同一代理
- 上下文整段复制传递（应给路径）
- 并行分支写同一文件
- 失败后原样重发（不换策略、不给新证据）
- 部分分支失败就丢弃全部结果
