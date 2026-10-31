# Changelog

All notable changes to **smart-textbook-team** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-10-31

### 修订态交付链（方案甲：md 承载修订语义 → docx 渲染 Word 真修订；管家拍板 + 铁律收窄）

> **诊断背景（2026-10-31 从零核查实测）**：① 全包 grep `追踪修订|track changes|w:ins|w:del|批注`
> = **0 命中**——「审稿校稿须在 Word 追踪修订模式下修改或标注」无任何载体；规范层「docx 禁止手改」
> 与该要求直接冲突。② 判据 4.10/4.11/4.12 只有 manuscript-delivery §4 声称、`check_manuscript.py`
> **零实现**（grep `4.10|4.11|4.12|ipynb|溯源|术语` 在 scripts/ 与 tests/ 全 0 命中）。
> ③ PROOFREAD 态产出「校对后稿」无人产出（examiner 副作用禁改 draft + 无成员认领）——校稿结论无落点。
> ④ 溯源表「ASSEMBLE 转写」从未发生（`assemble_md()` 不读 r3_verification_log）。

### Added
- **审稿修订标记（manuscript-delivery §1.5）**：md 源承载修订语义
  （`[旧]{.deletion author="X" date="D"}[新]{.insertion author="X" date="D"}`），
  pandoc 渲染为 Word 原生 `<w:ins>`/`<w:del>`（实测 3.13 + `postprocess_docx` 后处理不破坏修订标记）
- **`build_manuscript.py --revisions`**：构建审阅版 `交付/{教材名}_{ch##}_审阅.docx`
  （含 Word 真修订态，剔除校稿结论节——内部 QA 不进审阅对象）
- **`build_manuscript.py --apply-revisions --from-docx <审改过的docx> --revision-mode accept|reject|all`**：
  Word 审改回流 md（防 md/docx 分叉）；回流自动清洗 TOC 伪标题与转义方括号、重算净字数、补写校稿结论节。
  三模式语义实测：accept=净稿（标记 0）/ reject=恢复原文 / all=保留标记（2 处往返无损）
- **溯源表自动生成**：`--assemble` 从 `review/r3_verification_log.md` 转写
  `交付/{教材名}_{ch##}.溯源.md`（兑现 §4.1 从未发生的承诺；日志缺失 → WARN + 4.12 FAIL）
- **校稿结论落盘**：PROOFREAD 三件套（`review/proofread.md` 校对后稿·修订标记版 +
  `review/proofread_revisions.md` 修订记录+结论行）→ ASSEMBLE 自动转写进交付 md
  「## 校稿结论」节（判据 4.13c）；结论/修订计数/遗留待办随 docx 交付
- **门禁 4 四条新判据（`check_manuscript.py` 真实现）**：
  **4.10** 数据图 ipynb（存在 + cell 结构合规 + 数据内联抽查；此前零实现）；
  **4.11** 术语一致性（对照 terminology-table 4 条，N/A 豁免防空表死锁；此前零实现）；
  **4.12** 溯源表（`[实]` 处数 == 溯源行数；此前零实现）；
  **4.13** 修订态完整性（4.13a 标记成对+author/date 合法 / 4.13b md 标记数==docx 修订数——
  「改而不回流」机械拦截 / 4.13c 校稿结论存在）
- **静态契约 F36a-f（6 条）**：判据实装守护、双支柱（--revisions/--apply-revisions）、
  铁律收窄文案、PROOFREAD 三件套三方一致（examiner 义务/pipeline 产出/路径登记）、
  结论行格式同源、显式 --assemble 重装语义。**245 → 252 计分项**
- **CI 第 7 道扩展**：修订往返回归（审阅版含 w:ins/w:del 断言 + 回流 accept 标记清零 +
  回流后重建 docx 再 strict 全过）

### Changed
- **铁律收窄（管家拍板）**：「docx 禁止手改」→「**改 docx 不回流才禁止**」——docx 允许且推荐
  在 Word 追踪修订模式下审改；违规对象从「在 docx 上改」换成「改完不回流」（4.13b 拦截）
- **PROOFREAD 断链修复**：13 态表产出列落主「校稿三件套」；examiner 增第 6 条核心能力
  （校对后稿以修订标记呈现——「生成者≠审查者」靠修改可见维持，禁改 draft 本体的边界不变）；
  path-ownership 登记两条 review/ 路径 + 交付/ 动作扩写
- **显式 `--assemble` 重装语义**：交付 md 已存在时从 `章节/` 重装覆盖（旧语义只在缺失时装配
  → PROOFREAD 三件套完成后旧交付稿永不更新——实测断链）；溯源表+校稿结论转写移出
  assemble-only 分支，两条路径都补
- 版本四处同步 2.2.2 → 2.3.0；README 主理人体积声明 16.0KB → 18.4KB（M10a/M10c 实际拦截后修正）

### Verified
- 四套门禁全绿：静态契约 252/252（1.000）+ router 40/40 + vendor 6/6 + manifest 31/31
- CI 模拟（第 7 道全流程含修订往返）：构建 exit 0 / 审阅版含 w:ins+w:del / strict 全过 /
  回流后标记清零且「修订表述」在文 / 回流后重建再 strict 全过
- 负向实验：孤立修订标记 → 4.13a FAIL；删校稿结论节 → 4.13c FAIL；删溯源表 → 4.12 FAIL；
  数据图位缺 ipynb → 4.10 FAIL（补合规 notebook 后转 PASS）；md/docx 修订数不一致 → 4.13b FAIL

## [2.2.2] - 2026-10-30

