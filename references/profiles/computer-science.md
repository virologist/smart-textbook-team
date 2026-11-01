---
name: profile-computer-science
discipline: computer-science
displayName: 计算机 / 软件工程
version: 1.0.0
---

# 学科 profile：计算机 / 软件工程（computer-science）

> 加载协议见 `references/role-assembly.md` §6。用于验证「非兽医学科也能跑通」的解耦证据。

## 1. 领域 role_id 映射表（按 knowledge_scope 选用）

| 知识域 | role_id | role_name |
|--------|---------|-----------|
| 算法与数据结构 | `algorithms-specialist` | 算法领域专家 |
| 软件工程 | `software-engineering-educator` | 软件工程教育专家 |
| 计算机系统/体系结构 | `computer-architecture-specialist` | 体系结构专家 |
| 操作系统 | `os-specialist` | 操作系统专家 |
| 计算机网络 | `networking-specialist` | 网络领域专家 |
| 数据库 | `database-specialist` | 数据库专家 |
| 人工智能/机器学习 | `ml-ai-specialist` | 机器学习专家 |
| 信息安全 | `security-specialist` | 信息安全专家 |
| 编译原理 | `compiler-specialist` | 编译原理专家 |
| 人机交互 | `hci-specialist` | 人机交互专家 |

## 2. 术语权威源（供 4 维判据「术语精确性」对照）

| 类别 | 权威源 | 入口 |
|---|---|---|
| 计算机术语 | 《计算机科学技术名词》（全国科学技术名词审定委员会，第三版） | `https://www.cnctst.cn/` |
| 标准/规范 | IEEE Standards Association | `https://standards.ieee.org/` |
| 算法与复杂度 | ACM Computing Classification System (CCS) | `https://dl.acm.org/ccs` |
| 中文国标（信息技术类） | GB/T 系列现行标准 | `https://openstd.samr.gov.cn/bzgk/gb/` |
| 开源事实标准 | 官方 RFC / 语言规范原文 | `https://www.rfc-editor.org/` |

## 3. 引用核验源清单（供 citation-verify 方法 4 / 4b）

- 学术文献：DOI / Crossref、`dblp`（计算机领域书目库 `https://dblp.org/`）、arXiv
- 标准：IEEE / ISO / GB/T（注意现行版次与是否被取代）
- 官方规范：RFC 编号、语言官方规范原文（如 ECMAScript、Java Language Specification）
- **时效性陷阱**：语言标准与框架版本迭代极快（如 Python 2→3、RFC 被 obsoleted），
  引用必须写明**版本号**，且核「是否已废弃/被取代」

## 4. 版式 preference（可选，供 manuscript-delivery §3.3）

- 参考文献：GB/T 7714-2015；代码清单建议用等宽字体、带行号
- 图表：流程图/时序图/UML 为主（Mermaid 支持良好）

## 5. 判据执行体（术语表 + 章节结构）

> 本段是门禁 4.11 与 R1 结构审查的**学科化数据源**（三级查找第 2 级）。解析约定见
> `terminology-table.example.md` §1/§2。本 profile 的术语表**禁用列与别名列留空**——
> 计算机教材缩写（AI/ML/OS 等）是无歧义的标准缩写，无需禁用或别名约束；
> 与兽医域相反（兽医域 AI/ND/IBD 歧义大，必须禁用）。术语表在此只守
> 「标准写法唯一（4.11d）+ 首见位置（4.11c）」两维。

### 5.1 术语表（§2 表格式，机器可解析）

| 标准写法 | 允许别名 | 禁用写法 | 首次出现 | 来源 |
|---|---|---|---|---|
| 人工智能 | — | — | ch01 | 《计算机科学技术名词》第三版 |
| 机器学习 | — | — | ch01 | 《计算机科学技术名词》第三版 |
| 计算机网络 | — | — | ch01 | 《计算机科学技术名词》第三版 |

### 5.2 章节结构（八要素 · 计算机版）

| # | 要素 | 必备性 |
|---|---|---|
| 1 | 学习目标（知识+能力+素质三维） | 必备 |
| 2 | 导入案例（真实工程情境） | 必备 |
| 3 | 理论知识（挂节级文件） | 必备 |
| 4 | 技术方案（算法/架构/实现要点，含复杂度与权衡） | 必备 |
| 5 | 实践操作（实验/编码：目的/环境/步骤/验收标准） | 必备 |
| 6 | 案例分析（经典★/综合★★/进阶★★★） | 必备 |
| 7 | 思考与练习（梯度题，含编程题） | 必备 |
| 8 | 拓展阅读（前沿/开源动态/职业发展） | 必备 |

## 6. 审查基准（R2 四维的学科化判据）

| 维度 | 学科化判据 |
|---|---|
| 因果链完整性 | 问题→算法/方案→正确性/复杂度论证→实现→验证，逻辑闭环 |
| 鉴别点充分性 | 每对易混概念/算法 ≥3 条辨析点（时间/空间/适用场景/边界条件） |

## 7. 数值触发词（门禁 3.1 + 跨章数据矛盾共源）

- number_triggers: 时间复杂度、空间复杂度、准确率、召回率、吞吐量、延迟、内存占用、响应时间、并发数、覆盖率
- conflict_metrics: 准确率、召回率、吞吐量、延迟、覆盖率
