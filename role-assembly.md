---
name: role-assembly
description: "角色团组装规格——subject-writer 写作视角声明的团队内唯一权威源。定义角色团目的、4 维 examines 规范、kebab-case 命名约定、按 knowledge_scope 的组装算法与标准角色示例。writer 写 draft frontmatter 前必读。"
version: 1.0.0
---

# 角色团组装规格（role-assembly）

> 本文件是「多专家角色组装」的**团队内 SSOT**。subject-writer（祝书白）写作前按本规格组装角色团并声明于 draft frontmatter，供 quality-examiner（严正词）R2 复核对照。
> 角色团是**写作视角声明**（writer 内部多视角自检），**不是真实 spawn 子代理**——无需任何外部 agent 或外部文件。

## 1. 目的

writer 单视角写正文，易在领域术语、体例规范、学段适配三个维度失衡。角色团让 writer 在写作前显式声明「以哪些视角、盯哪些维度」，examiner R2 据此对照复核，避免「写完才发现术语不统一 / 案例不适合高职生」。

## 2. 角色团最小构成（3 视角，可扩展）

| 视角 | 默认 role_id（kebab-case） | role_name | 盯什么（examines） |
|------|---------------------------|-----------|-------------------|
| 领域 | `{domain}-specialist` | {领域}领域专家 | 术语精确性、因果链完整性、鉴别点充分性 |
| 编辑 | `textbook-senior-editor` | 教材资深编辑 | 术语一致性、引用格式、段落节奏 |
| 学段 | `vocational-edu-adapter` | 高职学段适配 | 学段可消化性、公式最小化、案例密度 |

## 3. 4 维 examines 规范（examiner R2 兜底基准 · SSOT）

> **本节是 4 维规范的唯一权威源（SSOT）**。quality-examiner.md 中的同形表格是执行副本；
> 两处不一致时**以本节为准**，改基准先改本节，examiner 副本随改。

| 维度 | 定义 | 可观察判据 |
|------|------|-----------|
| 术语精确性 | 学科术语规范、无口语化/自造词 | 与教材术语表 /《兽药典》/ ICTV 一致 |
| 因果链完整性 | 病因→病理→症状→诊断→防治逻辑闭环 | 无断环、无「有因无果」 |
| 鉴别点充分性 | 同类疾病的鉴别特征给足 | 每对易混疾病 **≥3 条**鉴别点（2026-10-15 P2-2 统一口径，原 examiner 副本 ≥2 作废） |
| 学段可消化性 | 高职生能读懂、复述、应用 | 段落 ≤200 字、抽象概念有实例锚点、先 How 后 Why |

> examiner 的 R2 固定基准就是这 4 维。角色团的 examines 是「额外视角」，**不替代** 4 维兜底——某角色 examines 未覆盖某标准维不构成 FAIL（4 维由 examiner 兜底）。

## 4. 命名约定

- **role_id**：小写 kebab-case（连字符），语义化，如 `poultry-pathologist-vet`、`textbook-senior-editor`、`vocational-edu-adapter`
- **禁止**：下划线（`domain_expert`）、泛名（`领域专家`）、中英混排
- role_name：中文可读名，如「禽病学领域专家」

## 5. 组装算法

1. 读 `chapter_design.md` 的 `knowledge_scope` 与目标受众
2. 定「领域视角」：按知识域映射领域 role_id（见 §6）
3. 固定「编辑视角」+「学段视角」：始终激活 `textbook-senior-editor` + `vocational-edu-adapter`
4. 声明于 draft frontmatter（格式见 §7）
5. 每角色 examines ≥1 项可观察维度（2026-10-15 P2-2 对齐 evo-10 口径：**全空 = 无效声明 → blocking**；声明 3 项但未覆盖 4 标准维**不构成 FAIL**——覆盖面由 examiner 4 维兜底，与 quality-examiner.md「examines 声明不可自证」条款一致。原「≥3 项否则 blocking」与该条款矛盾，废止）

## 6. 领域 role_id 映射表（按 knowledge_scope 扩展）

| 知识域 | role_id | role_name |
|--------|---------|-----------|
| 禽病 | `poultry-pathologist-vet` | 禽病学领域专家 |
| 猪病 | `swine-pathologist-vet` | 猪病学领域专家 |
| 反刍动物病 | `ruminant-pathologist-vet` | 反刍动物病领域专家 |
| 宠物/小动物 | `small-animal-clinician-vet` | 小动物临床专家 |
| 人兽共患病 | `zoonosis-specialist` | 人兽共患病专家 |
| 病原学/病毒 | `virology-specialist` | 病毒学专家 |
| 免疫学 | `immunology-specialist` | 免疫学专家 |
| 流行病学 | `epidemiology-specialist` | 流行病学专家 |
| 实验室诊断 | `lab-diagnostics-specialist` | 实验室诊断专家 |
| 药理/兽药 | `veterinary-pharmacology-specialist` | 兽医药理专家 |

> 表内未覆盖的知识域：writer 按 kebab-case 约定自行构造 `{domain}-{role}`，并在 frontmatter 声明 role_name 与 examines，不阻塞写作。

## 7. 声明格式（draft frontmatter 强制）

```yaml
角色团:
  - role_id: poultry-pathologist-vet
    role_name: 禽病学领域专家
    examines: [术语精确性, 因果链完整性, 鉴别点充分性]
  - role_id: textbook-senior-editor
    role_name: 教材资深编辑
    examines: [术语一致性, 引用格式, 段落节奏]
  - role_id: vocational-edu-adapter
    role_name: 高职学段适配
    examines: [学段可消化性, 公式最小化, 案例密度]
```

## 8. 变更记录

- v1.0.0 [2026-09-03] 初版：从 content-forge 旧 `expert-pool.yaml` 解耦，团队内自包含 SSOT；消除外部路径依赖、双命名体系（连字符 vs 下划线）与 examines 字段缺失三类断链
