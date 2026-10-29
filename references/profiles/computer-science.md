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
