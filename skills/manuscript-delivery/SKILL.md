---
name: manuscript-delivery
description: "University textbook MANUSCRIPT delivery spec (not slides): Markdown as the single source of truth, DOCX as the deliverable format. Defines md structure contract (heading hierarchy, frontmatter metadata, figure/exercise/ideology markers, cross-reference syntax), built-in DOCX typesetting defaults with override mechanism, and the dual-track figure strategy (md keeps renderable code; docx embeds rasterized PNG). Load in ASSEMBLE/DELIVER phases, or whenever the deliverable format, docx typesetting, or figure handling is in question. Trigger words: 书稿 / docx / 交付格式 / 版式 / 题注 / 目录 / 参考文献格式 / 图表栅格化 / manuscript."
version: 1.0.0
---

# manuscript-delivery — 大学教材书稿交付规格（md 源 + docx 交付）

> **本 skill 是交付物形态的唯一权威源（SSOT）**。
> 建立背景（2026-10-29 实测）：`team-lead.md` Phase ASSEMBLE 曾写「按 CHANGELOG 工具链 `scripts/build_chapter.py` 模板，可选生成 docx」——
> 但 `scripts/` 实测无该文件、CHANGELOG 全文 0 命中 `docx|pandoc|build_chapter`、git 全历史无此文件、全包无版式规范、无 docx 门禁。
> 即：**docx 交付链被声明过但从未存在，且引用了虚构出处**。本 skill 与其配套脚本兑现该承诺。

## 0. 交付形态铁律

| 格式 | 定位 | 路径 | 可否手改 |
|---|---|---|---|
| **Markdown** | **源格式 · 唯一真相**（可编辑、可复用、可 diff、可版本化） | `交付/{教材名}_{ch##}.md` | ✅ 唯一编辑入口 |
| **DOCX** | **交付格式**（供出版社/教务处/排版流转） | `交付/{教材名}_{ch##}.docx` | ❌ **禁止手改**（改则与源分叉） |

**禁止**：
1. ❌ 先出 docx 再改 docx——任何修改必须回到 md 重新构建
2. ❌ 把 docx 当作源——它是一次性产物，可由 md 完全重建
3. ❌ 交付 md 与 docx 内容不一致的版本（门禁 4 会拦截）

**为什么 md 是源**：教材是长周期资产（修订版、多章节复用、跨学期维护）。docx 是二进制，diff 与合并基本不可用；md 可 git 管理，且 Mermaid/表格源码可编辑复用——这正是「双轨图表」要保的东西。

---

## 1. md 结构契约

### 1.1 标题层级（禁止跳级）

| 层级 | 写法 | 编号 | 说明 |
|---|---|---|---|
| 章 | `# 第1章 XXX` | 每文件仅 1 个 | 与 `{ch##}` 一致 |
| 节 | `## 1.1 XXX` | 章内连续 | 不可从 `#` 直接跳到 `###` |
| 小节 | `### 1.1.1 XXX` | 节内连续 | — |

**跳级判定**：出现 `#` 后直接 `###`（中间无 `##`）→ 校验 FAIL。

### 1.2 frontmatter（书稿元数据，必填 7 项）

```yaml
---
教材名: 《禽病学》
章节号: ch01
章节标题: 禽流感病毒生物学特性
字数目标: 12000
实际净字数: 11840        # 由 scripts/count_net_words.py 生成，禁止手填
版本: R3
学科profile: veterinary  # 默认 veterinary；可由 profile 覆写（见 §3.3）
---
```

`实际净字数` **必须由脚本产生**：`python3 scripts/count_net_words.py --target <目标> <文件>`——自报值一律不作数（沿用既有 SSOT 纪律）。

### 1.3 标记语法（全章统一）

