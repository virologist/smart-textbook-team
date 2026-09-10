---
name: learn-protocol
description: "LEARN phase protocol for the textbook team: harvest signals from interventions.md / r3_verification_log / round reports, convert to minimal rule drafts, file into the candidate pool (学习/le候补/), and merge into evolution rounds only after ≥3 candidates or user ack. Trigger words: 经验沉淀 / LEARN 阶段 / 候补池 / 提取教训 / 本章学到了什么 / learn phase / post-mortem."
version: 1.0.0
---

# learn-protocol — LEARN 阶段协议

> 主理人在 Phase H（DELIVER 后自动触发）按本协议执行。**原则：LEARN 只产候选规则，不改 agent MD——合并需 ≥3 候选或用户 ack。**

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

### 2. 规则草案生成

每条信号转成**最小可操作规则**——格式：「在 X 情形下因为 Y 出现了 Z，应当 W」。一条草案只解决一个具体问题，禁止「要注意质量」式空话。

### 3. 存入候补池

写入 `学习/le候补/{日期}_{ch##}_候补.yaml`，格式：

```yaml
- date: YYYY-MM-DD
  chapter: ch##        # 真实章节；self-evo 表示自我进化留档
  signal_type: 反复打回点 | 介入命中 | 核验失败 | 红线命中 | 延迟超预算
  observed_pattern: {具体描述，含证据文件与行号}
  proposed_rule: {一句可执行规则}
  target: {待修改的 agent ID 或 skill 名}
  priority: P0 | P1 | P2
  status: OPEN         # 解决后就地改 RESOLVED + 补 resolution 字段
```

## 合并条件与流程

1. **阈值**：候补池累计 ≥3 条 OPEN 且同 target，或用户明确 ack
2. **合并 = 一次 evo 轮**：按 priority 排序落地到 target 文件 → 运行可用基准验证（当前环境无 tests/ 目录；若后续建立 `tests/test_smart_textbook_team.py` / `tests/test_orchestration_v2.py` 则必跑，未建立时以人工审查 + 抽查替代）→ 验证通过才 commit + tag evo-N
3. **关闭**：落地后将对应条目就地标 `RESOLVED` + `resolution: evo-N 已落地（具体条款位置）`
4. **铁律**：报告文字 ≠ 机制运转——「已记入候补池」必须等于实体 yaml 存在

## 反模式

- 编造候补（无证据文件支撑的 observed_pattern）
- LEARN 顺手直接改 agent MD（绕过合并门禁）
- 候补池只进不出（OPEN 条目超过 10 条未清理 = 提议一次合并评审）
