---
name: role-assembly
description: "角色团组装规格——subject-writer 写作视角声明的团队内唯一权威源。定义角色团目的、4 维 examines 规范、kebab-case 命名约定、按 knowledge_scope 的组装算法与标准角色示例。writer 写 draft frontmatter 前必读。"
version: 2.0.0
---

# 角色团组装规格（role-assembly）

> 本文件是「多专家角色组装」的**团队内 SSOT**。subject-writer（祝书白）写作前按本规格组装角色团并声明于 draft frontmatter，供 quality-examiner（严正词）R2 复核对照。
> 角色团是**写作视角声明**（writer 内部多视角自检），**不是真实 spawn 子代理**——无需任何外部 agent 或外部文件。
>
> **可达性（v1.1.0，2026-10-29）**：本文件位于 `references/`，由装配器 `resolve_shared_refs()` 自动收录并注入成员 spawn 文案的【专家包资源绝对路径】清单——成员可直接 Read，禁止从 scripts 路径反推包根。此前位于包根时该注入位为空（横向归因 ①）。

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
| 术语精确性 | 学科术语规范、无口语化/自造词 | 与教材术语表 + **学科 profile §2「术语权威源」**一致（v2.0.0 解耦；原写死《兽药典》/ICTV，跨专业失效） |
| 因果链完整性 | 病因→病理→症状→诊断→防治逻辑闭环 | 无断环、无「有因无果」 |
| 鉴别点充分性 | 同类疾病的鉴别特征给足 | 每对易混疾病 **≥3 条**鉴别点（2026-10-15 P2-2 统一口径，原 examiner 副本 ≥2 作废） |
| 学段可消化性 | 高职生能读懂、复述、应用 | 段落 ≤200 字、抽象概念有实例锚点、先 How 后 Why |

> examiner 的 R2 固定基准就是这 4 维。角色团的 examines 是「额外视角」，**不替代** 4 维兜底——某角色 examines 未覆盖某标准维不构成 FAIL（4 维由 examiner 兜底）。

## 4. 命名约定

- **role_id**：小写 kebab-case（连字符），语义化。领域视角按 profile §1 映射表取值
  （形如 `{domain}-specialist`）；固定视角恒为 `textbook-senior-editor`、`vocational-edu-adapter`
- **禁止**：下划线（`domain_expert`）、泛名（`领域专家`）、中英混排
- role_name：中文可读名，如「禽病学领域专家」

## 5. 组装算法

1. 读 `chapter_design.md` 的 `knowledge_scope` 与目标受众
2. 定「领域视角」：按知识域映射领域 role_id（见 §6）
3. 固定「编辑视角」+「学段视角」：始终激活 `textbook-senior-editor` + `vocational-edu-adapter`
4. 声明于 draft frontmatter（格式见 §7）
5. 每角色 examines ≥1 项可观察维度（2026-10-15 P2-2 对齐 evo-10 口径：**全空 = 无效声明 → blocking**；声明 3 项但未覆盖 4 标准维**不构成 FAIL**——覆盖面由 examiner 4 维兜底，与 quality-examiner.md「examines 声明不可自证」条款一致。原「≥3 项否则 blocking」与该条款矛盾，废止）

## 6. 领域 role_id 映射：profile 加载协议（v2.0.0 解耦）

> **为什么改（2026-10-30 实测）**：v1.x 本节是一张**写死的兽医映射表**（10 行全部兽医域），
> 且 §3 判据基准写死《兽药典》+ ICTV。跨专业复用（法学/计算机/经济等）时**该表整体失效**，
> 而规范本身对换专业这件事毫无提示——这是"看起来通用、实际单学科"的隐性耦合。

### 6.1 加载协议

1. **取学科标识**：优先用 `chapter_design.md` / draft frontmatter 的 `discipline` 字段；
   未声明 → 由主理人在派单指令中给出；**两者皆无 → 回落 `veterinary`（默认 profile）**。
2. **定位 profile 文件**：`references/profiles/{discipline}.md`（相对专家包根）。
   本目录由装配器 `resolve_shared_refs()` 递归收录，成员可直接 Read，**禁止猜路径**。
3. **读取映射表**：profile 的「§1 领域 role_id 映射表」即本节权威表。
4. **文件缺失处理**：目标 profile 不存在 → 回落到 `veterinary` 并在回传 `issues` 中声明
   「profile {X} 缺失，已回落 veterinary」——**不静默换学科**（与栅格化降级同纪律）。

### 6.2 内置 profile 清单

| discipline | 文件 | 说明 |
|---|---|---|
| `veterinary` | `references/profiles/veterinary.md` | **默认**；禽病/猪病/人兽共患病等 10 域 |
| `computer-science` | `references/profiles/computer-science.md` | 算法/软工/网络/AI 等 10 域 |
| `law` | `references/profiles/law.md` | 民法/刑法/行政法/国际法等 10 域 |

**新增学科**：复制任一 profile 为 `references/profiles/{discipline}.md` 并改写四节即可，
**无需改动本规范、无需改动任何成员 MD、无需改动装配器**。

### 6.3 表内未覆盖的知识域

writer 按 kebab-case 约定自行构造 `{domain}-{role}`，并在 frontmatter 声明
role_name 与 examines，不阻塞写作（与 v1.x 同）。

## 7. 声明格式（draft frontmatter 强制）

```yaml
角色团:
  # 领域视角：role_id 从 profile §1 映射表按 knowledge_scope 取值（见 §6）
  # 下例为【示意写法】——veterinary profile 下应填 poultry-pathologist-vet 等具体值，
  # computer-science profile 下应填 algorithms-specialist 等。本体不写死任何学科 ID。
  - role_id: '{domain}-specialist'
    role_name: '{领域}领域专家'
    examines: [术语精确性, 因果链完整性, 鉴别点充分性]
  - role_id: textbook-senior-editor
    role_name: 教材资深编辑
    examines: [术语一致性, 引用格式, 段落节奏]
  - role_id: vocational-edu-adapter
    role_name: 高职学段适配
    examines: [学段可消化性, 公式最小化, 案例密度]
```

> **v2.0.0 变更**：示例原本写死 `poultry-pathologist-vet`（兽医域）。
> 现改为学科中立的 `{domain}-specialist` 示意写法 + 注释说明取值来源，
> 使规范本体**零学科常量**（门禁 F30c 校验）。

## 8. 变更记录

- v1.0.0 [2026-09-03] 初版：从 content-forge 旧 `expert-pool.yaml` 解耦，团队内自包含 SSOT；消除外部路径依赖、双命名体系（连字符 vs 下划线）与 examines 字段缺失三类断链
- v1.1.0 [2026-10-29] 从包根移入 `references/`：修复「SSOT 可达性依赖未声明推导链」缺陷（成员需从 scripts 路径 dirname 两次反推包根）。移动后由装配器自动注入，零代码改动
- **v2.0.0 [2026-10-30] 学科解耦（唯一重构项）**：
  - §6 写死的 10 行兽医映射表 → 改为 **profile 加载协议** + 内置 3 个 profile（veterinary 为默认）
  - §3「术语精确性」判据基准由写死的《兽药典》/ICTV → 改为**引用 profile §2 术语权威源**
  - 新增学科只需加 `references/profiles/{discipline}.md`，不动规范/成员 MD/装配器
  - profile 缺失 → 回落 veterinary 并在 issues 显式声明（不静默换学科）
