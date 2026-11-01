---
name: manuscript-delivery
description: "University textbook MANUSCRIPT delivery spec (not slides): Markdown as the single source of truth carrying revision semantics, DOCX as the deliverable + review vehicle rendered with real Word tracked changes (w:ins/w:del). Defines md structure contract (heading hierarchy, frontmatter, figure/exercise/ideology markers, cross-reference syntax, review-revision marks §1.5, proofread-conclusion §4.2), built-in DOCX typesetting with override, dual-track figures, review-copy build (--revisions) and Word-backflow (--apply-revisions). Load in ASSEMBLE/DELIVER/PROOFREAD phases, or whenever deliverable format, docx typesetting, revision marks, or figure handling is in question. Trigger words: 书稿 / docx / 交付格式 / 版式 / 题注 / 目录 / 参考文献格式 / 图表栅格化 / 修订 / 追踪修订 / 审阅版 / manuscript."
version: 1.3.0
---

# manuscript-delivery — 大学教材书稿交付规格（md 源 + docx 交付）

> **本 skill 是交付物形态的唯一权威源（SSOT）**。
> 建立背景（2026-10-29 实测）：`team-lead.md` Phase ASSEMBLE 曾写「按 CHANGELOG 工具链 `scripts/build_chapter.py` 模板，可选生成 docx」——
> 但 `scripts/` 实测无该文件、CHANGELOG 全文 0 命中 `docx|pandoc|build_chapter`、git 全历史无此文件、全包无版式规范、无 docx 门禁。
> 即：**docx 交付链被声明过但从未存在，且引用了虚构出处**。本 skill 与其配套脚本兑现该承诺。

## 0. 交付形态铁律

| 格式 | 定位 | 路径 | 修订态政策（v1.1.0 放宽） |
|---|---|---|---|
| **Markdown** | **源格式 · 唯一真相**（可编辑、可复用、可 diff、可版本化） | `交付/{教材名}_{ch##}.md` | ✅ 唯一编辑入口；**修订语义在此承载**（§1.5） |
| **DOCX** | **交付格式 + 审稿工作载体**（Word 追踪修订模式审改） | `交付/{教材名}_{ch##}.docx` | ✅ **允许且推荐在 Word 追踪修订模式下修改/批注**（方案甲，2026-10-31 管家确认） |
| **审阅版 DOCX** | 含真修订态的审稿交付 | `交付/{教材名}_{ch##}_审阅.docx` | ✅ 由审稿修订标记渲染生成（§5.1） |

**禁止（v1.1.0 收窄为一条）**：
1. ❌ **改 docx 不回流**——在 Word 里接受/拒绝修订或做任何修改后，必须回流 md（`build_manuscript.py --apply-revisions`，§5.2）再重建；否则 md 与 docx 分叉，md 不再是真相（门禁 4.13 拦截）

> **v1.1.0 铁律修订（2026-10-31，管家拍板方案甲）**：原文案「docx 不得手工直接修改（见 §0 政策表）」
> 与「审稿/校稿须在 Word 追踪修订模式下修改或标注」直接冲突——修订无载体。
> 现改为：**修订允许发生在 docx（Word 追踪修订态），但 md 必须同步承载修订语义**；
> 分叉 = 交付物内部矛盾，按门禁 4 处置。docx 由 md 完全重建的能力不变。

**为什么 md 仍是源**：教材是长周期资产（修订版、多章节复用、跨学期维护）。docx 是二进制，diff 与合并基本不可用；md 可 git 管理，且修订标记（§1.5）让审稿意见同样可 diff、可核验——**md 承载修订语义，docx 只是修订语义的 Word 渲染态**。

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
教材名: 《示例教材》
章节号: ch01
章节标题: 示例主题概述
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

### 1.5 审稿修订标记（v1.1.0 新增 · 方案甲核心）

> **物理载体**：修订语义存于 md 源（可 diff、可 git、可机械核验）；
> 构建时由 pandoc 渲染为 Word 原生修订（`<w:ins>`/`<w:del>`），审稿人在 Word 里所见即所得。
> 实测依据：pandoc ≥2.x 支持，本仓实测 pandoc 3.13 + 后处理不破坏修订标记（2026-10-31）。

| 语义 | md 写法 | 渲染到 Word |
|---|---|---|
| 插入新文本 | `[新表述]{.insertion author="严正词" date="2026-10-31"}` | 红色下划线插入修订 |
| 删除旧文本 | `[旧表述]{.deletion author="严正词" date="2026-10-31"}` | 红色删除线删除修订 |
| 替换（删+插成对） | `[旧]{.deletion author="A" date="D"}[新]{.insertion author="A" date="D"}` | 一处完整替换修订 |
| 审稿批注（不改文） | `<!-- 批注(严正词): 建议补数据来源 -->`（HTML 注释） | md 保留；docx 审阅版剔除或转尾注 |