### 批次 1：机制补强（独立从零诊断后，按用户拍板 Q1-Q5 执行；低风险项先行）
- **A5 阻塞解除通路修复（P7）**：`scripts/progress.py` CLI `choices` 漏收 `BLOCKED_RESOLVED`
  → 阻塞登记后**无法标记为已解除**（`:104` 分支是死代码）。修复后 5 用例正负样本验证通过
  （init 新章 / update BLOCKED_RESOLVED / 换章 exit 2 / 同章幂等 / 非法状态仍拒）
- **A6 多章串档修复（P17）**：`progress.py init` 遇章节不符原只 WARN 后 return（调用方误判成功，
  `show` 仍返回旧章）→ 改为 `exit 2` 硬失败并报出现有章节
- **C15 role-assembly 可达性修复（横向归因 ①）**：`references/role-assembly.md` ← 原位于包根，
  成员需从 scripts 路径 `dirname` 两次反推包根（未声明推导链）。移入 `references/` 后由装配器
  `resolve_shared_refs()` 自动注入——**零代码改动，不碰联邦 shared-core**（实测装配产物资源清单
  已含该绝对路径）。同步更新 subject-writer / quality-examiner / CONTRIBUTING 三处引用；
  role-assembly 升 v1.1.0
- **C4 路径归属表补建（横向归因 ②，P10）**：`references/path-ownership.md` 新建（15 条路径 +
  4 条仲裁规则）。此前 harness §0「并行安全：路径表唯一归属」与「资源冲突」两条仲裁**指向空气**
- **C5 门禁 3 判据（P9）**：pipeline skill 补 PRODUCE 后内容门禁四项（数据标签完整率 /
  净字数脚本值 ±5% / 角色团声明完整 / 图表位编号连续）+ fail 一律回 PRODUCE 返修
- **C6 LEARN 信号枚举对齐（P16）**：harness §2 用 `token_overrun`、§7 用 `metric_breach`，
  均不在 learn-protocol 枚举内 → 枚举扩至 7 值并标为 SSOT
- **C7 预算优先级（P12）**：harness §3.1 新增五档（P0 RETRIEVE → P4 PROOFREAD）+ 硬规则
  「禁止为保 P1/P3 削减 P0」+ 削减须记黑板 `budget.cuts` 并在质量报告声明
- **C12 工具健康检查（P19）**：harness §3.2 新增静默失败 5 条判定（空返回/零结果/条数腰斩/
  主题无关/授权包装成成功）+ 记 `outcome=SILENT_FAILURE`（对标 arXiv 2603.01548）
- **C8 冗余度与可执行性（P13）**：harness §8 新增上下文三档裁剪 + 响应可执行性 4 判据
  （产物路径 / 结论可判定 / 下一步动作 / 异常已声明）；§7 检查表 +2 项
- **C13 boundary filter 落地（P18 实证升级）**：实测 5 个成员 MD 中 `boundary filter` **命中 0**
  （只在 team-lead dispatch 检查表出现）→ 义务完全依赖派单复述，而 evo-16 已实证「不复述必漏」。
  给 5 个成员 MD「注意事项」段补**成员自身义务行** + 门禁断言 F24a
- **B5 英文/国际标准核验链（citation-verify v1.4.0）**：方法 4 的 7 行权威源**全为中文且全兽医域**
  → 新增方法 4b（DOI/Crossref/ISBN/ISO/IEEE/WHO/FAO/EU/预印本 8 类，**学科中立**），
  三要素与中文源同构；预印本必须标明身份不得冒充已发表
- **C15b 可达性门禁（总纲级，P22）**：新增 F24a–F29b 共 14 条断言，特点是不验「字符串存在」、
  验**可达性与可执行性**（路径是否位于可注入区 / 引用是否指向真实文件 / CLI 是否受理该状态）。
  静态契约计分项 199 → **213**，4 道门禁全绿

## [2.2.2] - 2026-10-30（续）

### 批次 2：书稿交付链（docx + md｜按用户拍板 Q1 重做的能力补齐）
> **背景与勘误（实测）**：`team-lead.md:105` 曾写「按 CHANGELOG 工具链 `scripts/build_chapter.py`
> 模板，可选生成 docx」。实测 `scripts/` 无该文件、CHANGELOG/README/AGENTS/CONTRIBUTING 全文
> `grep docx|pandoc|build_chapter` **0 命中**、git 全历史无此文件 → **引用了不存在的文件且伪造了出处**。
> 批次 2 用真实实现兑现该承诺，并在 team-lead / pipeline 两处留下勘误说明（不抹除原文痕迹）。

- **A1′ 新增 `skills/manuscript-delivery/SKILL.md`（第 7 个 skill）**：书稿交付规格 SSOT——
  ① **md 为源、docx 为交付**双格式铁律（docx 禁止手改，改则回 md 重建）；
  ② md 结构契约（标题层级禁跳级 / frontmatter 7 项 / 图位·题注·习题位·思政标记 / **交叉引用可解析** / GB/T 7714 参考文献）；
  ③ 内置教材版式默认 + 三级覆写（--reference-doc > 学科 profile > 内置）；
  ④ **双轨图表**：md 保留可渲染源码（可编辑复用），docx 嵌栅格化 PNG；
  ⑤ 门禁 4 七项判据
- **A2′ 新增 `scripts/build_manuscript.py`**（兑现虚构的 build_chapter.py）：
  pandoc 转 docx + python-docx 后处理（中文字体 eastAsia / 字号 / 行距 / 首行缩进 /
  题注居中 / 页眉章标题 / 页脚 PAGE 域 / 页边距）+ Mermaid 源码落盘 + 三级降级栅格化。
  **实测**：端到端构建成功（12.2KB docx 回读验证 H1/H2 层级、宋体12pt/黑体16pt/14pt eastAsia、
  题注 CENTER、页眉章标题、页脚 PAGE 域、页边距 2.54/3.17cm 全部正确）
