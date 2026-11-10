# harness-protocol 执行体细节（自 SKILL.md 下沉，2026-11-10）

> 本文件承载 `skills/agent-harness-protocol/SKILL.md` §6.2 / §6.5 的**完整执行体细节**，
> 主文件只留指针。判据数字、命令、字段名与主文件原内容**一字未改**；
> 本文件与脚本实现同步维护，两处漂移以脚本为准并回改本文。

## 6.2 关键指标计算（compute_metrics.py）


每章 DELIVER 后跑 `scripts/compute_metrics.py --work-root $WORK_ROOT`，输出基线报告：

| 指标 | 计算 | 门槛 |
|------|------|------|
| 分派命中率 | 末态 OK 任务 / 派发任务（按 task_id 去重取末态——E1 重试不双扣；P2-6 修复） | ≥ 0.80 |
| 返工率 | 同 task_id ≥2 次成功交付的 review 任务 / review 任务数（ERROR→OK 重试不算返工，单列 retry_rate 参考列；P2-6 修复，旧口径「review R2+」会把既定第二轮审查误判为返工） | ≤ 0.30 |
| blocking 占比 | blocking_open 非空**任务** / 总任务（行口径另列为参考列） | ≤ 0.10 |
| 平均轮次 | 同 task_id 的 trace 行数中位数 | ≤ 6 |
| per-task token | in+out 累加,按 task_type 分桶（行含 estimated:true 时报告标注「不可审计」） | (无硬门槛,首章采基线) |
| **相位级时延** | 按 `phase` 分桶的 P50/max（需 trace 带 `phase`/`start`，C2） | (无硬门槛,首章采基线) |
| **坏行计数** | trace.jsonl 中无法解析的行数 | = 0 |
| **平均并发度** | 时间加权平均并发度（任务视为区间 `[start, start+duration_ms]`，扫描线求同时在跑任务数的时间加权平均）+ 峰值并发（需 trace 带 `start` 且 `duration_ms>0`；P1-4） | (无硬门槛,Q2 动态并行度——固定阈值等于把动态策略写死) |

> **并发度口径（P1-4，2026-11-04）**：① **时间加权平均**而非「峰值」——峰值会高估真实并行水平；
> ② **退化区间排除**——真实运行实测 `start == ts` 且 `duration_ms=0`（未记录任务起始时刻），
> 此时不构成任何时间区间，**排除而非兜底造 1ms 伪区间**（否则会虚构出 ≈0.0 的并发）；
> ③ 无任何可判定区间时输出 `⚠ 不可计算（不是「并发为 0」，是数据不足）`——
> **UNKNOWN 优先于误杀**，与 watchdog 的 `UNKNOWN` 同源原则；
> ④ **不设门槛**：Q2 授权「并发度受 API 速率 / token 预算约束」→ 并行度是动态量，
> 写死阈值等于把动态策略写死。本项仅作瓶颈定位用。

> 本表与 `compute_metrics.py` 实现同步维护（2026-10-15 P2-6：脚本先行修复，本表随改）；
> 静态契约测试 F 系列不校验本表数字——两处漂移以脚本为准并回改本表。

**口径裁决记录（2026-11-04，H1/H2/H3）**：
| 项 | 旧实现 | 旧文档 | 裁决 | 理由 |
|---|---|---|---|---|
| blocking 占比 | trace **行**数作分母 | 「总**任务**」 | 以**任务**为准，行口径保留为参考列 | 同一份数据出两个数，差异足以跨过 ≤0.10 门槛 |
| 返工率 | task_type 前缀 `review-` | 同 | 保留判据，但**不可计算时必须告警** | 漏标 → 指标整行消失且 exit 0，静默失效 |
| 坏行 | 静默 `continue` | 未提 | 计入 `bad_lines` 并在报告标注「数据不完整」 | 分母被动变小且不可区分「任务少」与「日志坏了」 |

**门槛 fail 触发 LEARN 候补**：`signal_type=metric_breach`,≥3 候选或用户 ack 才合并。