**规则**：
1. `author` 必须是成员 ID 或真实审稿人姓名（溯源用）；`date` 为 ISO `YYYY-MM-DD`
2. 修订标记**只出现在正文段落**，禁入 frontmatter / 图表位 / 代码块（pandoc 不解析块内 span）
3. **交付态成对约束**：一处替换必须 deletion+insertion 成对、同 author 同 date——孤立标记由判据 4.13 拦截
4. 正式发布版（用户接受全部修订后）用 `--apply-revisions` 生成净稿，标记清零（4.13a 校验）

**校稿结论写入文档（§4.2 契约的落点）**：PROOFREAD 轮的校稿结论以 `## 校稿结论` 节写入
交付 md（构建时同步进 docx）——含「结论：可交付/需返修」、按轮次汇总的修订计数
（插入 N 处/删除 N 处/批注 N 条）、遗留待办与责任人。**结论缺失 = 门禁 4.13c FAIL**。

---

## 2. 双轨图表（本 skill 的核心机制）

> **问题根源**：`visual-instructional-designer` 的产出是 **Mermaid / SVG / Markdown 表格代码块**（`figures/{图号}.md`），不是图片资产。
> 直接把 md 转 docx → 图表区变成一堆代码文本。docx 交付链必须在 ASSEMBLE 补一个**栅格化环节**。

### 轨道 A：md 保留可渲染代码块（可编辑 · 可复用）

交付 md 中的图表位保留完整规格卡 + 源码：

````markdown
[图 1-3：示例结构模式图]
图 1-3 示例结构模式图
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

> **判据数说明（2026-10-31）**：本表列**判据族**（4.1–4.11）;
> 脚本实跑会产生更细的子判据 ID（如 4.2a/4.2b/4.5a…，实测 19+ 个）——
> **以 `check_manuscript.py` 实跑输出为准**，本表与脚本由 CI 第 7 道（书稿链冒烟）联动守护；
> 新增判据须同步本表（漏同步会被验收审计抓）。

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
| 4.10 | **数据图 notebook**（`assets/{图号}.ipynb` 存在且符合 4-cell 契约：md 图说明 + 原始数据 + 绘图 + 导出；`--exec-notebooks` 时再跑 4.10e） | 补建或回 designer |
| 4.10e | **notebook 真执行**（`--exec-notebooks` 开启时成立；优先 `nbconvert --execute`，环境不可用降级逐-cell 直执行并在 detail 标注「降级」；超时/报错均 FAIL） | 回 designer 修 notebook 或补依赖 |
| 4.11 | **术语一致性**（对照 profile §5.1 术语表，三级查找：禁用写法零出现 / 同概念多写法未并存 / 首见位置正确） | 回 writer |
| 4.12 | **溯源表**（`交付/{教材名}_{ch##}.溯源.md` 存在；覆盖正文全部唯一标识符；标识符在参考文献中存在；由 `--assemble` 自动生成） | 回 examiner 补 R3 日志后重建 |
| 4.12c | **引用标签闭环**（P2-6：每个 `[引]` 必须紧跟可检索来源标识符，且该来源在本章«参考文献»节中存在；裸 `[引]` = FAIL） | 回 writer 补来源，或改标 `[待核实·reason=...]` |
| 4.12d | **逐处锚定**（ADR-03：正文每个 `[实]` 后同一句窗口内必须有可检索锚——PMID/DOI/ISBN/中文权威源名，或本地源三形态 `[[笔记]]` / `本地:路径#锚` / `ima:{kb}:{doc}`；`本地:` 必须带 `#锚`（小节或 `#L行号`），裸 `[实]` 无锚 = FAIL） | 回 writer 补锚，或改标 `[待核实·reason=...]` |
| 4.13 | **修订态完整性**（4.13a 修订标记**逐处配对/显式声明**且 author/date 合法——孤立 insertion 必须带 `[整段新增]` 或位于「## …新增」小节；4.13b md 标记与 docx 修订数一致；4.13c 校稿结论节存在且含结论） | 回 examiner/重建 |
| 4.14 | **R5 硬门槛**（ADR-05：`运行态/r5-score.json` 存在时——total≥80 ∧ total==Σ(维度×权重)/100 ∧ 权重和==100 ∧ 每维 ≥1 证据位置；由 `scripts/score_quality.py` 产出，4.14 独立重算反伪造。文件不存在 → N/A 不阻塞） | 回 examiner 跑 score_quality.py 补评 |

