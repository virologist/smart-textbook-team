---
name: scientific-figure
description: "Scientific figure production for university textbooks: retrieve or derive data for each figure, abstract the data into a regularity, and produce one .ipynb per figure containing the raw data, the R/ggplot2 or Python/matplotlib plotting code, and PDF+PNG outputs with Chinese labels. Covers figure type selection by teaching purpose, data abstraction principle, notebook contract (data cell / code cell / output cell), font setup for CJK in matplotlib, and manual-refinement friendliness. Trigger words: 科研绘图 / 数据图 / 图表 / notebook / ipynb / ggplot / matplotlib / PDF 图 / 教材配图."
version: 1.1.0
---

# scientific-figure — 教材级科研图表生产规范

> **本 skill 是「数据型图表」的产出规范**；概念图/流程图仍走 Mermaid 轨道
> （见 `skills/manuscript-delivery/SKILL.md` §2 双轨图表）。
> 二者的分界：**图中数值来自检索/推导的真实数据 → 走本 skill；图示关系来自概念 → 走 Mermaid**。

## 1. 数据图生产四步（不可跳步）

```
① 数据就位 → ② 数据抽象 → ③ 绘图代码入 notebook → ④ 导出 PDF/PNG
```

### ① 数据就位（来源优先级）

| 优先 | 来源 | 说明 |
|---|---|---|
| 1 | 正文 `[实]` 数据 | 教材正文已核验的数据（最佳：图与文同源） |
| 2 | 检索摘要 | `知识库/retrieval/*.md` 中已核验条目 |
| 3 | 权威机构原始数据 | WOAH / 国家统计局 / 行业年鉴（须注明出处与访问日期） |
| 4 | **推导/模拟数据** | 仅当无实测数据时，**必须标注「示意数据（基于 XX 假设推导）」**并说明抽象方法 |

> **禁止**：为图好看而编造数据；禁止把示意数据画成实测数据的样式（不加区分标注）。

### ② 数据抽象（体现概括性或特殊性规律）

图不是数据的复制，而是**规律的表达**。每个数据图必须能回答：
**「这张图让读者看出什么规律？」**

| 规律类型 | 图形选择 | 教学目的表述 |
|---|---|---|
| **概括性规律**（一般趋势/普遍关系） | 折线图 / 散点 + 趋势线 / 箱线图 | 「展示 X 随 Y 的普遍变化趋势」 |
| **特殊性规律**（该病/该场景的独特性） | 对比柱状 / 雷达图 / 热图 | 「突出 X 区别于其他 Y 的特征」 |
| **构成关系** | 堆叠柱 / 饼（慎用） | 「呈现 X 的组成结构」 |
| **时序节律** | 折线（季节性）/ 极坐标 | 「展示 X 的周期性节律」 |
| **分布差异** | 小提琴 / 直方 | 「比较两组分布差异」 |

> **抽象必须落进图注**：`图 1-3 某病发病率随鸡龄变化趋势（示意数据，基于传播模型推导）`。
> 抽象说明缺失 = 图退化为装饰性插图（`visual-instructional-designer` 的教学目的守门会拦）。

### ③ 一图一 notebook（契约）

**每个数据图对应且仅对应一个 `.ipynb`**，落盘 `章节/{ch##}/figures/assets/{图号}.ipynb`：

| cell | 内容 | 要求 |
|---|---|---|
| **cell 1（markdown）** | 图说明 | 教学目的 / 数据来源 / 抽象方法 / 已知局限；数据与图式须符合外部判据 skill 时，锚 `[实]（std-skill:{skill名}:{条目}）`（§挂载规范 references/skill-mounting.md；仅作判据不作内容源——B7 铁律） |
| **cell 2（code）** | **原始数据** | 独立成块，**不依赖外部文件**（数据内联，便于复现）；注明来源与获取日期 |
| **cell 3（code）** | **绘图代码** | R（ggplot2）或 Python（matplotlib）；**中文标注**；样式可手动精修 |
| **cell 4（code）** | 输出 | 导出 `{图号}.pdf`（印刷矢量）+ `{图号}.png`（预览）——**裸文件名，不带目录前缀**（见下方路径约定） |