- **A3′ 新增 `scripts/check_manuscript.py`（门禁 4）**：7 项判据（标题跳级 / 题注连续与配对 /
  交叉引用悬空 / 参考文献编号与年份 / docx 可打开与层级 / md-docx 图数一致 / 净字数 ±5%）。
  **双向验证**：正向 12 PASS exit 0；构造坏稿 → 跳级·断号·悬空节引用·悬空图引用·
  参考文献断裂·字数偏差 **6 项全部正确 FAIL**，exit 1
- **实测修正 1（空行强制）**：图位/题注/规格卡三行连写无空行 → pandoc 按 Markdown 合并为
  同一段落，题注居中**实测 0 命中**。已在 skill 立规「三者必须空行分隔」并纳入校验 4.2
- **实测修正 2（docx 渲染态清理）**：图位占位标记 `[图 X-Y：…]` 在 docx 中会让读者看到
  占位符与题注重复两遍 → 构建时移除（md 源保留，docx 属渲染态）
- **栅格化环境实测**：本机 `mmdc` 因 Chrome 版本不匹配（期望 148，缓存为 131/156）不可用 →
  **三级降级实战生效**：保留源码 + 醒目占位框 + 显式 WARN「未栅格化 N 个」，**未静默丢图**。
  已在 skill §2.0 记录运维前提与排障命令
- **流程接入**：team-lead Phase ASSEMBLE（构建）/ DELIVER（先过门禁 4 再交付，双格式 +
  质量报告须列未栅格化图表数）；pipeline 目录树改为 `交付/{md,docx}` 双档、状态机 ASSEMBLE/DELIVER
  门禁列更新、「与原 v5 差异」段补勘误
- **CI 第 7 道门禁**：书稿交付链冒烟（build_manuscript --assemble → docx 落盘 → check_manuscript --strict）。
  本地复现 exit 0 / FAIL 0（CI 内 mmdc 不可用，正好回归「降级路径不阻断交付」）

### 批次 1 复查后的修正（独立复查代理查出，均已修）
- **install.ps1 完全未同步（高）**：此前**无任何门禁覆盖** PowerShell 安装路径——清单既无
  `references`，又长期缺 `scripts`/`tests`/`vendor`/`.claude-plugin`，还留着已迁走的
  `role-assembly.md` 死条目 → **Windows 安装态连 assemble_spawn_prompt.py 都不存在且无人报警**。
  修复：清单与 install.sh 对齐；新增 M12a/b/c 三条门禁（含两安装器核心目录集合一致性）
- **恒真断言修复（中，3 条）**：复查代理用「父提交回退法」实测——
  ① `F24a` 原为全文子串匹配，义务行被挪进代码块仍 PASS → 改为**位置敏感**（只认注意事项段内、排除代码块内），
     负向实验（挪进代码块）正确 FAIL；
  ② `F26b` 父提交 pipeline:151 已提及 count_net_words.py → 改为**只认门禁 3 小节内**，负向实验正确 FAIL；
  ③ `F29a` 父提交 progress.py:119 已有该字面量 → 改为**解析 argparse choices**（并加 F29b 校验解析本身未失效），
     负向实验正确 FAIL
- **M11 重构**：原 M11c 与 M11a 判据重复（同一条件计数两次）→ 改为 M11c 校验 `scripts/` 运行期可达
- **README 同步**：技能数 6→7、计分项 213→214、CI 门禁 5→6→7 道；新增交付形态说明行
  （M10b 门禁实际拦截一次，证明散文漂移门禁有效）

### 批次 3：学科解耦（唯一重构项，按 Q3=A 保留兽医为默认 profile）
> **问题（实测）**：`role-assembly.md` §6 是一张**写死的 10 行兽医映射表**，§3 术语判据
> 写死《兽药典》+ ICTV；`citation-verify` 方法 4 的权威源表全为兽医域。
> 跨专业（法学/计算机/经济）复用时**这些表整体失效，而规范本身对换专业毫无提示**——
> 「看起来通用、实际单学科」的隐性耦合。

- **B1 `role-assembly.md` v1.1.0 → v2.0.0**：§6 改为 **profile 加载协议**
  （取 `discipline` → 读 `references/profiles/{discipline}.md` → 缺失回落 `veterinary`
  并**在 issues 显式声明，禁止静默换学科**）；§3 术语判据改为引用 profile §2；
  §7 frontmatter 示例改为学科中立 `{domain}-specialist`；命名约定示例同步去兽医化
  → **规范本体零学科常量**（门禁 F30c 校验）
- **B2 新增 3 个学科 profile**（`references/profiles/`）：
  `veterinary.md`（默认，原 10 行表迁入 + 术语源 + 核验源 + 版式）、
  `computer-science.md`、`law.md`。每个统一四节结构（映射表 / 术语权威源 / 核验源清单 / 版式 preference）。
  **实测 3 个文件均被装配器 `resolve_shared_refs()` 递归注入**（rglob 生效，无需改代码）
- **B4 citation-verify 学科源分层**：方法 4 表头声明分层——中国区通用源（任何专业）
  + 🐾 兽医域默认源（2 行标注）；**学科专属源由 profile §3 提供**，换专业以 profile 为准；
  法律行举例改为跨专业并列（兽医：动物防疫法 / 法学：民法典）
