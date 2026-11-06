---
name: learn-protocol
description: "LEARN phase protocol v2 (learn_v2) for the textbook team: harvest signals from interventions.md / r3_verification_log / round reports AND from mechanical metric-baseline breaches, convert to minimal rule drafts, file into the candidate pool (学习/候补/), and merge into evolution rounds only after the metric review gate + protocol-eval regression. Trigger words: 经验沉淀 / LEARN 阶段 / 候补池 / 提取教训 / 本章学到了什么 / 指标越界 / 基线偏离 / metric breach / learn phase / post-mortem."
version: 2.1.0
---

# learn-protocol — LEARN 阶段协议（learn_v2）

> 主理人在 Phase H（DELIVER 后自动触发）按本协议执行。**原则：LEARN 只产候选规则，不改 agent MD。**
>
> **v2 变化（2026-11-04 B2，补诊断 Q3「指标-改进闭环缺失」）**：新增**机械触发**
> （指标偏离基线 >20% 或破红线 → 自动生成候补）、**指标评审门**、**protocol-eval 回归**
> 与**基线重置**。原「≥3 候选或用户 ack」保留为**补充触发**，不再是唯一入口。
> 完整回路：`指标 → 学习 → 协议修订 → 评测回归 → 新基线`。
>
> **v2.1 变化（2026-11-05 R1，补复诊 §3.2 R1）**：第 4 步「protocol-eval 回归」从
> **文字承诺落地为执行体** `scripts/protocol_eval.py`（5 组件离线评测，门槛 ≥0.80，
> 失败项清单可定位）。此前该步只写在流程里、零实现 ⇒ 闭环缺末环、改协议变成盲改。

## 何时使用

- DELIVER 完成后（Phase H 自动触发）
- 用户说「总结本章教训」「沉淀经验」
- 候补池条数达到合并阈值时提议合并

## 三步曲

### 1. 数据收集（扫描四类信号源）

| 信号源文件 | 提取什么 |
|-----------|---------|
| `章节/{ch##}/review/interventions.md` | 反复触发的打回点（同 blocking ≥2 轮）→ 规则缺陷；介入协议 A/B/C/D 命中次数 → 成员薄弱类型 |
| `章节/{ch##}/review/r3_verification_log.md` | 核验失败模式（哪类 [实] 最易判错：标识符假/主题错配/数据点不可定位的占比） |
| `章节/{ch##}/review/round*_report.md` | 被拒绝的边界调用（GOF/隐私/政治敏感拒绝次数）→ 红线命中频度 |
| `运行态/trace.jsonl` | 各 Phase 实际耗时 vs 延迟预算（超预算 ≥50% 的阶段） |
| **`运行态/metrics_baseline.jsonl`** + **`运行态/metrics_delta.json`**（v2 新增） | 指标相对 running mean 的偏离与破红线项；这是**机械触发**的唯一权威信号源，不依赖主观复盘 |

### 2. 规则草案生成

每条信号转成**最小可操作规则**——格式：「在 X 情形下因为 Y 出现了 Z，应当 W」。一条草案只解决一个具体问题，禁止「要注意质量」式空话。

### 3. 存入候补池

写入 `学习/候补/{日期}_{ch##}_候补.yaml`，格式（**`signal_type` 枚举为 SSOT，8 值**：`反复打回点 | 介入命中 | 核验失败 | 红线命中 | 延迟超预算 | token_overrun | metric_breach | citation_r7_flagged`——`metric_breach` 与 `token_overrun` 是 2026-10-29 补入；**`citation_r7_flagged` 是 ★J7 v2.10.4 补入**：R7 批量复核（scripts/verify_citations_r7.py）标记的「部分支持（定量/定性未获支撑）」锚点自动生成候补，供 L2/L3 内容返修批次消费——此前 R7 结果只落在 review/r7_result.json，无 learn 侧通路，返修批次容易漏掉这些锚点）：