> **导出路径约定（P2-4 修正，2026-11-01；执行级校验暴露的真实缺陷）**
> 旧契约写 `savefig('figures/assets/{图号}.pdf')`，但 notebook 的执行 cwd 是**它自己所在目录**
> （`章节/{ch##}/figures/assets/`）——两者叠加会去找
> `…/figures/assets/figures/assets/{图号}.pdf`，目录不存在 → 执行必失败。
> 若改 cwd 到 WORK_ROOT 又会让产物落到 `WORK_ROOT/figures/assets/`（错位）。
> **现行约定**：cell 4 用**裸文件名** `savefig('{图号}.pdf')` / `savefig('{图号}.png', dpi=DPI)`，
> 执行时 cwd = notebook 所在目录（= Jupyter 打开 notebook 的默认行为）。
> 这样 notebook 可整体搬移、可被 `check_manuscript.py --exec-notebooks` 原样执行，
> 产物天然落在 `章节/{ch##}/figures/assets/`，与 `build_manuscript.py` 的查找路径一致。

**代码便于手动精修**（硬要求）：
- **禁止**把绘图逻辑塞进一个巨型 cell；按「数据处理 / 样式 / 导出」分步；
- 关键参数（尺寸、配色、字号、线宽）**提取为顶部常量块**，便于手改；
- 注释用中文说明「改这里会怎样」；
- 不使用隐藏状态（不依赖前一次运行残留的变量）。

**中文标注**（R/Python 各自写法）：
- R：系统字体随 OS；需显式指定中文字体（如 `family = "Songti SC"` / `"Heiti"`），否则图内中文变方框。
- Python/matplotlib：`plt.rcParams['font.sans-serif'] = ['Songti SC','SimHei','Noto Sans CJK SC']`
  + `plt.rcParams['axes.unicode_minus'] = False`（负号丢失）。

### ④ 输出

- **PDF**（矢量，印刷必需）—— 尺寸按教材版式（A4 宽度内，图宽约 12–15cm）；
- **PNG**（预览，≥300 dpi）；
- 两者落 `章节/{ch##}/figures/assets/`。

## 2. 与交付链的接缝

- `build_manuscript.py`：栅格化后处理会扫描 `assets/`；`.ipynb` 与 `.pdf` 作为
  **附件资产**随交付目录分发（docx 内嵌 PNG，PDF 供出版社排版）。
- 门禁 **4.10**：数据图必须附 `.ipynb` 且可执行（`jupyter nbconvert --execute` 通过）；
  概念图不要求。
- 门禁 **4.12**（溯源与图注完整性，manuscript-delivery §4.1）：图注必须含「教学目的 + 数据来源」，否则 FAIL（防装饰性图）。

## 3. 严禁

- ❌ 编造数据（任何未标注来源的数值）
- ❌ 示意数据画成实测样式（必须显著标注）
- ❌ 图内中文变方框（字体未配）而不自查
- ❌ 一图多 notebook 或一 notebook 多图（契约是一一对应）
- ❌ 数据依赖外部文件（cell 2 必须自包含）
- ❌ 手工精修困难（巨型 cell / 硬编码坐标 / 隐藏状态）

## 4. 复核清单（designer 自查 + examiner 抽查）

- [ ] 每个数据图有且仅有一个 `.ipynb`
- [ ] cell 2 数据自包含 + 注明来源与日期
- [ ] 抽象方法写进图注（概括性 or 特殊性规律）
- [ ] 中文标注正常（无方框）
- [ ] PDF 已导出（矢量）+ PNG 预览
- [ ] notebook 可 `nbconvert --execute` 通过
- [ ] 关键参数在顶部常量块（便于精修）

## 5. 人在回路（撞上限/撞严禁时的停机契约）

