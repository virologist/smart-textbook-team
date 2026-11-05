---
name: profile-veterinary
discipline: veterinary
displayName: 兽医 / 畜牧（默认 profile）
version: 1.1.0
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

## 5. 判据执行体（术语表 + 章节结构）

> 本段是门禁 4.11（术语一致性）与 R1 结构审查的**学科化数据源**（三级查找第 2 级）。
> 第 1 级是 `{WORK_ROOT}/学科标准/术语表.md`（每本书自己的，优先）；第 3 级是包内
> `terminology-table.example.md`（仅示例，命中时 WARN）。解析约定见 example 文件 §1/§2。

### 5.1 术语表（§2 表格式，机器可解析）

| 标准写法 | 允许别名 | 禁用写法 | 首次出现 | 来源 |
|---|---|---|---|---|
| 禽流感 | 禽流行性感冒 | AI、AIV、禽流感（AI） | ch01 | ICTV / 《动物防疫法》2021 修订 |
| H9N2 亚型禽流感病毒 | H9N2 亚型 | H9N2 AIV | ch01 | ICTV |
| 低致病性禽流感 | 低致病性禽流感病毒 | LPAIV、低致病性禽流感（LPAI） | ch01 | WOAH 陆生动物卫生法典 |
| 新城疫 | 鸡新城疫 | ND、Newcastle | ch02 | 兽药典 2020 版 |
| 传染性法氏囊病 | 鸡法氏囊病 | IBD | ch03 | WOAH |
| 大肠杆菌病 | 禽大肠杆菌病 | E. coli、Ecoli（作病名单独使用时） | ch01 | 兽药典 2020 版 |

### 5.2 章节结构（八要素 · 兽医/医学版 · 自 chapter-structure.md 逐字搬迁）

> ADR-02 下沉：本表原为 `references/chapter-structure.md §1` 的「默认口径八要素」，
> 现按学科化原则整体搬入本 profile。搬迁须与旧位置逐字一致（GATE2 风险管控：
> 兽医路径行为不得退化）。

| # | 要素 | 必备性 | 最小内容要求 | 常见误用（判 FAIL） |
|---|---|---|---|---|
| 1 | 学习目标 | 必备 | 知识 + 能力 + 素质三维标注，各 ≥1 条；可映射 Bloom 层级 | 只写「掌握本章知识」这类空话 |
| 2 | 导入案例 | 必备 | 一个真实情境案例（可标 `[待核实]`），引出本章问题 | 与学习目标无关的装饰性故事 |
| 3 | 理论知识 | 必备 | 本章知识主线，必须挂节级文件 | 只有结论无机制解释 |
| 4 | 防治措施 | 必备 | 四位一体：预防 / 治疗 / 控制 / 综合防控（各 ≥1 条） | 只写「加强饲养管理」 |
| 5 | 实践操作 | 必备 | SOP 形态：操作目的 / 器材 / 步骤 / 安全 / 评价标准（**安全项不可缺**） | 缺安全提示 |
| 6 | 案例分析 | 必备 | ≥1 个案例（典型 ★ / 复杂 ★★ / 警示 ★★★ 难度分级） | 与导入案例重复 |
| 7 | 思考与练习 | 必备 | 梯度题（认知层级递进），含 `[习题 {章}-{序}]` 标记（书稿层唯一合法形式；设计层按节分配用 `[习题位 {节号}：…]`，落位时映射为全章流水号） | 全部同层级题 |
| 8 | 拓展阅读 | 必备 | 前沿技术 / 行业动态 / 职业发展 之一以上，带来源 | 空占位 |

> 学段裁剪：高职专科可裁要素 8 与要素 4 部分细分，要素 1/2/5/7 不可裁；职业本科八要素全备。
> 鉴别诊断类章节附加要求（个论不重复 / 三切入口 / Mermaid 推理链）原在 chapter-structure.md §4，
> 现并入本 profile §5.2（ADR-02 下沉，兽医专属）。

## 6. 审查基准（R2 四维的学科化判据）

| 维度 | 学科化判据 |
|---|---|
| 因果链完整性 | 病因→病理→症状→诊断→防治逻辑闭环，无断环 |
| 鉴别点充分性 | 每对易混疾病 ≥3 条鉴别点（0 条 blocking，1–2 条 advisory） |

## 7. 数值触发词（门禁 3.1 + 跨章数据矛盾共源）

- number_triggers: 发病率、病死率、死亡率、剂量、浓度、免疫程序、日龄、效价、阳性率、感染率、保护率
- conflict_metrics: 发病率、病死率、死亡率、阳性率、检出率、感染率