- **B7 外部学科规范注入协议**：pipeline 新增「外部学科规范注入协议」——
  三来源（profile §2/§3 > 用户 `{WORK_ROOT}/学科标准/` > profile-overrides），
  门禁 **3.5 专业规范符合性**（未提供可判定条目时自动 N/A，**不得因此阻塞交付**）；
  硬规则「外部规范只作判据不作内容来源」（涉著作权）
- **新增门禁 F30a-e / F31a-d（9 条）**：校验解耦**实质**而非形式——
  加载协议存在、≥3 个 profile（含默认）、**正文无学科专属 role_id**、
  回落规则存在、术语判据不写死、profile 位于可注入区、四节结构完整、
  pipeline 有 3.5、citation-verify 声明 profile 来源。
  **负向实验**：把兽医 role_id 写回正文定义区 → F30c 正确 FAIL

### 批次 2 独立复查后的 14 项修正（并行审计代理查出，逐条已修）
> 复查代理用「负向实验 + 父提交回退法」查出的问题，其中 2 条高严重度是**功能性硬伤**。

**高**
- **C-1 图表源码错位（教材硬伤）**：`write_source_assets` 原用「图位数 vs 代码块数」**下标配对**，
  只要某图位前多一个代码块（示例/表格）→ 后续**全部错位**，把第 2 张图源码挂到 `图 1-1` 名下，
  且**不报错、静默产出错误书稿**。改为**按位置就近匹配**（每个图位取其之后、下一图位之前的
  第一个未占用代码块），两侧失配项分别落盘为 `ch01-orphanNN` 并 WARN。
  **回归用例**：图位间插入额外代码块 → 旧实现必错位，新实现 `1-1=ONE / 1-2=TWO / EXTRA=orphan` ✓
- **C-2 陈旧资产误报**：`4.6a` 原以 `assets/*.png` 计数为基准 → 上一章残留的 `9-9.png`
  会被计入，造成「图数一致」的假通过。改为**只统计 stem 属于本章图位集合的资产**，
  并对残留资产发 WARN 建议清理

**中**
- **C-7（严重）`install.ps1` 取错父目录**：`$REPO_DIR = $PSScriptRoot | Split-Path -Parent`
  指向仓库**父目录** → 所有 `Test-Path` 判假 → **WorkBuddy 安装态实际什么都不装且不报错**。
  改为 `$REPO_DIR = $PSScriptRoot`
- **C-8** `install.ps1` VERSION 仍为 `2.0.0`（与 plugin.json 2.2.2 不符）→ 同步
- **C-6** SVG 源码被送进 mmdc（mmdc 只吃 .mmd）→ 必然 exit 1、无谓触发降级占位。
  改为 SVG 直接交 pandoc 嵌入（Word 支持矢量，优于二次栅格化）；删除未使用的
  `RE_TABLE_FENCE` 死代码
- **C-9** 交付目录多命中时静默取第一个 → 改为**歧义报错 exit 2**（build 与 check 两处）
- **C-3** 新增判据 **4.0**：frontmatter 七项必填（教材名/章节号/章节标题/字数目标/实际净字数/版本/学科profile）
- **C-4** 新增判据 **4.8/4.9**：习题位编号连续、思政融入点存在性；
  并在 skill §1.3 逐行标注判据编号，**明确「思政占比 2–3%」无自动判据**（规范不再声称超出实际能力的校验）
- **C-5** 判据 4.2 由「只查图」扩展为**图+表双向**（表题注与 `[表 X-Y]` 此前完全未覆盖）

**低**
- **C-10** 三个正则补 `re.M`（`^…$` 缺省只匹配整串首尾，曾致 4.1「无任何标题」误报）
- **C-11** README 三处漂移：正文第二处残留 `13.4KB`、计分项 214→227、CI 门禁 6→7 道；
  `M10c` 由 `search` 改 `findall` 并**排除里程碑表格行**（把历史值 22.1KB 误判为漂移）
- **C-12** `install.ps1` heredoc 与 `AGENTS.md` 的技能数文案同步（5/6 → 7）
- **C-13** `skills/SKILL_CHANGELOG.md` 补 manuscript-delivery 条目
- **C-14** CI 第 7 步去掉「失败再跑一次」的兜底（掩盖真实失败原因）
- **附带修复**：`settings.json` 被误删（A5a 门禁捕获，已 `git checkout` 恢复）；
  skill §1.3 表格被 blockquote 截断成两半（格式修复）

**新增守护门禁**：`F32a`（README 声明的静态契约计分项 == 实际，放进测试自身 → 漂移必被抓，
实测声明 226 vs 实际 227 立即 FAIL）。静态契约 **227 项全绿**

### 批次 4：动态成员层（C1+C2+C3+C11 同批落地；Q2=B 运行时真生成）
> **为什么四项必须同批**：C3 门禁改造（解锁人数硬编码）必须与 C1/C2（动态生成）同批——
> 否则门禁先红或能力先上而门禁不认；C11（E3 替补）依赖动态层存在才有「等价成员」可换。

- **C1 新增 `skills/team-generation/SKILL.md`（第 8 个 skill）**：
  **双层成员架构**（静态层 5 人常驻 + 动态层按章节生成）；**「先对齐后生效」硬闸门**
  （构成表 → 用户对齐三问 → confirmed_by_user: true 才可注册——未经确认的提案成员
  在装配器层面就被拒绝，不只靠自觉）；三维评估（覆盖深度/领域匹配度/准确性保障）；
  E3 替补机制（examines 覆盖不缩水 + 换人不洗计数）；动态成员**禁止代行审查职责**（契约三原则不可被动态层绕过）