> **v1.1.0 实现补齐说明（2026-10-31）**：4.10–4.12 此前只有本表声称、
> `check_manuscript.py` **零实现**（实测 grep `4.10|4.11|4.12|ipynb|溯源|术语` 在
> scripts/ 与 tests/ 全部 0 命中——属「规范声称超出实际能力」缺陷复发）。
> 本版三条判据与 4.13 已在脚本真实落地，由负向实验守护（破坏对应物必 FAIL）。
>
> **P1/P2 补充（2026-11-01，真实章节全链实战）**：4.11c 与 4.12c 属**后来补实现**——
> 4.11c 此前只在 `terminology-table.md §3`（现 profile §5.1 术语表）声明、脚本零实现；4.12c 为新增，
> 封死 `[引]` 绕过核验的后门（`[引]` 与 `[实]` 走完全不同的核验通道：
> `[实]` 进溯源表被 4.12/4.12b 管，`[引]` 此前无人管）。同类缺陷的通用教训：
> **判据表里每一条 ID 都必须在 `check_manuscript.py` 有对应 `r.add("4.xx"` 调用**，
> `test_smart_textbook_team.py` F37 对此做静态守护。

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

**门禁 4.12（本 skill 契约；P1-1 口径修订 2026-11-01）**：交付前检查——① 溯源表存在；
② **唯一标识符覆盖**：正文出现的每个唯一 PMID/DOI 都在溯源表中有行（原「`[实]` 处数 == 行数」
口径已废弃——同一 PMID 多节引用是教材常态，处数 >> 行数恒 FAIL 且补日志无法修复）；
③ 溯源行的标识符在参考文献中存在。任一不满足 → FAIL。

**门禁 4.12d（ADR-03 · 逐处锚定，2026-11-01 批次 B2）**：修「空集恒真」——
旧口径只做集合差，正文 `[实]` 不写标识符 → 正文标识符集合为空 → 恒 PASS，
且 detail 写「全部溯源」主动伪造合规结论。新口径把「有声明必有锚」变成硬判据：
**正文每一处 `[实]` 后同一句窗口内（约 120 字符，切到句末标点）必须出现可检索锚**，
锚分两类——学术/中文权威（PMID / DOI / ISBN / 中文权威源名如《…法》《…典》）与
本地源三形态（`[[笔记]]` / `本地:相对路径#锚` / `ima:{kb}:{doc}`）。
其中 `本地:` **必须带 `#锚`**（小节标题或 `#L行号`），只给路径不给锚仍判不可检索（FAIL）。

> 生成方式（v1.1.0 起自动）：examiner R3 核验按**标识符**逐条记录（位置 + 标识符 + 结果）到
> `章节/{ch##}/review/r3_verification_log.md`（同一标识符多处出现记一行，位置列可并列）→
> ASSEMBLE 阶段 `build_manuscript.py --assemble` **自动转写**为 `交付/{教材名}_{ch##}.溯源.md`。
> 日志缺失 → 构建器 WARN + 判据 4.12 FAIL。

### 4.2 校稿结论（v1.1.0 新增 · 修复 PROOFREAD 断链）

> **断链实测（2026-10-31）**：pipeline 13 态表声明 PROOFREAD 产出「校对后稿」，
> 但 quality-examiner 契约为「只写 review/ 下文件；禁止改 draft」——
> 全包无任何成员产出「校对后稿」，校稿结论更无落点。

**PROOFREAD 态产出改为三个文件**（归属 quality-examiner，登记进 path-ownership）：

| 产出 | 路径 | 内容 |
|---|---|---|
| 校对后稿 | `章节/{ch##}/review/proofread.md` | 在 draft 基础上仅做风格/术语修订的稿子，修改处**全部带修订标记**（§1.5）——生成者≠审查者的分离靠「修改可见」维持 |
| 修订记录 | `章节/{ch##}/review/proofread_revisions.md` | 逐条修订清单：位置/类型(插删)/理由(对应 R4 判据)/作者 |
| 校稿结论 | 写入交付 md 的 `## 校稿结论` 节（由 ASSEMBLE 从上行两件转写） | 结论(可交付/需返修) + 修订计数 + 遗留待办 + 责任人 |

**门禁 4.13（修订态完整性，判据见下表）**：md 修订标记与 docx 修订态一致 + 校稿结论已写入。

---

## 5. 与既有流程的接缝

