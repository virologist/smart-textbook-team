---
name: scientific-figure
description: "Scientific figure production for university textbooks: retrieve or derive data for each figure, abstract the data into a regularity, and produce one .ipynb per figure containing the raw data, the R/ggplot2 or Python/matplotlib plotting code, and PDF+PNG outputs with Chinese labels. Covers figure type selection by teaching purpose, data abstraction principle, notebook contract (data cell / code cell / output cell), font setup for CJK in matplotlib, and manual-refinement friendliness. Trigger words: 科研绘图 / 数据图 / 图表 / notebook / ipynb / ggplot / matplotlib / PDF 图 / 教材配图."
version: 1.0.0
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
| **cell 1（markdown）** | 图说明 | 教学目的 / 数据来源 / 抽象方法 / 已知局限 |
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

## 变更记录
- v1.0.0 [2026-10-30] 初版（批次 C5）：数据图四步流程 + 一图一 notebook 契约 +
  中文标注配方 + 复核清单 + 门禁 4.10/4.12 挂载点