| 语义 | 语法 | 校验要求 |
|---|---|---|
| 图表位 | `[图 {章}-{序}：{标题}]` | 序号连续无跳号 + 有题注 | 4.2a/b-图 |
| 图题注 | 图位下一行 `图 {章}-{序} {标题}` | 与图位一一对应 | 4.2a-图 |
| 表题注 | 表格上一行 `表 {章}-{序} {标题}` | 同上 | 4.2a/b-表 |
| 习题位 | `[习题 {章}-{序}]` | 编号连续（无习题位时 WARN） | 4.8 |
| 思政融入 | `[思政·{主题}]` | **仅校验存在性**；占比 2–3% 属写作约定，由 didactic-architect 在设计阶段把关，**无自动判据** | 4.9（存在性） |
| 数据标签 | `[实]`/`[估]`/`[引]`/`[待核实]` | 沿用既有规则（属门禁 3.1，非门禁 4） | 3.1 |
| **交叉引用** | `[见 §1.2]` / `[见图 1-3]` | **目标必须真实存在**（可解析） | 4.3a/b |

> **判据编号说明（2026-10-30 补）**：初版只写「校验要求」文字、未标注由哪条判据执行，
> 其中「思政占比 2–3%」实际**没有任何自动判据**。现逐行标注编号，无判据的项明确写出，
> 避免规范声称的校验与实际能力不符。

> **空行强制（实测得出，2026-10-30）**：图位 / 题注 / 规格卡三者之间**必须空行分隔**。
> 实测反例：三行连写无空行 → pandoc 按 Markdown 规则合并为同一段落，
> 导致「题注居中」「图在题注上方」等版式全部失效（题注居中实测 0 命中）。

> **交叉引用是书稿特有的新校验点**：单章内 `[见 §X]` 指向的节号、`[见图 X-Y]` 指向的图号若不存在 → 读者按图索骥扑空。教科书里这属于硬伤。

### 1.4 参考文献

章末固定 `## 参考文献`，**GB/T 7714-2015** 格式（可覆写，见 §3.3）：

```
[1] 作者. 题名[J]. 刊名, 年, 卷(期): 起止页.
[2] 作者. 书名[M]. 版次. 出版地: 出版社, 年.
```

编号按**正文首次引用顺序**（顺序编码制），不按字母序。

---

## 2. 双轨图表（本 skill 的核心机制）

> **问题根源**：`visual-instructional-designer` 的产出是 **Mermaid / SVG / Markdown 表格代码块**（`figures/{图号}.md`），不是图片资产。
> 直接把 md 转 docx → 图表区变成一堆代码文本。docx 交付链必须在 ASSEMBLE 补一个**栅格化环节**。

### 轨道 A：md 保留可渲染代码块（可编辑 · 可复用）

交付 md 中的图表位保留完整规格卡 + 源码：

````markdown
[图 1-3：禽流感病毒结构模式图]
图 1-3 禽流感病毒结构模式图
> 规格卡：教学目的=…｜数据来源=正文 §1.2 [实]｜类型=示意图

```mermaid
graph LR
  HA[血凝素] --> V[病毒粒子]
```
````

**价值**：修订版改图、跨章节复用、换出版社重排时，源码可直接改后重栅格。

### 轨道 B：docx 嵌入栅格化图（可交付 · 可印刷）

| 源类型 | 栅格化路径 | 产物 |
|---|---|---|
| Mermaid | `mmdc -i {图号}.mmd -o {图号}.png` | PNG（默认宽度 1024px，300dpi 可选） |
| SVG | `mmdc` 或 pandoc 内联 SVG→PNG | PNG |
| Markdown 表格 | **不栅格化** | 转 docx **原生表格**（可编辑、可选中） |

**资产落盘**：`章节/{ch##}/figures/assets/{章}-{序}.mmd`（源码）+ `.png`（栅格）。
（与 `references/path-ownership.md` 中 `figures/assets/` 归属一致：唯一归属 visual-instructional-designer。）

### 2.0 栅格化环境准备（运维前提）

```bash
# macOS
brew install pandoc            # 必需
pip install python-docx        # 必需
# Debian/Ubuntu / CI
sudo apt-get install -y pandoc && python3 -m pip install python-docx
# 可选（仅双轨图表的栅格化轨道需要）
npm i -g @mermaid-js/mermaid-cli
npx puppeteer browsers install chrome   # mmdc 依赖 Chrome，版本须与 mmdc 期望一致
```