```yaml
- date: YYYY-MM-DD
  chapter: ch##        # 真实章节；self-evo 表示自我进化留档
  signal_type: 反复打回点 | 介入命中 | 核验失败 | 红线命中 | 延迟超预算 | token_overrun | metric_breach | citation_r7_flagged
  observed_pattern: {具体描述，含证据文件与行号}
  proposed_rule: {一句可执行规则}
  target: {待修改的 agent ID 或 skill 名}
  priority: P0 | P1 | P2
  status: OPEN         # 解决后就地改 RESOLVED + 补 resolution 字段
```

## learn_v2：机械触发（指标 → 候补）

> 这一节是 v2 的核心。**不再依赖主理人「想起来要总结」**——指标越界是机械信号。

### 触发条件（满足任一即必须执行）

1. `metrics_baseline.py compare` 返回 **exit 1**（任一指标偏离 running mean >20%，或破红线）
2. `compute_metrics.py` 自身返回 exit 1（单次门禁 FAIL）
3. 每章 DELIVER 后固定跑一次 `metrics_baseline.py record`（append-only 追加基线）

### 与基线工具的接口契约（SSOT：`scripts/metrics_baseline.py`）

| 命令 | 用途 | 退出码 |
|---|---|---|
| `python3 scripts/metrics_baseline.py record --work-root "$WORK_ROOT" --chapter ch## --protocol-version <ver>` | DELIVER 后追加一行快照 | 0 成功 / 2 输入错 / 3 基线损坏 |
| `python3 scripts/metrics_baseline.py compare --work-root "$WORK_ROOT" --chapter ch## --json 运行态/metrics_delta.json` | 输出 delta 表 + 越界告警 | **0 无越界 / 1 越界（触发本节的机械流程）/ 2 / 3** |
| `python3 scripts/metrics_baseline.py list --work-root "$WORK_ROOT"` | 查看分段历史 | 0 / 3 |
| `python3 scripts/metrics_baseline.py reset --work-root "$WORK_ROOT" --reason "..." --confirm` | 协议合入后开新分段 | 0 / 2 / 3 |

基线文件 `运行态/metrics_baseline.jsonl` **append-only、永不覆写**。`reset` 只追加一行
`type=reset` 分段标记，旧行全部保留可审计；`compare` 只取最后一个 reset 之后的记录。

### 自动生成的候补条目（必须带指标证据）

compare 返回 1 时，对**每一条告警**生成一条 `signal_type: metric_breach` 候补：

```yaml
- date: YYYY-MM-DD
  chapter: ch##
  signal_type: metric_breach
  observed_pattern: "{指标名} 基线 {b} → 当前 {c}（delta {±x%}），来源 运行态/metrics_delta.json；关联 trace 摘要 {相位/任务ID}"
  proposed_rule: "{一句可执行规则，须指向具体相位或成员}"
  target: {agent ID 或 skill 名}
  priority: P0 | P1 | P2     # 破红线 = P0；纯偏离 >20% = P1
  status: OPEN
  metric_evidence:            # learn_v2 新增：缺此字段的 metric_breach 候补无效
    metric: {指标名}
    baseline: {b}
    current: {c}
    delta: {±x}
    red_line: true | false
    delta_report: 运行态/metrics_delta.json
```

**铁律**：`metric_evidence` 必须由 `metrics_baseline.py --json` 的机器输出填，
禁止手写或估算；「参考了指标」这种无文件支撑的表述按编造候补处理。

## 合并条件与流程（v2：两道触发 + 两道门）

**触发（二选一）**
- **机械触发**（v2 主路径）：出现 1 条及以上 `metric_breach` 候补 → 直接进入指标评审门
- **补充触发**（v1 保留）：候补池累计 ≥3 条 OPEN 且同 target，或用户明确 ack

**流程**
1. **阈值 / 触发**：见上
2. **指标评审门（v2 新增，管家节点裁决）**：逐条核对 `metric_evidence` 与
   `metrics_delta.json` 是否一致、拟议改动是否真能影响该指标、是否有更简单的解释
   （样本量不足 / trace 坏行 / 一次性外部抖动）。裁决 **合入** 或 **驳回**；
   驳回须在候补条目写 `resolution: 驳回理由`，不得直接删除。
