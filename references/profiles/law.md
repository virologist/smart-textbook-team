---
name: profile-law
discipline: law
displayName: 法学
version: 1.0.0
---

# 学科 profile：法学（law）

> 加载协议见 `references/role-assembly.md` §6。用于验证「非兽医学科也能跑通」的解耦证据。

## 1. 领域 role_id 映射表（按 knowledge_scope 选用）

| 知识域 | role_id | role_name |
|--------|---------|-----------|
| 民法 | `civil-law-specialist` | 民法专家 |
| 刑法 | `criminal-law-specialist` | 刑法专家 |
| 行政法 | `administrative-law-specialist` | 行政法专家 |
| 宪法 | `constitutional-law-specialist` | 宪法专家 |
| 诉讼法 | `procedure-law-specialist` | 诉讼法专家 |
| 国际法 | `international-law-specialist` | 国际法专家 |
| 商法/经济法 | `commercial-law-specialist` | 商法经济法专家 |
| 知识产权 | `ip-law-specialist` | 知识产权专家 |
| 法理学 | `jurisprudence-specialist` | 法理学专家 |
| 法律实务 | `legal-practice-specialist` | 法律实务专家 |

## 2. 术语权威源（供 4 维判据「术语精确性」对照）

| 类别 | 权威源 | 入口 |
|---|---|---|
| 法律术语 | 《法学名词》/ 全国科学技术名词审定委员会 | `https://www.cnctst.cn/` |
| 现行法律文本 | 国家法律法规数据库 | `https://flk.npc.gov.cn/` |
| 司法解释 | 最高人民法院 / 最高人民检察院官网 | `https://www.court.gov.cn/` |
| 裁判文书 | 中国裁判文书网 | `https://wenshu.court.gov.cn/` |
| 行政法规 | 中国政府网政策库 | `https://www.gov.cn/zhengce/` |

## 3. 引用核验源清单（供 citation-verify 方法 4 / 4b）

- 法律/法规：`flk.npc.gov.cn`（**必须核现行有效版本与条文序号**）
- 司法解释：两高官网，注意是否被新解释取代
- 行政法规/规章：`gov.cn/zhengce`，需核对发文字号与印发日期
- 学术文献：DOI / Crossref、CNKI（无 PMID 时核验标准引文格式）
- **时效性陷阱（高危）**：法条修订与司法解释更新频繁（如民法典施行后
  九部单行法同时废止）。引用必须写明**法律名 + 版本/施行日期 + 条文序号**，
  引用已废止条文 = 硬错误

## 4. 版式 preference（可选，供 manuscript-delivery §3.3）

- 参考文献：GB/T 7714-2015；法条引用建议用「《法律名》第 N 条」格式
- 图表：法律关系图/流程图为主
