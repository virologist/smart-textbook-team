---
name: agent-harness-protocol
description: "Execution-layer harness for multi-agent orchestration: message envelope schema, state blackboard spec, retry/timeout/budget/circuit-breaker rules, trace logging format, and degradation chains. Load when dispatching agents, handling cross-agent state, or when a task stalls, retries, or times out."
version: 1.0.0
---

# agent-harness-protocol — 多代理编排执行层

> Harness 的核心命题：**同模型 + 同需求，没有 Harness 完成率约 60%，有 Harness 约 98%**。
> 差距不在模型能力，而在执行层是否把「上下文、状态、重试、预算、可观测」管起来。

## 何时使用

- 需要调度任何成员（spawn 前必读）
- 任务卡住/重试/超时/需换策略
- 跨阶段交接、状态同步
- 排查「为什么这个任务没跑完」

---

## 1. 消息信封（强制）

**ACP 兼容**：若平台注入 ACP 统一信封（v/to/type/trace_id/status/confidence），以 ACP 为外层，本协议字段（msg_id/task_id/correlation_id/context_refs/state_patch/ts）并入 payload；`trace_id` 与 `msg_id` 同值，ACP `status` 映射本协议 `type`。两套字段不得互相丢弃。

```yaml
envelope:
  msg_id: "{task_id}-{from}-{seq}"
  task_id: "{ch##}-{阶段}-{轮次}"
  correlation_id: "{ch##}"
  from: "{member_id}"
  to: "smart-textbook-team-team-lead"    # 一律回编排者
  type: RESULT | BLOCK | ERROR | STATUS | NEED_INPUT
  payload: {...}
  context_refs: ["相对 WORK_ROOT 的路径"]
  state_patch: {phase:..., artifacts:{...}, blocking_open:[...]}
  ts: "ISO8601"
```

| 字段 | 用途 | 违规后果 |
|------|------|---------|
| `msg_id` | 去重与 trace 串联 | 缺失 → 无法断点续跑 |
| `correlation_id` | 跨阶段聚合同一章节 | 缺失 → 并行分支无法归并 |
| `context_refs` | **上下文按引用** | 内联大段正文 → context 膨胀，下游失焦 |
| `state_patch` | 黑板增量 | 缺失 → 状态漂移，编排者失去全局视图 |

**上下文传递纪律**：给路径，不给内容。确需内联时 ≤500 tokens（如返修的具体句子）。

---

## 2. 状态黑板（SSOT）

路径：`{WORK_ROOT}/运行态/workflow-state.yaml`

```yaml
chapter: ch03
phase: PRODUCE
artifacts:
  design: 章节/ch03/chapter_design.md
  retrieval: [...]
  draft: 章节/ch03/draft.md
  review: [...]
gates: {gate1: pass, gate2: pass, gate3: pending}
blocking_open: []
retries: {ch03-PRODUCE-R2: 1}
budget: {turns_used: 43, turns_limit: 200}
circuit: CLOSED
trace_ref: 运行态/trace.jsonl
```

**操作规则**
1. 成员启动 = 先读黑板；成员结束 = 必 patch 黑板
2. patch 是增量的、append 式的，不覆盖他人写入
3. 只有编排者可写 `phase` 与 `circuit`
4. `blocking_open` 非空 → 任何成员不得推进到下一阶段

**字段级 patch 语义（evo-7 补，防并发丢更新）**
| 字段类型 | patch 方式 | 示例 |
|---------|-----------|------|
| 列表字段（artifacts.*, blocking_open） | **追加**（append），禁止整表覆写 | `artifacts.retrieval += [新文件]` |
| 计数字段（retries.*, budget.turns_used） | **单调递增**，取 max(旧值, 新值)，禁止回退 | `budget.turns_used = max(旧, 43)` |
| 枚举字段（gates.*, circuit, phase） | 只能沿状态图前进（pending→pass/fail；CLOSED→OPEN→HALF_OPEN→CLOSED），**回退需编排者在 trace 里留因** | gate2: pending→pass |
| 标量覆盖字段（chapter） | 初始化后只读 | — |

并发写冲突处理：两成员同时 patch 同一字段时，后写者必须在文件尾部 patch 注释中声明「与 {对方 msg_id} 并发，已按 merge 规则合并」；无法自动合并 → 发 `BLOCK` 给编排者裁决。

---

## 3. 重试 / 超时 / 预算

| 机制 | 阈值 | 行为 |
|------|------|------|
| 同方式重试 | ≤2 次 | 第 3 次必须换策略 |
| 策略切换 | 第 3 次 | 按介入协议根因 A/B/C/D 切换（A 补证据 / B 改指令 / C 拆步骤 / D 停机报用户） |
| E2 超时 | 60 秒无进展 | 自动升级 E3 |
| 预算预警 | turns_used ≥80% limit | 强制落盘进度 + 回 STATUS，凭日志续跑 |
| 预算耗尽 | turns_used = limit | 保存现场（黑板 + 已落盘产物）上报，不静默丢弃 |

**长任务续跑模式**：大任务先落盘中间产物到约定路径，重启后读该文件跳过已完成部分。审查官 R3 分批核验、检索员多知识点检索均适用。

---

## 4. 熔断 Circuit Breaker

```
CLOSED  ──E5/连续E3──▶  OPEN  ──用户处置后──▶  HALF_OPEN ──探测任务成功──▶ CLOSED
                          │                        │
                          └──禁止一切调度────────探测失败──▶ OPEN
```

**「连续 E3」窗口定义（evo-7 补，消除歧义）**：同一 `correlation_id`（同一章节）下，**滑动窗口 = 最近 3 次成员任务**中 E3 出现 ≥2 次 → 判「连续 E3」触发 OPEN。计数器持久化在黑板 `retries` 字段旁（`e3_window: [任务ID 列表]`），由编排者维护；不同章节的 E3 不合并计数。

- **CLOSED**：正常调度
- **OPEN**：停止一切成员调度，保存现场，通知用户
- **HALF_OPEN**：只放 1 个探测任务；成功回 CLOSED，失败回 OPEN

---

## 5. 降级链（工具层）

```
PubMed MCP（须先 ToolSearch 载入 schema）
  → WebFetch https://pubmed.ncbi.nlm.nih.gov/{PMID}/
  → CrossRef https://api.crossref.org/works/{DOI}
  → WebSearch
  → 标注 [待核实·reason=核验工具不可用]   ← 不得默认通过
```

每层失败必须如实记录，**禁止跳过失败层直接给结论**。

---

## 6. 可观测 trace

路径：`{WORK_ROOT}/运行态/trace.jsonl`，每次成员调用追加一行：

```json
{"msg_id":"ch03-PRODUCE-R2-subject-writer-1","task_id":"ch03-PRODUCE-R2",
 "from":"team-lead","to":"subject-writer","start":"ISO8601",
 "duration_ms":128000,"turns":37,"outcome":"RESULT|ERROR|BLOCK",
 "artifacts":["章节/ch03/draft.md"]}
```

用途：定位瓶颈（哪个阶段最慢）、识别反复失败任务、为 LEARN 提供原始数据。

---

## 7. 交接检查表（dispatch 前逐项过）

- [ ] 任务指令含 `task_id` 与 `correlation_id`
- [ ] 已给出 WORK_ROOT 与全部 `context_refs` 路径
- [ ] 明确要求「结束时 patch 黑板 + SendMessage 回编排者」
- [ ] 声明了本次任务的 turn 预算与超时行为
- [ ] 若是并行分支，确认与其他分支无文件写冲突
- [ ] 若是返修任务，附上 examiner 的 blocking 原文（具体到行号/引文）