> **依赖缺失行为**：`build_manuscript.py` 对 pandoc / python-docx **exit 3 硬失败，不降级**——
> 宁可明确报错也不产出「缺 docx 的半成品交付物」。mmdc 缺失则可降级（见 §2.1）。

> **实测坑（2026-10-30，本机 macOS）**：`mmdc` 已安装、`npx puppeteer browsers install chrome`
> 也已执行，但 mmdc 仍报 `Could not find Chrome (ver. 148.0.7778.97)`——缓存里装的是 131/156，
> 与 mmdc 期望的 148 不匹配；设 `PUPPETEER_EXECUTABLE_PATH` 指向已有 Chrome 在受限沙箱内仍启动失败。
> **结论**：栅格化属**可失败环节**，这正是 §2.1 三级降级存在的理由。
> 排障命令：`mmdc -i t.mmd -o t.png -b white`（能出 PNG 即环境 OK）。
> 环境不可用时不必阻塞写作——按 §2.1 降级交付，并在质量报告显式声明未栅格化图表数。

### 2.1 栅格化降级（防单点故障，维度 12）

`mmdc` 不可用（未安装 / CI / 他人机器）时，**禁止静默丢图**，按序降级：

1. 尝试 `mmdc` → 成功则嵌 PNG
2. 失败 → 尝试 `npx @mermaid-js/mermaid-cli`
3. 全部失败 → **保留代码块 + 醒目占位框**：
   `［图 1-3：栅格化工具不可用，矢量源码见交付 md 源文件］`
   并在**质量报告**中列出「未栅格化图表 N 个」——**用户可见，不静默**

判定标准：交付时 `未栅格化图表数 == 0` 才算完整交付；>0 必须显式告知用户并说明原因。

---

## 3. docx 版式规范（内置默认 + 可覆写）

### 3.1 内置默认（教材版式）

| 元素 | 规格 |
|---|---|
| 页面 | A4；页边距 上下 2.54cm / 左右 3.17cm |
| 正文 | 宋体 小四（12pt）；行距 1.5 倍；首行缩进 2 字符；段后 6pt |
| H1（章） | 黑体 三号（16pt）加粗；段前 24pt 段后 18pt；居中 |
| H2（节） | 黑体 四号（14pt）加粗；段前 18pt 段后 12pt |
| H3（小节） | 黑体 小四（12pt）加粗；段前 12pt 段后 6pt |
| 图题注 | 图**下**方；宋体 五号（10.5pt）；居中；`图 {章}-{序} {标题}` |
| 表题注 | 表**上**方；宋体 五号；居中；`表 {章}-{序} {标题}` |
| 页眉 | 章标题；页脚 | 页码（居中） |
| 目录 | 自动生成，≥3 级，置于正文前 |
| 参考文献 | 章末 `参考文献` 节，GB/T 7714-2015，悬挂缩进 |

### 3.2 构建管线

```
md（源）
  ├─ 图表位扫描 → Mermaid/SVG 源码落盘 assets/
  ├─ 栅格化（mmdc，带降级）→ PNG
  ├─ pandoc: md → docx（--reference-doc=内置默认模板）
  └─ python-docx 后处理：题注自动编号 / 页眉页脚 / 目录 / 参考文献悬挂缩进
```

### 3.3 覆写机制（跨专业 · 跨出版社）

优先级从高到低，命中即止：

1. **显式指定**：`build_manuscript.py --reference-doc <file>`（用户提供 .docx 模板）
2. **学科 profile**：`交付/版式配置.yaml` 或 profile 目录内的 `typesetting.yaml`
3. **内置默认**（§3.1）

> 与学科解耦（批次 3）的接缝：本 skill **不含任何学科常量**，版式与学科规范均由外部 profile 提供；默认层只提供「通用教材版式」。

---

## 4. 构建与校验命令（SSOT）

```bash
# 构建（md → docx；md 由 ASSEMBLE 产出）
python3 scripts/build_manuscript.py \
  --work-root "$WORK_ROOT" --chapter ch01 \
  --format md,docx [--reference-doc <模板.docx>]

# 校验（进 DELIVER 前必过；--strict 时任一 FAIL 即 exit 1）
python3 scripts/check_manuscript.py \
  --work-root "$WORK_ROOT" --chapter ch01 --strict
```