3. **合并 = 一次 evo 轮**：按 priority 排序落地到 target 文件 → 跑包内四份门禁
   （`test_router_eval` / `test_smart_textbook_team` / `test_vendor_core` / `test_manifest_sync`，
   全 exit 0 才可 commit + tag evo-N）
4. **protocol-eval 回归（v2 新增）**：协议改动后必须复跑路由 eval 与相位一致性检查，
   确认「改动没有让别的指标退化」；回归不通过 = 回滚该条改动，候补保持 OPEN。
   **R1（2026-11-05）落地**：本步不再是文字承诺，执行体为 `scripts/protocol_eval.py`
   （协议组件离线评测，5 组件：路由置信度阈值 / 熔断窗口 / 预算优先级 / 节级拓扑 / 恢复分类）。

   ```bash
   # 合入前的协议评测闸门（分数 <0.80 即拒绝合入，与 router eval 同门槛）
   python3 scripts/protocol_eval.py                       # 人读格式：分数 + 失败项清单
   python3 scripts/protocol_eval.py --json                # 机器可读
   python3 scripts/protocol_eval.py --component circuit-breaker   # 只评某组件
   ```

   | 退出码 | 含义 | 动作 |
   |---|---|---|
   | 0 | 评测得分达标（0-1 量纲，≥0.80） | 允许进入第 5 步（基线重置） |
   | 1 | 评测得分未达标（0-1 量纲，<0.80） | **拒绝协议合入**：回滚该条改动，候补保持 OPEN，不得基线重置 |
   | 2 | 输入错误（用例集缺失） | 修输入后重跑 |
   | 3 | 用例集结构损坏 | 修用例集后重跑 |

   门槛口径：**评测得分 = 各组件 eval 通过项 / 总项**（跨组件合并计算），门槛 **≥0.80**。
   ⚠️ 此处 0-1 量纲是**协议评测分数**（与路由置信度的 0-100 量纲不是同一回事）。
   双闸判定：除总分门槛外，**每个组件**也须 ≥0.80——合并口径会稀释单组件失效
   （实测熔断组件改坏后总分仍 0.882），组件级底线是防「坏协议被放行」的最后一道闸。
   失败项清单必须逐条列出（含用例 ID + 实际行为 vs 期望行为），
   便于定位是「协议写错」还是「执行体没实现」。
   **边界纪律**：protocol-eval **只报分、不改协议**——协议修订权在主理人 + 管家节点评审门。
5. **基线重置（v2 新增）**：合入且回归通过后，用 `metrics_baseline.py reset --reason "evo-N ..." --confirm`
   开新分段，**`--reason` 必须含 evo 编号与 protocol_version**，实现「协议版本号联动」。
   重置前旧基线必须已在 `list` 中可查（审计留痕）
6. **关闭**：落地后将对应条目就地标 `RESOLVED` + `resolution: evo-N 已落地（具体条款位置）`
7. **铁律**：报告文字 ≠ 机制运转——「已记入候补池」必须等于实体 yaml 存在

## 反模式

- 编造候补（无证据文件支撑的 observed_pattern）
- LEARN 顺手直接改 agent MD（绕过合并门禁）
- 候补池只进不出（OPEN 条目超过 10 条未清理 = 提议一次合并评审）
- **`metric_breach` 候补缺 `metric_evidence` 或数值靠手写**（必须用 `--json` 机器输出）
- **静默重置基线**（直接改/删 `metrics_baseline.jsonl`、或 reset 不带 `--reason`/`--confirm`）——这会抹掉漂移证据，等同虚报完成
- **协议合入后跳过 protocol-eval 回归**（改了 A 指标却没检查 B 是否退化）
- **把 compare 的 exit 1 当成「本次任务失败」**：它是学习触发信号，不是交付门禁；交付门禁仍以 `compute_metrics.py` 与四份测试为准