## 6.5 P1 三件执行体：并行调度 / 成员契约 / 拆分-合并（2026-11-04 补）

> **背景**：本包此前存在「**协议完备 + 仪表失灵**」的结构性缺口——13 态流水线、契约、门禁
> 在设计层写得完整，但**关键条款只有散文、没有可执行体**：并行度怎么定、成员只写了一半
> 怎么判、单章超上下文怎么拆怎么合，全靠编排者读文档自觉执行。
> 本节把三条条款各落一个脚本 + 退出码判据，与 P0 批次的 `watchdog.py` /
> `validate_envelope.py` / `budget_guard.py` 同构。

#### 6.5.1 并行调度（`scripts/scheduler.py`）

```bash
# 规划本批可并行章节与并发上限（--work-root 是顶层参数，须在子命令之前）
python3 scripts/scheduler.py --work-root "$WORK_ROOT" plan
```

| 退出码 | 含义 | 处置 |
|---|---|---|
| 0 | 计划已生成 | 按 `max_concurrency` 派工 |
| 1 | 依赖未满足 / 存在环 | 阻塞，不得派工 |
| 2 | 输入缺失（book-spec 或 WORK_ROOT 不存在） | 补输入 |

**并发度决策（Q2 授权落地：动态决定，不写死）**——优先级从上到下：

1. 显式 `--max-concurrency`（人工授权）
2. 环境变量 `STB_MAX_CONCURRENCY`
3. 环境变量 `STB_RATE_LIMIT`（速率上限折算）
4. **都没有 → 退化为 1（保守串行）+ 明确告警**

无论来源如何，最终并发数受**可并行章节数**与**协议分支硬上限 `BRANCH_CAP`** 约束。
**禁止把并发度写成固定常量**——Q2 明确「受限于 API 速率还是 token 预算」，
写死等于把动态策略固化成静态假设。

> **依赖判定必须看「最远相位」而非「有无该章」**：`章节/_book/chapter-map.md` 里
> 依赖章**只走到 PRODUCE** 时，下游章**不得**被释放（负例已固化为测试用例
> `test_scheduler_partial_dependency_not_released`）。

#### 6.5.2 成员契约校验（`scripts/contract_check.py`）

```bash
python3 scripts/contract_check.py --work-root "$WORK_ROOT" \
    --member subject-writer --chapter ch03 --mode sections
```

契约 SSOT = `references/member-contracts.json`（每个成员的 `must_produce` / `must_not_write`）。

| 退出码 | 判定 | 处置 |
|---|---|---|
| 0 | `PASS` — must_produce 全部落盘 | 可推进 |
| 1 | `PARTIAL` — 部分落盘 | 按 `on_partial` 处置 |
| 2 | `MISSING` — 应产出物一个都没有 | 按 E2 处置（成员未交付） |
| 3 | `OUT_OF_SCOPE_WRITE` — 越界写 | 拒收（契约三原则②） |
| 4 | 输入缺失 / `CONTRACT_CONFLICT` / 契约文件损坏 | 阻断（判据本身不可信） |

**越界检测的三级写者证据分级**（P1-2，UNKNOWN 优先于误杀）：

| 级别 | 证据来源 | 强度 | 判定 |
|---|---|---|---|
| **L1** | 静态：契约 `must_not_write` × `references/path-ownership.md` | 确定性 | 自有 `must_produce` 落在禁写族内 → **硬矛盾** `CONTRACT_CONFLICT`（阻断）；族内只拥有部分路径 → **软重叠**（仅提示，非矛盾） |
| **L2** | trace.jsonl 里该成员自报的**路径型** artifacts | 较强 | 命中禁写族 → **越界**（阻断） |
| **L3** | 产物文件头部自述的写者（如 `> 撰写：subject-writer`） | 较强 | 命中禁写族 → **越界**（阻断） |
| — | 三级均无证据 | 无 | 只记 `suspected`（**提示，不阻断**） |

**三个实现要点（真实样本踩坑）**：
- **实例 ID 归一**：trace 的 `from` 是实例 ID（`subject-writer-1` / `-2` / `didactic-architect-3`），
  必须剥离尾部 `-N` 后缀才可比对规范角色；