- **C2 新增 `scripts/generate_team.py`**：读 chapter_design 的 knowledge_scope +
  学科 profile 映射表 → 产团队构成提案（`confirmed_by_user: false`，**只出提案不落盘注册表**）。
  实测修复：不同知识域构造出重名 ID（「病毒学/病毒」「病毒」均落 `domain-specialist`）
  → 加序号去重（`domain-specialist-2`）。正/负样本验证：未命中映射表的域由命名约定构造并 WARN
- **装配器动态通道（联邦件改动，vendor 已同步，VENDOR sha 已更新 02a69d1f→3a502d93）**：
  新增 `--work-root` + `--allow-dynamic-members`（**默认关闭**）；注册表只收录
  `confirmed_by_user: true` 条目；动态成员角色由 `build_dynamic_member_md()` 从注册表条目
  **即时合成**（无静态 agents/*.md 依赖）——这正是「运行时真生成」的实现。
  **闸门三态实测**：false → exit 2 拒绝；true → exit 0 合成角色（含 examines/收尾三件套/资源注入）；
  无 --work-root → exit 2。**首版手搓 YAML 状态机解析器有顺序 bug 导致闸门失效**
  （false 态也放行，实测抓出）→ 重写为「正则判确认标志 + PyYAML 全量解析」两段式
- **C3 门禁 A6e 改造**：`memberAgents == MEMBER_IDS`（锁死 5 人）→ **声明一致性**
  （声明的每个成员都有 agents/*.md；不锁人数）——静态层增员不再误红
- **C11 E3 替补通路**：task-router E3 处置由「换等价成员（无）」改为按序
  ①换等价成员（examines ⊇ 原成员；动态层优先；新提案过闸门；interventions 记账；
  打回计数跨成员累计）②无可换再上报用户
- **流程接入**：team-lead 新增 Phase B0（动态团队生成四步，闸门在第③步）；
  plugin.json ×3 / install.sh ×3 / install.ps1 ×3 / README 全量同步第 8 个 skill
  （上一轮 manuscript-delivery 漏登记的教训，本轮**主动**同步）
- **新增门禁 F33a-g（7 条）**：闸门定义、提案器不落盘注册表（行为级按行判据——
  首版 `re.S` 判据跨全文件误报文档字符串，已修）、装配器默认关闭、
  confirmed_by_user 过滤、角色即时合成、E3 替补、审查分离不可绕过。
  **F32a 自指序修复**：F32（README 计分项守护）必须排在所有断言之后，否则算不准总数——
  F33 移至 F32 前。静态契约 **237 项全绿**

### 批次 5：评测增强 + 信封统一（C9 + C10 + C14）
- **C9 整章产物质量（`compute_metrics.py` 第 6 指标）**：过程指标 [1]-[5] 只答「流程顺不顺」，
  新增 [6] 答「产物好不好」——① 结构完整率（5 类必备段）② 数据标签完整率（数值陈述带
  [实]/[估]/[引]/[待核实]）③ 引用核验通过率（R3 报告汇总）。数据源缺失 → 整体 N/A 不阻塞。
  实测修复：`compute()` 的 `if not traces` 早退分支漏算产物质量（无 trace 的纯产物工作区恒 N/A）；
  `render` 从 `[6]` 段正确输出三维度 PASS/FAIL（实测 0.90 < 0.95 正确 FAIL）
- **C10 新增 `scripts/check_cross_chapter.py`**：单章流程只看本章，多章成书的三类跨章矛盾
  无人看守——① 术语多写法（同缩写标注多个中文名 / 术语表别名）② 数据矛盾（同「对象+指标」
  多章数值不一，只比对带 [实] 标签的断言）③ 内容重复（跨章 ≥60 字相同句）。
  **双向验证**：构造术语不一致+数据矛盾 → WARN+FAIL exit 1；内容一致 → 0 矛盾 exit 0
- **C14 信封统一**：
  ① harness §1 定为**唯一 SSOT**（此前三处模板并存、字段集互不相同：上行16/下行13/成员12）；
  ② 模板补 `from`/`to` 字段——此前反投毒对账以 `from` 为锚但模板无此字段，
     成员按模板回传**必然**被判 SPOOFED_SENDER（规则恒误杀）；
  ③ 5 个成员 MD 的 result_envelope v2.4 模板改为**引用 harness §1**（不再复制字段表）；
  ④ `record_trace.py` 新增 `--from-envelope`：from/to/task_id/type 以信封为准
     （不一致 WARN 以信封为准），信封缺 from/to **拒收 exit 2**（来源不可验证=不可信回传）。
     三态实测：CLI 模式 / 信封覆盖+WARN / 缺 from 拒收，全部符合预期

## [2.2.0] - 2026-10-15

### Re-execution（同日，按用户裁决执行改进方案 P0-1/2/3 + P1-1/2）
- **P0-1 顺序裁决**：13 态 SSOT（pipeline skill + progress.py PHASE_ORDER）确立为权威；
  team-lead SOP 重排：保留 B/C/D/E 派工，PROOFREAD 独立成段显式派给 quality-examiner R4 风格审查，
  CONSOLIDATION 排 VISUALIZE 之前（取代原 F 可视化与 E 并行方案），ASSEMBLE+DELIVER 拆段。
  W1/W2/W3/W4 流程同步更新。**静态契约 C7 新增**：13 态每态在 SOP 中有派工段 + PROOFREAD→examiner 显式断言
- **P0-2 PROOFREAD 派工**：quality-examiner R4（AI 腔/术语一致/学段语言/排版节奏），
  与 E 串行且全 pass 后启动——保持四轮审查结构不变
- **P0-3 工具名前缀去写死**：scout.md / examiner.md / citation-verify.md 移除裸
  `mcp__paper_search_server__*` / `mcp__pubmed__*` 等前缀写死；harness §5.1 新条款
  明确「首次使用必须 ToolSearch 解析当前环境可用工具」+ 唯一可写死的常值是降级链 URL。
  新增静态契约 C7b（grep 成员 MD/skill 排除裸前缀）+ harness §5.1 豁免白名单段
- **P1-1 散文漂移门禁**：M 门禁扩至 14 项（M10a/b/c）—— README 头部版本/技能数声明
  /主理人体积声明 与 `wc -c`/`ls skills/` 实际比对；人为改 13.4KB→9.9KB → M10c FAIL 验证
  通过
- **P1-2 install.sh 注册路径行为验证**：干净 HOME 实测发现 install.sh 写入
  `$WB/my-experts/marketplace.json` 是 dead 位置，host 实际识别的 v3 路径是
  `$WB/my-experts/.codebuddy-plugin/marketplace.json`（register_expert 走的就是这个）。
  修复：改写路径 + 移除 `-d "$WB/my-experts"` 守卫（首次安装时 my-experts/ 尚未建） +
  拆 if 嵌套规避 zsh set -u 在 `[[ && $var && ]]` 中的作用域误判 + 改用 `${var:-}` 兜底。
  复测：干净 HOME 端到端 exit 0 且 marketplace.json 真实落到 v3 路径
- **P0-3 grep 门禁已入 M**：C7b 兜底 + 反向验证通过

### 缺口闭环（2026-10-15 交付核查后）
- **实锤缺口 1：导出 zip 长期过期**——`smart-textbook-team.zip` 实为 2026-08-29 的
  **2.0.0 / 21 文件**老包，本轮全部改动（v2.2.1 / count_net_words / vendor / 两个新测试）
  一个都不在其中；根因是**手工打包无任何门禁**，一个月无人发现
- 新增 `scripts/package_release.sh`：版本四处自洽校验（.codebuddy-plugin / .claude-plugin /
  marketplace.json / install.sh）→ 打包 → 回读 zip 版本自检；`--check` 只校验不打包。
  正负样本双向验证：zip=2.0.0 时 exit 1 拒绝，zip=2.2.1 时 exit 0
- 导出包刷新至 **2.2.1 / 71 文件**（含打包脚本本身）
- CI 第 6 道门禁：`package_release.sh` 打包冒烟（导出物不入库，仅验脚本可跑）
- **实锤缺口 2：4 份报告长期未入库**——tb-writer 内 09-10 红队 / 09-18 提案 /
  10-15 诊断 / 10-15 执行报告长期 `??` 状态，已 commit（`38705a5`），
  并把 3.6MB zip 加入 .gitignore（真源在本仓，不应二次入库）
- 脚本自身踩坑记录：check 分支内 `ZIP_VER` 赋值后在 `set -u` 下引用报 unbound——
  与同日 install.sh 三次踩坑同源，已用 `${VAR:-}` 显式规避

### 延后任务（evo-17 候补，LE-20261015-06）
- P1-3 评测双端化（LLM-judge）、P1-4 整章级真实基线、P2-1 trace schema 版本化、
  P2-2 成本硬门槛、P2-3 evo-17 tag 合并、P2-4 澄清协议泛化—— 共 6 项登记候补,
  待用户下一章真实任务或专项迭代触发

> P1 真实运行（e2e-p1：ch08 PRODUCE-R2 → VERIFY-R2，含 E1 重试）产出 5 条 LEARN 候补，
> P2 按证据逐条落地修复。运行态证据 `tb-writer/.omc/e2e-p1/`。

### Added
- `scripts/count_net_words.py` — 净字数 SSOT 计数器（P2-4 / LE-20261015-01）：
  口径写死为代码 + 分步明细可审计 + `--self-test` 内置夹具 + `--target` 门禁判定；
  真实 ch08 稿三方口径 1203/1213/1329 → SSOT 终审 1213，与审查官独立复核一致
- subject-writer / quality-examiner MD 接入 SSOT 计数器，禁止手工自报净字数
- harness §6.4「成员开工三件套」+ §7 检查表 +1 项（P2-7 / LE-20261015-05）：
  接任务 3 步内先落盘骨架再逐段补全；E1 重试指令模板固化三条加固
- trace 信封新增 `estimated` 字段 + record_trace `--estimated` 旗标（P2-6 / LE-04）

### Changed
- `compute_metrics.py` 口径修复（P2-6 / LE-20261015-03）：
  ① 分派命中率按 task_id 去重取末态（E1 重试不双扣）；② 返工率改按
  「同 task_id ≥2 次成功交付」判定（旧口径把任务名里的 R2 第二轮审查误判为
  返工，真实数据 2/2=1.000 恒 FAIL）；③ 新增 retry_rate 参考指标。
  修复后 e2e-p1：1.000 / 0.000 / 0.000 / 1.5 全 PASS
- router 评测样本 26 → 40（P2-3）：13 类每类 ≥2（12 类达 3）+ 3 升级用例；
  检索-标准分支补中文法规关键词（兽药典/动物防疫法/畜牧法/公告）
- `assemble_spawn_prompt.py`（shared-core，4 包同受益）正文技能路径解析
  （P2-5 / LE-20261015-02）：成员 MD 正文声明的 `skills/*/SKILL.md` 相对路径
  解析为绝对路径注入（仅收录真实存在的文件），「前置门禁」从不可执行变为可执行

### Fixed
- **P2-1 citation-verify v1.3**：新增「中文法规/标准/公告源核验链」——
  国家法律法规数据库 / gov.cn / 农业农村部公告 / 国家标准全文公开系统 /
  中国兽药信息网 / WOAH 六类权威入口 + 中文源核验三要素（源真实/版次现行/数据可定位）
  + 时效性陷阱条款（旧版次引用 = FAIL）
- **P2-2 规则冲突消除**：examiner 鉴别点阈值 ≥2 与 role-assembly §3 ≥3 矛盾 →
  统一 ≥3 并互标 SSOT；role-assembly §5「examines ≥3 项否则 blocking」与
  examiner evo-10 口径（仅全空 FAIL）矛盾 → 对齐并废止旧条款

### Ops
- V4 防漂移门禁在 P2-5 后实际拦截 vendor 漂移一次（联邦 sha 02a69d1f… ≠ vendor b808ff8d…），
  按提示同步后 6/6 通过——设计目的首次达成

### CI（P3-2 归档）
- **实证：harness-gate 自 2026-09-30 建立以来 4 连 failure，从未通过**（静态契约
  默认路径指向安装态，runner 上必 FATAL）——P0 修复后首次转绿：
  - 首绿 run: https://github.com/virologist/smart-textbook-team/actions/runs/38651831819（P0-2b，2026-10-14）
  - 最新 run: https://github.com/virologist/smart-textbook-team/actions/runs/38658898153（v2.2.0，2026-10-15，
    ubuntu + Python 3.12.15，5 道门禁全过，router 40/40=1.000）
- P3-1（install.sh 清单同步检查）已于 2.1.1 提前落地：tests/test_manifest_sync.py M1–M9

### Re-audit（2026-10-15 独立再诊断驱动，同日第二轮）
- 静态分析代理 12 项发现中 8 项当日修复：task-router §1「12 类」计数失真、
  pipeline 统稿净字数「>20%」与 ±5% 门禁冲突（对齐 SSOT 脚本）、harness §6.2
  门槛表与 compute_metrics 实现同步、writer examines「≥3 项否则 blocking」残留
  对齐 evo-10（F21b 断言随改）、learn-protocol「环境无 tests/」失真、
  progress.py「append-only」自述失真 + init 幂等校验、README 版本/进化状态/
  技能清单/常驻体积失真、marketplace.json 2.0.0 漂移（M 门禁扩至 M9a，11 项）
- 诊断「CONTRIBUTING clone 地址 biodog」经复查**不成立**（全文无 github URL），未采纳
- 遗留进改进方案：VISUALIZE/统稿顺序双说法、PROOFREAD 无人调度、install.sh
  注册文件路径与测试读取路径不一致、检索工具名漂移、评测双端化等

## [2.1.1] - 2026-10-15

> P0 分发可安装性修复。来源：10-15 五维诊断（资源配置 3/5，「建而未用」）
> 报告 `tb-writer/docs/2026-10-15-smart-textbook-team-diagnosis-report.md`。

### Added
- `vendor/shared-core/` — shared-core 兜底副本 + `VENDOR.json` 清单（sha256/来源/同步命令）
- `tests/test_vendor_core.py`（V1–V6）：清单自洽 + 防漂移 + 安装态冒烟 + **git-clone 态隔离冒烟**
- `tests/test_manifest_sync.py`（M1–M9）：两份 plugin.json 必一致字段 + install.sh 逐循环技能覆盖
- shim `SHIM_DEBUG=1` 开关：打印 core 解析来源（federal / vendor）

### Fixed
- **P0-1 git clone 后 shim 退出码 3**（R9 联邦下沉回归）：解析顺序改为
  ① 联邦真源（自包根**父目录**起向上 4 层）→ ② `vendor/shared-core` 兜底 → ③ exit 3。
  安装态仍走真源不产生第二副本；clone/CI/离线态开箱可用。
- **P0-1b install.sh 漏拷 scripts/tests/vendor/.claude-plugin**：新建装的
  trace / progress / assemble_spawn_prompt 全部不可用（v2.0 起即存在）
- **P0-3 跨平台漂移**：`.claude-plugin` version 2.0.0→2.1.0、skills 补 `task-router`、
  description/author 对齐；install.sh 三处技能循环补 `task-router`
  （原 Claude Code / Desktop / Cursor 用户拿不到 router）
- **P0-2 E1c 伪阴性**：`.created-by-session` 为宿主安装标记，实测本机 7 个专家包
  全不存在 → git/CI 态恒失败。降级为不计分环境观测项（`Checker.check_env`）

### Changed
- 静态契约评测 0.983 → **1.000**（199 计分项 + 1 环境观测项）
- CI 门禁 2 道 → 5 道（+ vendor core、+ 清单同步、+ install.sh 干跑冒烟）；
  静态契约阈值 0.95 → **0.99**（E1c 解耦后 1.000 可达）

## [2.1.0] - 2026-09-30

> 九维编排诊断（evo-16）驱动修复 + 成员人设注入协议（并行会话平台实测）合成落地。
> 诊断全程轨迹与 before/after diff 见 `tb-writer/docs/2026-09-30-smart-textbook-team-orchestration-audit.md`。

### Added
- `scripts/assemble_spawn_prompt.py` — 确定性装配器：成员 MD 全文注入 + skill 绝对路径 + 白名单/任务包校验（teammate 裸 spawn 不注入人设的平台实测对策）
- team-lead「成员人设注入协议」（P0 强制三步：装配 → spawn → 以落盘文件收产出，SendMessage 仅作通知）
- harness §2「黑板权属双模式」（evo-16b 合成）：注入模式成员亲 patch / 裸跑模式 lead 核验代 patch——消除两协议矛盾
- 成员 MD ×5 新增「工具白名单」与「收尾三件套」契约行（trace + progress + 黑板，义务不再依赖派单指令复述）
- harness §6.3 第 0 条 + team-lead「初始化双工件」：Phase A 同轮创建黑板 + progress（堵初始化断链）
- harness §2 操作规则 5/6：门禁即时推进 + 预算对账活字段（tokens_used 按 trace 累加）
- task-router §6 同步义务声明；harness §7 检查表 +2 项（黑板初始化 / gate 即时推进）

### Changed
- `compute_metrics.py` 平均轮次口径修复：改按「同 task_id trace 行数中位数」（可审计），成员自报 turns 降为参考列
- `tests/test_router_eval.py` 重构：枚举改从 skill §1 SSOT 解析派生（消灭双 SSOT）；修 2 处分支优先级误路由（核验→检索、图文一致→出图）+ 1 处运算符优先级 bug；置信度按 §2 四步信号合成；用例 22 → 26

### Fixed
- **P0 黑板/进度初始化断链**（实战实证：黑板缺失 → 全员「读黑板/patch」义务落空）：Phase A 强制双工件初始化
- **P1 成员义务可达性**（实战实证：指令不复述则 trace/progress 双落空）：义务写死进成员 MD + 成员侧加载范围扩至 harness §6
- **P1 router 离线评测失真**：19/22 → 26/26（含 2 个实战级误路由修复）

### Tests
- 静态契约评测 0.983（185/186，E1c 为应用侧会话标记，非本轮引入）
- router eval 26/26（1.000）；metrics 口径 median=1.0 PASS（自报 9.0 仅参考）

## [Unreleased]

### Planned
- Enable IMA OpenAPI for citation verification (currently static + offline)
- Add CHANGELOG note for A+B integration findings (see `tb-writer/docs/2026-09-10-ab-integrated-integration-report.md`)
- Hook system for member-to-member injection detection (harness §1.1 enhancement)

---

## [2.0.0] - 2026-09-10

### Added
- `role-assembly.md` — single source of truth for multi-expert role assembly (replaces external `expert-pool.yaml` reference)
- `install.sh` (macOS/Linux) — cross-platform installer with `--target` selector
- `install.ps1` (Windows PowerShell) — cross-platform installer with `-Target` selector
- `LICENSE` (MIT) and `CHANGELOG.md` and `CONTRIBUTING.md` — preparation for public release
- Bilingual README (Chinese / English) with platform support matrix and uninstall instructions

### Changed
- `plugin.json`: removed placeholder `email` (full anonymity), replaced PNG avatar references with emoji fallback (no PNG assets shipped)
- `subject-writer.md`: rewrote role-assembly reference from external `expert-pool.yaml` to internal `role-assembly.md` (closes cross-team dependency)
- `agent-harness-protocol/SKILL.md`: added explicit "layer distinction" between tool-level retry and task-level retry (closes semantic ambiguity)
- `smart-textbook-team-team-lead.md`: added `version: 2.0.0` (was missing after evo-11/13 compaction), W2/W3/W4 workflows now declare prerequisites
- `plugin.json`: `tags` and `quickPrompts` arrays preserved unchanged

### Fixed
- **BUG-1 (P0)**: subject-writer reference to external `expert-pool.yaml` was broken (file outside the team, no path declaration, role_id naming mismatch, missing `examines` field). Now references `role-assembly.md` inside the team.
- **BUG-2 (P1)**: semantic ambiguity between `E1 retry ≤3` (tool-level degradation chain) and harness `same-approach retry ≤2` (task-level). Explicitly distinguished.
- **BUG-3 (P1)**: boundary filter and token budget rules in `agent-harness-protocol` were unreachable for members. Added explicit "member-side safety obligation" in team-lead and a dispatch checklist item in harness §7.
- **BUG-4 (P2)**: `team-lead.md` was missing `version: 2.0.0` field after evo-11/13 compaction. Restored.
- **BUG-5 (P2)**: W2/W3/W4 workflows declared "skip X" without declaring prerequisites. Each now states what input must already exist.

### Tests
- `tests/test_smart_textbook_team.py` — **1.000 / 1.000** (183 checks, 0 fail)
- `tests/test_triz_invention_team.py` — **1.000 / 1.000** (regression, 0 fail)
- Red-team audit — 5 bugs found via 32-perspective parallel analysis, all fixed in commit `d2da143`

---

## [1.x] - Evolution History

This package evolved from `content-forge v5` (tb-writer project) through **evo-1 to evo-13** iterative cycles:

- **evo-1**: Initial team scaffold with 5 agents
- **evo-2**: 1.000 score on internal test suite
- **evo-3 to evo-7**: Harness protocol upgrades — role matrix, message envelopes, state blackboard, retry/timeout/budget, circuit breaker
- **evo-8**: Red-team + Darwin audit — injection defense, examination verification, blackboard anti-poisoning, budget reconciliation, sender authentication, cache discipline, version discipline (1.0.0 → 1.1.0-1.2.0)
- **evo-9**: LEARN candidate pool — first activation, deadlock resolution, degradation fatigue cooling, cross-`task_id` retry counting, side-effect boundary check; harness v1.2; R-class protection 32 → 37
- **evo-10**: Three-pronged deep evaluation — examination-explosion contradiction unification, retry rounds 4→3 alignment, first real LEARN candidate import (ch06 field practice 3 items), R12 semantic sync
- **evo-11**: Compact team-lead from 22KB to 6.8KB (-69%); 154 → 347 baseline checks all green; safety C→B+
- **evo-12 / 12a**: P2 candidate merge, schema-versioned patches
- **evo-13**: Final hardening before v2.0.0 release

See `tb-writer/docs/2026-09-10-smart-textbook-team-redteam-report.md` for the full red-team audit.
