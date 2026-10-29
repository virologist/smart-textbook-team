---
name: team-generation
description: "Dynamic expert-team generation: collapse a senior expert team at per-chapter/per-section granularity from the chapter design + discipline profile, present the composition table for user alignment BEFORE it takes effect, then register members into the runtime dynamic-member registry. Covers the composition proposal algorithm, the hard alignment gate (no effect until user confirms), 3-dimension evaluation (coverage depth / domain match / output accuracy), runtime registration (dynamic-members.yaml), and E3 member-substitution. Load when user asks to build a custom expert team for a specific chapter/discipline, or when E3 escalation needs an equivalent member. Trigger words: 生成团队 / 动态成员 / 团队构成 / 专家坍缩 / 换成员 / 替补 / team generation."
version: 1.0.0
---

# team-generation — 动态专家团队生成（先对齐后生效）

> **本 skill 是「按输入主题动态坍缩生成资深专家团队」的唯一权威源**。
> 设计原则（对齐诊断维度 D1）：坍缩结果必须**先输出、与用户对齐、确认后才生效**——
> 没有这个闸门，误配的团队会把整章写作带进错误的视角，返工成本是一整章。

## 0. 双层成员架构（本团 v2.3 起生效）

| 层 | 定义 | 来源 | 生效方式 |
|---|---|---|---|
| **静态层** | 常驻 5 成员（设计/检索/撰写/审查/可视化） | `plugin.json teamInfo.memberAgents` | 安装即生效 |
| **动态层** | 按章节主题临时生成的专家成员 | `运行态/dynamic-members.yaml`（WORK_ROOT 级注册表） | **用户确认后**由主理人注册 |

**为什么动态层放在 WORK_ROOT 而不是包内**：动态成员是**章节级资产**（换章/换书即失效），
放包内会污染安装态、且多书共用包时互相串扰；放 WORK_ROOT 与 progress/trace 同级，生命周期一致。

## 1. 生成流程（四步，闸门在第 3 步）

```
① 输入收集 → ② 构成提案（generate_team.py）→ ③【闸门】用户对齐确认 → ④ 注册生效
```

### ① 输入收集
必需：`chapter_design.md`（knowledge_scope + 目标受众）+ discipline（学科 profile 名）。
缺失 → 回问，不猜。

### ② 构成提案（只产出提案，不落盘生效）
```bash
python3 scripts/generate_team.py \
  --design "$WORK_ROOT/章节/ch01/chapter_design.md" \
  --profile veterinary --out 运行态/team-proposal-ch01.yaml
```
产出**团队构成表**（yaml），每成员含 `{member_id, role_name, domain, examines, source_profile}`。

### ③【硬闸门】先对齐后生效
主理人把构成表**原文呈现给用户**，明确三问：
1. 这 N 个视角覆盖是否合适？（多/少/错）
2. `examines` 分工是否符合预期？
3. 确认生效 or 修改 or 放弃？

**未获用户明确确认前，禁止执行第 ④ 步**——这是铁律，不因「用户催进度」而跳过。
（诊断依据：团队构成错误 → 写作视角全错 → 整章返工，是全链路最贵的错误类型。）

### ④ 注册生效
用户确认后，主理人把确认的成员写入 `运行态/dynamic-members.yaml`：
```yaml
chapter: ch01
discipline: veterinary
confirmed_by_user: true          # 未经确认禁止写 true
registered_at: "2026-10-30T09:00:00"
members:
  - member_id: poultry-pathologist-vet
    role_name: 禽病学领域专家
    domain: 禽病
    examines: [术语精确性, 因果链完整性, 鉴别点充分性]
    source_profile: veterinary
```

## 2. 动态成员的 spawn 约束（与装配器联动）

- **member_id 命名**：kebab-case，禁止与静态成员同名、禁止中文/下划线
- **spawn 时**：装配器自动把动态层并入白名单（`--allow-dynamic-members` 通道），
  成员 MD 用**通用专家模板 + role 声明段**合成（见 §4）
- **动态成员不是独立 agent 文件**：它们没有 `agents/*.md`，
  spawn prompt 由装配器从注册表条目即时合成——这正是「运行时真生成」的实现方式
- **生命周期**：随章节交付后归档（注册表移入 `学习/团队档案/`），不跨章复用除非用户明确要求

## 3. 三维评估（构成提案自带，供用户对齐时参考）

| 维度 | 判据 | 不足时的动作 |
|---|---|---|
| 知识覆盖深度 | 提案成员的 examines 并集 ⊇ chapter_design 知识域清单 | 补成员或扩 examines |
| 领域匹配度 | 每个知识域有 ≥1 成员 primary 覆盖 | 换更贴近的 role_id |
| 输出准确性保障 | ≥1 成员盯「术语精确性」+ examiner 兜底 4 维 | 补领域术语视角 |

## 4. E3 替补机制（换等价成员）

静态/动态成员连续 E3 时，除按介入协议处置外，**可换等价成员**：

1. **等价判定**：新成员的 examines ⊇ 原成员 examines（覆盖不缩水）
2. **来源优先级**：动态层已有成员 > 按 §1 流程生成新提案（仍要过闸门）
3. **换人记账**：`interventions.md` 记 `{原成员, 新成员, 等价依据, 用户是否确认}`
4. **换人不重置计数**：打回计数按 `correlation_id + 问题指纹` 跨成员累计（防「换人洗计数」）

## 5. 严禁

- ❌ 跳过闸门直接注册（最贵的错误）
- ❌ 动态成员 ID 与静态成员冲突（装配器会拒绝，但不要依赖兜底）
- ❌ 把动态成员写进 `plugin.json`（那是静态层 SSOT；动态层只在 WORK_ROOT）
- ❌ 用动态成员替代 quality-examiner 的审查职责（审查者与生成者分离是契约三原则，不可被动态层绕过）

## 变更记录
- v1.0.0 [2026-10-30] 初版：兑现 Q2=B「运行时真生成新 agent」；闸门先对齐后生效；E3 替补通路