> §3 与 §4 是**静态清单**——只说「哪几项不许错」，没说「撞上哪条时具体做什么、交回谁、
> 用户能定什么」。本节把两者逐条绑定成动作契约：**撞上哪条 → 回退到第几步 → 降级成什么
> → 附什么 → 交回谁**。
> **designer 不自行放行任何一条**；处置权在主理人。车道口径 SSOT =
> `references/decision-lanes.md`——本节只列图级停机动作，不复述车道定义；
> **红道动作永远人工**，模型的置信度不是放行依据。

### 5.1 §3 严禁 → 停机动作

| §3 条目 | 判定 | 停机动作（回退到第几步） | 降级形式 | 交回谁 |
|---|---|---|---|---|
| 编造数据（任何未标注来源的数值） | 该数值回指不到任一来源 | 停绘图，**回退到 §1①**：该数值整条作废，按来源优先级 1→2→3 重取 | **不降级**——无来源数值一律不画，不得以任何形式留用 | 主理人（数据疑点上报主理人） |
| 示意数据画成实测样式（必须显著标注） | 图注缺「示意数据（基于 XX 假设推导）」，或样式与实测图不可区分 | **回退到 §1②**：补抽象方法说明 + 补显著标注后重画 | 降级为**示意图**交付：走 §1① 来源优先级第 4 级「推导/模拟数据」，图注须显著标注「示意数据（基于 XX 假设推导）」并说明抽象方法 | 主理人 |
| 图内中文变方框（字体未配）而不自查 | 导出的 PDF/PNG 中中文为方框 | 停下不交图，**回退到 §1③**：修 cell 3 字体配置（Python 走 `plt.rcParams['font.sans-serif']` + `axes.unicode_minus`；R 走 `family` 指定中文字体）后重新导出 | **不降级**——文字不可辨的图不得进教材 | designer 自查 → examiner 抽查 |
| 一图多 notebook 或一 notebook 多图（契约是一一对应） | `章节/{ch##}/figures/assets/` 下 `{图号}.ipynb` 与图位编号不是一一对应 | 停在 §1③：**按图位拆并 notebook**，每个数据图有且仅有一个 `.ipynb` | **不降级**——门禁 4.10 按图位查 notebook，数目对不上即判 FAIL | designer 自查 → examiner 抽查 |
| 数据依赖外部文件（cell 2 必须自包含） | cell 2 出现外部文件读取，原始数据未内联 | **回退到 §1③**：把外部数据内联进 cell 2（独立成块，注明来源与获取日期），删外部读取语句 | **不降级**——门禁 4.10 结构校验查的就是「数据未内联」，外部数据文件不进交付目录 | designer 自查 → examiner 抽查 |
| 手工精修困难（巨型 cell / 硬编码坐标 / 隐藏状态） | cell 3 把绘图逻辑塞成巨型块，或关键参数散落在代码里 | **回退到 §1③**：按「数据处理 / 样式 / 导出」分步，关键参数提取为顶部常量块，删隐藏状态 | **不降级**——本项是硬要求，不接受「能跑就行」的图 | designer 自查 |

### 5.2 §4 复核清单 → 判定与失败处置

| §4 检查项 | 判定 | 失败处置 |
|---|---|---|
| 每个数据图有且仅有一个 `.ipynb` | `assets/` 下 `.ipynb` 数 == 数据图位数 | 失败 → 回 §5.1「一图多 notebook」行处置；门禁 4.10 判 FAIL，不得先交图后修 |
| cell 2 数据自包含 + 注明来源与日期 | cell 2 含字面原始数据，且写明来源与获取日期 | 失败 → 回 §1③ 内联数据、补来源与日期，重跑 §4 本项 |
| 抽象方法写进图注（概括性 or 特殊性规律） | 图注能回答「这张图让读者看出什么规律」 | 失败 → 回 §1②：先定规律类型与图形选择再写图注；缺此项的图退化为装饰性插图，不得交付 |
| 中文标注正常（无方框） | 导出件目视无方框 | 失败 → 回 §5.1「图内中文变方框」行处置 |
| PDF 已导出（矢量）+ PNG 预览 | 两个文件都在 `章节/{ch##}/figures/assets/` | 失败 → 回 §1④ 重新导出（cell 4 用裸文件名 `savefig('{图号}.pdf')`） |
| notebook 可 `nbconvert --execute` 通过 | 门禁 4.10e 真执行 exit 0 | 失败 → 回 §1③ 修 cell 3/4（savefig 路径 / 依赖 / 语法）后重跑 `check_manuscript.py --exec-notebooks`；环境无 nbconvert 时 4.10e 走逐 cell 直执行降级档，两档都不可用才判 N/A（不判 FAIL），降级结论须原样转述到交付说明，不得当通过 |
| 关键参数在顶部常量块（便于精修） | 尺寸 / 配色 / 字号 / 线宽在顶部常量块 | 失败 → 回 §1③ 提取常量块；不降级 |