- **路径型 artifact 筛选**：artifacts 混有中文描述文本（「情境策略」「难度标尺+CSV」），
  必须按扩展名/斜杠过滤，否则路径匹配假阳性；
- **越界优先于产物齐备**：判定顺序是「越界 → 齐备」，且**越界产物从 `present` 移除并计入 `missing`**
  —— 越界产出视同未产出（契约三原则②）。

#### 6.5.3 拆分-合并链路（`scripts/merge_sections.py`，Q3 授权落地）

> Q3 授权原文：「单章 token 不受限；如果超过单次 AI 的上下文限度，则拆分分别执行完成后再
> 合并检查和校队/润色修改，确保上下文连贯和衔接。」拆开是三个动作：① 拆分 → ② 合并 →
> ③ **合并后必须走检查/校对/润色**（不得直接进装配）。

```bash
# 合并 + 生成合并后必检清单
python3 scripts/merge_sections.py --work-root "$WORK_ROOT" --chapter ch01
# 只检查已有 draft.md 的衔接（不重新合并）
python3 scripts/merge_sections.py --work-root "$WORK_ROOT" --chapter ch01 --check-only
```

| 退出码 | 含义 |
|---|---|
| 0 | 合并完成且必检清单已生成（可进 `VERIFY-R3`） |
| 1 | 合并后必检未过（衔接问题 / 缺节 / 重复节）——**不得进 VERIFY-R3** |
| 2 | 输入缺失（`sections/` 不存在或为空 / 设计缺节） |

**与 `assemble_sections.py` 的分工**：`assemble_sections.py` = 节级自查 + 拼接 + 拼接清单（**节内视角**）；
`merge_sections.py` = 合并后衔接检查 + 整章必检清单（**章间视角**）。
节与节之间的衔接问题（术语漂移、图位冲突、数据口径打架、段落拼接感）**只有整章视角才看得出来**。

**合并后必检清单（C1-C6）**，落盘 `章节/{ch##}/合并检查清单.json`（归属编排者）：

| 编号 | 检查项 | 级别 | 判定 |
|---|---|---|---|
| C1 | 节序连续性 | 阻断 | 章内节号须连续递增，无跳号/无倒序 |
| C2 | 节号唯一性 | 阻断 | 同节号不得出现两份 |
| C3 | 术语一致性 | 阻断 | 同一术语在章内不得出现两种写法 |
| C4 | 图表位连续性 | 阻断 | 图位编号须为 `{章号}-{序号}` 形态，序号不重复 |
| C5 | 数据标签完整性 | 阻断 | 数值陈述须带 `[实]/[估]/[引]/[待核实]` 标签 |
| C6 | 章节过渡 | 提示 | 相邻节之间须有过渡（承接句/小结） |

> **C3 的两级判据（关键）**：
> **L1 权威源优先**——术语表三级查找（`{WORK_ROOT}/学科标准/术语表.md` >
> `references/profiles/{discipline}.md` §5.1 > example 示例），命中即**阻断**；
> **L2 启发式仅在术语表完全缺失时启用**（近形异写检测），且明确标注「非权威」+ 提示级。
> 反面教训：早期版本在**权威源存在时另造启发式**，19 个候选里 19 个是噪声（误报率 95%），
> 反而把真阳性 `「禽病防治」(×2) vs「禽病防冶」(×1)` 一起淹掉。
> 权威源存在就**必须用它**，不得绕过。

#### 6.5.4 搭接并行裁决门（`scripts/parallel_gate.py`，B3）

> 口径 SSOT = `skills/textbook-pipeline-workflow/SKILL.md` §搭接并行协议。
> 本门把升级 A/C 的两条风险控制从散文变成机械判据；**只报决策、不 spawn 成员**，
> 并行裁决权归编排者（主理人）。`PHASE_ORDER` 23 相位**不变**——
> `SPECIFY-refine` / `VISUALIZE-spec` / `VISUALIZE-final` 是子阶段标签，不是新相位。

