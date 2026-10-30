---
name: gap-types
description: "知识缺口清单的 gap_type 枚举（SSOT）——architect 拆解缺口清单、scout 按类型检索的唯一对照表。此前 gap_type 仅在 scout 输入契约出现 2 次，无枚举、无产出方归属（批次 C9 补）。"
version: 1.0.0
---

# 知识缺口类型枚举（gap types）

> **谁用**：didactic-architect（把 chapter_design §B「数据需求」拆成缺口清单）、
> literature-scout（按 gap_type 选择检索策略与核验深度）、subject-writer（按缺口类型标注 `[待核实·reason=...]`）。

## 1. 枚举（7 类）

| gap_type | 含义 | 典型触发词 | 检索策略倾向 | 核验深度 |
|---|---|---|---|---|
| `epidemiology` | 流行病学数据 | 发病率/病死率/流行率/感染率/季节分布 | Tier 0→1→4（流行病学数据权威源优先） | 高：≥2 源一致 |
| `pathogen-biology` | 病原生物学特性 | 形态/结构/血清型/基因型/培养特性 | Tier 0→1（教科书与综述优先） | 中：权威教科书可单源 |
| `clinical` | 临床症状/体征 | 症状/体征/病变/剖检变化 | Tier 0→2（临床手册优先） | 中 |
| `diagnosis-method` | 诊断方法与判读 | PCR/ELISA/抗体水平/Ct 值/判定标准 | Tier 1→4（方法学文献+标准） | 高：标准须现行有效 |
| `treatment-control` | 治疗/防控措施 | 药物/剂量/免疫程序/休药期/消毒 | Tier 0→4（兽药典/公告最优先） | **最高：法规类须现行有效** |
| `economics` | 经济损失/成本 | 损失/成本/效益/价格 | Tier 2→3（行业报告/统计年鉴） | 低-中：标注估算口径 |
| `frontier` | 前沿进展 | 新技术/新疫苗/新毒株/研究热点 | Tier 1→2（近 5 年文献） | 中：标注时效 |

## 2. 缺口清单格式（architect 产出 → scout 消费）

```yaml
章节: ch03
缺口清单:
  - gap_id: ch03-g01
    gap_type: epidemiology
    描述: 某病 2020 年后国内家禽发病率变化趋势
    上下文: §1.2 流行现状段需要近年数据支撑
    优先级: P0        # P0=正文必需 / P1=增强 / P2=可选
  - gap_id: ch03-g02
    gap_type: treatment-control
    描述: 某疫苗现行免疫程序与剂量
    上下文: §4.1 免疫程序表
    优先级: P0
```

## 3. 职责归属（批次 C9 明确）

| 环节 | 归属 | 动作 |
|---|---|---|
| **拆解缺口清单** | **didactic-architect** | 从 chapter_design §B「数据需求」逐条转成上述格式，落 `章节/{ch##}/gaps.md` |
| **消费缺口清单** | literature-scout | 按 `gap_type` 选检索策略；每缺口一个检索任务（可 fan-out ≤5） |
| **缺口回填** | subject-writer | 检索结果回填正文；未回填者标 `[待核实·reason=gap_id 未命中]` |

> 路径归属：`章节/{ch##}/gaps.md` 归 didactic-architect（已登记进 path-ownership 表）。

## 变更记录
- v1.0.0 [2026-10-30] 初版（批次 C9）：7 类枚举 + 清单格式 + 三方职责归属