### 5.3 停机时必须附的交付物（停机包）

停机不是「报错退出」，是一份**可裁决的停机包**。缺件即视为未上报，重来。

| 附件 | 内容 | 出处 |
|---|---|---|
| 图注草案 | 该图完整图注（教学目的 + 数据来源 + 抽象方法 + 已知局限）；降级为示意图时须含「示意数据（基于 XX 假设推导）」 | §1② / §1③ cell 1 |
| notebook 复现命令 | 复现命令原文（`jupyter nbconvert --to notebook --execute --stdout 章节/{ch##}/figures/assets/{图号}.ipynb`）+ 执行环境说明（有无 nbconvert / matplotlib / R） | §1③ / §4 |
| 失败项原文 | 命中的 §3 条目或 §4 检查项**原文** + 门禁判据原文与其 detail 末行（4.10 / 4.10e / 4.12）；**不转述、不摘要** | §3 / §4 / §2 |
| 降级说明 | 降级到哪一级（§1① 第 4 级推导数据，或不降级）+ 依据哪条用户裁决 | 本节 |

停机包随 designer 的 SendMessage 回传清单交主理人（`smart-textbook-team-team-lead`），
并记入 `章节/{ch##}/review/interventions.md`——不记则 learn 侧无法归因。

### 5.4 交回谁 + 用户可做的决定

**交回谁**：

- **designer**（`visual-instructional-designer`）自查命中 → 执行 §5.1 / §5.2 的停机动作，
  **不自行放行、不自行补数据**；产停机包交主理人。
- **examiner**（`quality-examiner`）R4c 图文一致性抽查命中 → 退回 designer 重做，
  **不代改图**（审查者不代改，与「只核验不改稿」同一纪律）。
- **主理人**（`smart-textbook-team-team-lead`）→ 涉用户决定的三个选项由主理人问用户，
  结论回传给 designer；designer 不直接问用户。

**用户可做的决定**（主理人问，designer 执行）：

1. **接受示意图并按示意数据交付** —— 走 §1① 来源优先级第 4 级，图注显著标注
   「示意数据（基于 XX 假设推导）」+ 抽象方法；样式须与实测图可区分。
2. **补真实数据后重做** —— 补到来源优先级 1 / 2 / 3 级，designer 从 §1① 重走并重跑 §4。
3. **取消该图** —— 该图位撤出（不产出 `.ipynb` 与 PDF/PNG），由主理人转 writer 调整正文图表位。

> **未获用户裁决前**：该图不出现在交付目录，**不得以「先交付后补」推进**；
> 交付前的图件放行属红道动作，永远人工。

## 变更记录
- v1.0.0 [2026-10-30] 初版（批次 C5）：数据图四步流程 + 一图一 notebook 契约 +
  中文标注配方 + 复核清单 + 门禁 4.10/4.12 挂载点
- v1.1.0 [2026-11-10] 新增「§5 人在回路」小节：把 §3 严禁与 §4 复核清单逐条绑定到「停机动作 / 交付物 / 交回谁 / 用户可做的决定」；version 1.0.0 → v1.1.0