| 阶段 | 变化 |
|---|---|
| `PROOFREAD` | 产出三件套：校对后稿（带修订标记）+ 修订记录 + 校稿结论（§4.2；v1.1.0 修复无人产出断链） |
| `CONSOLIDATION` | 六项统稿 checklist 不变，新增第 7 项：交叉引用可解析性 |
| `ASSEMBLE` | 装配 md（含校稿结论节）→ 自动生成溯源表 → **构建 docx（默认带修订态）** |
| `DELIVER` | `present_files` 交付 **md + docx（+审阅版，如有修订）+ 溯源表** + 质量报告（含未栅格化图表数、修订计数、`[待核实]` 数） |

### 5.1 审阅版（v1.1.0 新增）

```bash
# 构建审阅版：md 中的修订标记 → Word 真修订态（w:ins/w:del，含 author/date）
python3 scripts/build_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 --revisions
# 产物：交付/{教材名}_{ch##}_审阅.docx —— 出版社/作者在 Word 里逐条接受或拒绝
```

- 审阅版**不含校稿结论节**（结论属内部 QA，正文修订才是审阅对象）
- md 与交付 docx 始终含修订标记（真相态）；净稿只在用户明确要求时生成

### 5.2 Word 审改回流（v1.1.0 新增 · 防 md/docx 分叉）

```bash
# 审稿人在 Word 里接受/拒绝/继续标注修订后，回流 md：
python3 scripts/build_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 \
    --apply-revisions --from-docx 交付/{教材名}_{ch##}_审阅.docx
# 行为：pandoc --track-changes=accept|reject 按 --revision-mode 读 docx → 覆写交付 md
#       → 删除/接受后的 docx 由 md 重建 → 三格式重新对齐
```

- 回流后交付 docx **必须重建**（禁止保留旧 docx）——判据 4.13b 校验 md 标记数 == docx 修订数
- 回流是编排者（team-lead）职责，登记进 path-ownership（docx 审改属审稿场景例外，回流动作仍归编排）

> **注意**：`pipeline skill` 目录树中的 `交付/{教材名}_{ch##}.md` 现为**源格式**；docx 为同名的派生交付物，两者成套交付。

### 5.3 全书装配（ADR-01 B5 新增 · 多章成书）

单章交付链之上，多章成书由 `book-orchestration` skill 编排、`build_book.py` 装配。
本 skill 的单章产物（`交付/{教材名}_{ch##}.md`）是全书装配的**输入**：

```bash
# 章交付 md + book-spec.md → 合稿 md + docx（全书门禁 5.1–5.5 由 check_book.py 把守）
python3 scripts/build_book.py --work-root "$WORK_ROOT"
# 产物：交付/{教材名}_合稿.md + 交付/{教材名}.docx
```

全书装配语义（与单章构建的差异）：

| 维度 | 单章（build_manuscript） | 全书（build_book） |
|---|---|---|
| 图号 | 章内序 `图 1-1` | 重排为全书序 `图 1`、`图 2`…（图位/题注/交叉引用同一映射） |
| 参考文献 | 章内 `[1..n]` | 跨章去重合并 + 全书重编号，统一放末尾 |
| 目录/页码 | `--toc`，单章页码 | TOC 域（`\o "1-3"`）+ 单节连续页码（不分节重启） |
| 校验 | 门禁 4（check_manuscript） | 5.1–5.5（check_book），5.3 逐章复用门禁 4 |

## 变更记录

- v1.3.0 [2026-11-01] ADR-05 硬门槛落盘（批次 B4）：判据表补 **4.14 R5 硬门槛**
  （r5-score.json：total≥80 ∧ total==Σ(维度×权重)/100 ∧ 权重和==100 ∧ 每维 ≥1 证据位置；
  不存在 → N/A 不阻塞）；附带归位 frontmatter version 漂移（B5 加 v1.2.0 变更记录时
  漏同步版本号，1.1.0→1.3.0 一次补齐）。
- v1.2.0 [2026-11-01] 全书层（ADR-01 批次 B5）：新增 §5.3 全书装配（build_book.py 合稿
  语义：图号全书序 / 参考文献合并重编号 / TOC 域 + 连续页码）；单章行为零改动。
- v1.1.0 [2026-10-31] 修订态交付链（方案甲，管家拍板）：铁律收窄为「改 docx 不回流才禁止」；
  新增 §1.5 审稿修订标记（md 承载修订语义 → pandoc 渲染 Word 真修订）；§4.2 校稿三件套
  修复 PROOFREAD 无人产出断链；判据 4.10/4.11/4.12/4.13 在脚本真实落地（此前三条零实现）；
  溯源表改为 --assemble 自动生成；§5.1 审阅版 + §5.2 Word 审改回流。
- v1.0.0 [2026-10-30] 初版：兑现被虚构引用的 docx 交付链；确立 md 源 + docx 交付双格式铁律、双轨图表（含栅格化三级降级）、内置版式默认 + 三级覆写、门禁 4 七项判据。
