---
name: profile-veterinary
discipline: veterinary
displayName: 兽医 / 畜牧（默认 profile）
version: 1.0.0
---

# 学科 profile：兽医 / 畜牧（veterinary）

> **默认 profile**：未指定学科时使用本文件。
> 加载协议见 `references/role-assembly.md` §6。

## 1. 领域 role_id 映射表（按 knowledge_scope 选用）

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

表内未覆盖的知识域：writer 按 kebab-case 约定自行构造 `{domain}-{role}`，
并在 frontmatter 声明 role_name 与 examines，不阻塞写作。

## 2. 术语权威源（供 4 维判据「术语精确性」对照）

| 类别 | 权威源 | 入口 |
|---|---|---|
| 兽药 | 《中华人民共和国兽药典》（2020 年版一部/二部/三部） | `https://www.ivdc.org.cn/` |
| 病毒命名 | ICTV（国际病毒分类委员会）现行分类 | `https://ictv.global/` |
| 疫病名录 | 农业农村部现行动物疫病名录 | `http://www.mara.gov.cn/` |
| 法定传染病 | 《中华人民共和国动物防疫法》（2021 修订） | `https://flk.npc.gov.cn/` |
| 诊断标准 | GB/T 16550 等现行国标 | `https://openstd.samr.gov.cn/bzgk/gb/` |
| 国际动物卫生 | WOAH（WAHIS / 陆生动物卫生法典） | `https://www.woah.org/` |

## 3. 引用核验源清单（供 citation-verify 方法 4 / 4b）

- 中国法规/公告：`flk.npc.gov.cn`（法律）、`gov.cn/zhengce`（法规）、`mara.gov.cn`（农业农村部公告）
- 中国标准：`openstd.samr.gov.cn/bzgk/gb/`（注意现行版次）
- 兽药典：`ivdc.org.cn`
- 国际：WOAH、OIE 名录、PubMed / Crossref（DOI）
- **时效性陷阱**：动物防疫法（2021 修订）、GB/T 16550 等均有多版历史，引用旧版 = 数据可能整体失效

## 4. 版式 preference（可选，供 manuscript-delivery §3.3）

- 参考文献：GB/T 7714-2015
- 图表：疫病流程图/病理示意图为主，配色需可灰度打印区分