**校验项（门禁 4）**：

| # | 判据 | FAIL 处置 |
|---|------|----------|
| 4.1 | md 标题层级无跳级 | 回 ASSEMBLE 修结构 |
| 4.2 | 图/表题注编号连续且与图位一一对应 | 回 designer/writer |
| 4.3 | 交叉引用目标全部可解析 | 回 writer 修正或删除 |
| 4.4 | 参考文献编号连续、格式合规（GB/T 7714） | 回 writer |
| 4.5 | docx 可被 python-docx 打开、标题层级完整 | 重建 |
| 4.6 | **md 与 docx 图数一致**（docx 图数 == md 图位数 − 显式降级数） | 重建或补栅格化 |
| 4.7 | 净字数 ±5%（`count_net_words.py` 脚本值） | 回 writer 或经用户同意放宽 |
| 4.8 | 习题位编号连续 | 回 writer |
| 4.9 | 思政融入点已标注（存在性） | 回 writer |
| 4.11 | **术语一致性**（对照 `references/terminology-table.md`：禁用写法零出现 / 同概念多写法未并存 / 首见位置正确） | 回 writer |

## 4.1 溯源表（交付物必含，批次 C3）

> **为什么必须有**（实测缺口）：此前交付物只有正文 + 参考文献，**无法回答
> 「正文中这句话的证据在哪」**。citation-verify 核的是「引用本身真不真」，
> 但没有把「正文陈述 ↔ 证据 ↔ 引用编号 ↔ 文本位置」串成链——
> 审稿人或出版社追问某条数据来源时，只能靠人工逐句翻。

**交付物必须附溯源表**，落盘于 `交付/{教材名}_{ch##}.溯源.md`（或书稿末尾附录）：

| 序 | 正文位置（节号/行号） | 陈述要点 | 数据/结论 | 证据类型 | 标识符/来源 | 核验状态 |
|---|---|---|---|---|---|---|
| 1 | §1.2 第 3 段 | 某病发病率 | 12.5% | 期刊 | PMID:12345678 | ✅ 已核验 |
| 2 | §1.3 第 1 段 | 某药休药期 | 7 天 | 兽药典 | 兽药典 2020 版 | ✅ 已核验 |
| 3 | §2.1 第 2 段 | 某疗法有效率 | — | 待核实 | — | ⚠ [待核实] |

**规则**：
- 凡正文出现 `[实]` 标签的陈述，**必须有对应溯源行**；
- 标识符须与「参考文献」章节的条目**编号一致**（可机械核对）；
- 核验状态取 `已核验` / `待核实`，**不得出现空白**；
- `待核实` 条目数须在质量报告中显式列出（与门禁 4.6b「未栅格化图表数」同纪律）。

**门禁 4.12（本 skill 契约）**：交付前检查——① 溯源表存在；② `[实]` 条数 == 溯源行数；
③ 溯源行的标识符编号在参考文献中存在。三者任一不满足 → FAIL。

> 生成方式：examiner R3 核验时已逐条记录「位置 + 标识符 + 结果」到
> `章节/{ch##}/review/r3_verification_log.md` → ASSEMBLE 阶段据此转写为溯源表
> （**不改内容，只做格式转换**，避免二次引入不一致）。

---

## 5. 与既有流程的接缝

| 阶段 | 变化 |
|---|---|
| `CONSOLIDATION` | 六项统稿 checklist 不变，新增第 7 项：交叉引用可解析性 |
| `ASSEMBLE` | 装配 md（既有）→ **构建 docx（本 skill）** |
| `DELIVER` | `present_files` 交付 **md + docx 双格式** + 质量报告（含未栅格化图表数） |

> **注意**：`pipeline skill` 目录树中的 `交付/{教材名}_{ch##}.md` 现为**源格式**；docx 为同名的派生交付物，两者成套交付。

## 变更记录

- v1.0.0 [2026-10-30] 初版：兑现被虚构引用的 docx 交付链；确立 md 源 + docx 交付双格式铁律、双轨图表（含栅格化三级降级）、内置版式默认 + 三级覆写、门禁 4 七项判据。
