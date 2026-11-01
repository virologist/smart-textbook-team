---
name: audience-profiles
version: 1.0.0
description: "学段判据表 SSOT——writer 撰写 / examiner R2 学段可消化性维与 R5 易懂易学维 / didactic-architect 设计输出按 audience 档取判据。学科中立（学科常量禁入本文件）；学段常量禁入通用层，门禁同 check_domain_neutral（本文件与 profiles/ 豁免）。"
---

# 学段受众判据表（audience profiles）

> 本文件是「按目标学段取写作/审查判据」的**唯一权威源（SSOT）**。
> subject-writer（按档行文）、quality-examiner（R2 学段维 / R5 易懂易学维按档检查）、
> didactic-architect（chapter_design 声明 audience 档）三方判据全部以本表为准；
> 成员 MD 与通用层文档**只许引用本表，不得复述学段画像**（ADR-02 同构纪律——
> 学段常量词禁入通用层，由 `scripts/check_domain_neutral.py` 机械校验）。

## 0. 加载协议（audience 取值枚举）

audience 取值来自 `chapter_design` frontmatter（didactic-architect 必填声明）或
`progress.py init/book init --audience`（主理人派单输入）：

- 合法枚举：`高职专科 | 职业本科 | 学术本科 | 研究生`
- **未声明 → 回落 `职业本科`（默认档）**，且须在回传 `issues` 中显式声明
  「audience 未声明，已回落职业本科」——**禁止静默回落**（与 profile 缺失回落
  veterinary 同纪律）
- 声明值不在枚举内 → examiner R1 / 主理人门禁 1 判 blocking（判据 Q2，
  与既有结构门禁同层执行，不新增脚本）
- 换学段 = 换判据基准：同一章 audience 变更后，writer/examiner 按 §1 对应档
  逐列重校（不豁免已通过轮次）

## 1. 判据表（每档一行，机器可解析；五维红线不豁免）

| 学段 | 句长锚点 | 案例密度 | 公式纪律 | 结构裁剪（引 chapter-structure §5） | 术语铺垫 |
|------|---------|---------|---------|-----------------------------------|---------|
| 高职专科 | ≤150 字/段 | 每知识块 ≥1 案例锚点 | 公式最小必要化，每个公式配文字解释 | 可裁要素 8 与要素 4 细分；要素 1/2/5/7 不可裁 | 每个抽象术语首现必配实例 |
| 职业本科 | ≤200 字/段 | 每节 ≥1 案例锚点 | 公式配推导要点 | 八要素全备，要素 4 含岗位胜任维 | 首现给全称+应用情境 |
| 学术本科 | ≤250 字/段 | 每章 ≥2 案例 | 公式完整推导可保留 | 八要素全备 | 首现给全称 |
| 研究生 | ≤300 字/段 | 案例可降为文献实例 | 公式+证明链 | 可裁要素 2/6，须补研究前沿与方法学 | 学科默认 |

> **红线不豁免**：五维评分与 80 分红线在任何档都不豁免（chapter-structure §5 既有口径）；
> 本表只改「可消化性判据的档位基准」，不改质量红线。
> examiner R2 学段可消化性维、R5 易懂易学维的量化阈值（≥2 处 / ≥30% 等）
> 沿用 `references/role-assembly.md` §3，本表提供的是「按哪档基准判」的取数依据。

## 2. 执行挂点

- **didactic-architect**：`chapter_design.md` frontmatter 必含 `audience: <枚举值>`
  （输入契约已有学段字段，本条把声明钉进输出契约）
- **subject-writer**：按 §1 对应档逐列执行（句长/案例/公式/术语铺垫四列是行文判据；
  替代成员 MD 内的学段画像写死）
- **quality-examiner**：R2 学段可消化性维与 R5 易懂易学维按对应档逐列检查；
  R1 校验 `audience:` ∈ §0 枚举（判据 Q2）
- **writer 角色团**：`vocational-edu-adapter` role_id 恒定（kebab-case 稳定标识，
  不随档改名——保 draft frontmatter 兼容），role_name 与判据基准按 audience 档挂本表

## 3. 变更记录

- v1.0.0 [2026-11-01] 初版（#71 批次 2）：四档判据表 + 加载协议（回落须声明）
  + 执行挂点；学科中立零常量——本文件是学段常量词的唯一豁免载体（连同 profiles/）