| 子命令 | 判据 | 退出码 |
|---|---|---|
| `anchor` | 知识块共享锚「只增不改」（v1 ID 全留 + 字段签名不变；允许新增） | 0 ANCHOR_OK / 1 ANCHOR_VIOLATION / 2 输入错误 |
| `visual-drift` | 冻结稿 vs 返修稿图表位变更率 >0.5（严格大于）⇒ 回退串行 | 0 CONTINUE_PARALLEL / 1 FALLBACK_SERIAL / 2 输入错误 / 3 trace 写失败 |

- **§1.4 路径归属核对的具体结论**：refine↔RETRIEVE、spec↔R2/R3 两组目标路径归属不同
  ⇒ 允许并行；两份只读冻结快照（归编排者）不构成第二写者，详见
  `references/path-ownership.md` v1.5.0 变更记录。
- **不得恒真放行**：无锚区块 / 空锚 / 列错位 / 同一文件自比对 / 冻结稿无图位 ⇒ `exit 2`；
  回归用例含反向例（`tests/test_parallel_gate.py` 25 例）。
- **trace 合规**：回退时经 `record_trace.py` 写 `STATUS` 行（带 `phase=VISUALIZE` +
  显式 `start`，满足 §6.1 的 B2 强制契约）；正常路径不写，不污染 `dispatch_hit_rate`。
- 回退报告带 `learn_signal`（`signal_type: parallel_fallback` + `metric_evidence`），
  接上 learn_v2 的「指标 → 学习 → 协议修订 → 评测回归 → 新基线」回路。
- 编排者 override 脚本决策须记 trace + `review/interventions.md`，否则 learn 侧无法归因。
- **不改变 §预算降级 P3 策略**：预算不足时 VISUALIZE 仍可整段推迟转 W4 补图；
  B3 的 spec 前移是「有余量时并行」，不是强制并行。

---

#### 6.5.5 节级并行与恢复（`scripts/scheduler.py --mode sections` / `assemble_sections.py`，B4）

> 口径 SSOT = `skills/textbook-pipeline-workflow/SKILL.md` §节级并行与恢复协议。
> 与 §6.5.4 同纪律：**脚本只报决策、不 spawn 成员**，波次调度与重派权归编排者。
> `PHASE_ORDER` 23 相位**不变**——节级波次是既有相位内的机制，不是新相位。

**节级 dispatch 的额外必填字段**（缺任一 ⇒ 不得并行派工，退回串行）：

| 字段 | 作用 | 缺失后果 |
|---|---|---|
| `must_produce` | 本节唯一落盘路径 | 不知写哪 ⇒ 可能写整章稿 ⇒ 第二写者覆盖 |
| `section_no` | 节号 | 节号自查与 `exports/imports` 声明失效 |
| `required_terms` | 上游已定义术语 | 上游术语可能被重定义 ⇒ 术语冲突 |
| `target_words` | 本节净字数目标 | 预算降级无法估 token |
| `task_id` | 本节独立任务号 | trace 与 `retries.{task_id}` 无法归因 |

**§1.4 路径归属核对的具体结论（B4）**：同波次各节写入
`章节/{ch##}/sections/{节号}.md`（归 subject-writer）——**路径互不相同** ⇒ 允许并行；
`章节/{ch##}/draft.md` 在节级模式下**不由 writer 写**，由编排者执行的
`assemble_sections.py` 拼接产出 ⇒ 防止并行 writer 各写整章稿造成覆盖。

**缺节恢复的 harness 约束**：

| 分类 | 判据 | 编排者动作 | 成员动作 |
|---|---|---|---|
| `RECOVERABLE` | 上次成功拼接清单含该节（文件后来丢失） | 复用上次 spawn 文案重派该节 | 重做该节，**沿用上轮已确立的引用与标签口径**（不换锚点） |
| `NEVER_PRODUCED` | 清单无该节 / 基线缺失或损坏 | 按 `on_partial=BLOCK` 重派 | 正常生产该节 |

- **恢复报告只报不 spawn**：`运行态/section_recovery_{ch##}.json` 归编排者（路径归属
  v1.6.0），成员只读；成员**不得**因为看到 `RECOVERABLE` 就自行重做并覆盖基线。
- **基线损坏须人工核对**：`baseline_status=corrupt` ⇒ 不得静默当「从未产出」，
  否则会误重派已交付内容、造成版本漂移；须主理人核对拼接清单后人工裁决。
- **退出码语义**（`assemble_sections.py`）：`0` 成功 ｜ `1` 节级自查未过 ｜
  `2` 输入缺失 ｜ `3 RECOVERY_REQUIRED`（已出恢复报告，待编排者重派）。
- **trace 合规**：两种缺节分类都写合规 `BLOCK` trace（带 `phase` 与显式 `start`，
  满足 §6.1 的 B2 强制契约），纳入 `retry_rate`；`--no-trace` 仅供 CI/离线排查。
- **回归覆盖**：节级调度 22 例 + 恢复协议 11 例 + 跨章依赖 12 例，
  共 45 例，均含反向例（条件翻转时结果随之改变），见 `tests/test_scheduler_sections.py`、
  `tests/test_assemble_recovery.py`、`tests/test_cross_chapter_deps.py`。

#### 6.5.6 波次状态与契约回写（`scheduler.py --write-wave-state` / `contract_check.py --wave`，R2）

> 口径 SSOT = `skills/textbook-pipeline-workflow/SKILL.md` §波次状态与契约回写协议。
> 与 §6.5.5 同纪律：**脚本只报不 spawn**，波次计划、契约回写、裁决都归编排者。
> `PHASE_ORDER` 23 相位**不变**——波次状态是既有相位内的机制，不是新相位。

**为什么必须有它**：B4 的节级波次此前只 `print` 到 stdout，调度器算出的波次结构
**没有持久化锚点** ⇒ 契约回写无对象、效率指标无数据源、中断续跑不知上次跑到哪波。

| 环节 | 执行体 | 产物 |
|---|---|---|
| 落盘计划 | `scheduler.py plan --mode sections --chapter ch## --write-wave-state` | `运行态/wave_{ch##}_w{n}.json`（schema `stt.wave_state/1`） |
| 契约回写 | `contract_check.py --chapter ch## --wave {n}` | 增量 patch `contract`/`net_words`/`reason` |
| 主理人裁决 | `contract_check.py --chapter ch## --wave {n} --verdict READY\|BLOCKED\|BUDGET_DEGRADED` | `wave_verdict`/`verdict_by`/`verdict_at`/`verdict_reason` |
| 效率指标 | `compute_metrics.py` | `[9] wave_time` / `parallel_gain` |

**「计划」与「授权」必须分离**（本节核心纪律）：

| 字段 | 谁写 | 初值 |
|---|---|---|
| `proposed_verdict` | 脚本（机器建议） | `READY` / `BUDGET_DEGRADED` |
| `wave_verdict` | **主理人**（正式裁决） | `PENDING` |

脚本写 `wave_verdict` ⇒ 「计划存在」被误读成「已获执行授权」。

**退出码语义**：

| 脚本 | 退出码 | 含义 |
|---|---|---|
| `scheduler.py --write-wave-state` | `0` | 计划成立且波次状态已落盘 |
| | `1` / `2` | 依赖成环 / §C.1 表非法 ⇒ **不落盘** |
| | `5` | 落盘失败（锚点未建立 ⇒ **不得据此派工**） |
| `contract_check.py --wave` | `0` | 回写完成（`wave_verdict` 未被脚本改动） |
| | `4` | 波次状态缺失 / schema 不匹配 / 非法裁决值 |

**净字数口径必须同源** `count_net_words.py`——否则回写值与章节门禁
量的是不同的东西（C-05 病灶：同一规则两份口径）。

**路径归属**：`运行态/wave_{ch##}_w{n}.json` 归主理人（path-ownership v1.7.0）；
波次状态**按波次一个文件**，同波次各节写的是不同的 `sections/{节号}.md`
⇒ 与 §6.5.5 的节级并行不产生双写者。

---
