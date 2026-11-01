# Changelog

All notable changes to **smart-textbook-team** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 批次 B1/B2/B3/B4/B5/B6：状态机归一（ADR-04）+ 反幻觉加固（ADR-03）+ 判据学科化（ADR-02）+ 硬门槛落盘（ADR-05）+ 全书层（ADR-01）+ 横切验收口径（GATE2 §6）

> GATE2 变更单 B1–B6 全部闭合。单章流程行为语义除判据口径加固（更严）外不变；
> 全书层与硬门槛为纯增量（4.14 缺文件 N/A）。

### 学段受众 profile 化（#71，2026-11-01 批次 2）

- **新建 `references/audience-profiles.md`（唯一新文件，学段判据表 SSOT）**：四档
  （枚举四值见该文件 §0，学科中立措辞不在本条复述）× 五列判据（句长锚点/案例密度/
  公式纪律/结构裁剪/术语铺垫）；audience 未声明 → 回落默认档且**须在 issues 显式
  声明**（禁止静默回落，与 profile 缺失回落同纪律）；五维评分与 80 分红线任何档
  不豁免。
- **判据 Q1（学段中立，机械）**：`check_domain_neutral.py` 新增学段常量词表段
  （`check_audience_terms`：HARD 执行体词 → FAIL / SOFT 举例措辞 → WARN）；
  学段词扫 **md 正文**（学段画像病灶在通用行文，与学科词只扫代码块不同）；
  豁免 `references/audience-profiles.md`（SSOT 本体）与 `references/profiles/`。
  FAIL 计数并入既有出口（学科 HARD + 学段 HARD + 硬路径）。
- **判据 Q2（audience 枚举合法，LLM 执行层）**：examiner R1 校验 chapter_design
  frontmatter `audience:` ∈ audience-profiles §0 枚举；didactic-architect 输出契约
  补 frontmatter 必含 `audience:` 声明。不新增脚本（与既有门禁 1 同层）。
- **五处写死段改挂 SSOT**（不改 `vocational-edu-adapter` role_id——kebab-case
  稳定标识，保 draft frontmatter 兼容）：subject-writer 学段适配表达改按档逐列执行；
  visual-instructional-designer 认知负荷判据挂表；quality-examiner R2 学段维
  「经验式检查」→「按 SSOT 对应档逐列检查」+ R1 判据 Q2；role-assembly §1/§2/§3/§7
  判据基准与 role_name 挂表；chapter-structure §5 裁剪细则收敛为引用
  audience-profiles §1（本节只留口径引用）。
- **测试与 CI**：静态契约 +3 计分项（F41a–F41c：SSOT 结构 / 学段中立门禁实跑 /
  五处执行挂点），277 → **280**；CI「学科中立性门禁」步扩学段词探针（回潮必须拦 +
  SSOT 豁免自证）+ audience-profiles 三节结构断言（与三 profile 断言同段）。

### 评审申诉通道（#70，2026-11-01 批次 1）

- **零新脚本、零新信封字段**：申诉载体 = 既有 RESULT 信封 `issues` 带
  `APPEAL:<问题指纹>` + `context_refs` 附新证据位置；仅针对单项 blocking 提出
  （correlation_id 级全量重审仍走既有返修循环）。
- **判据 A1（新证据可判定）**：主理人 diff 申诉 `context_refs` vs 原 blocking 审查
  报告 evidence 清单，差集非空才受理；A1 属 LLM 编排层（与介入协议同层），不进
  check_manuscript。
- **判据 A2（申诉 ≤1 次）**：复用 `record_trace.py --reject-key`，键前缀
  `appeal|<correlation_id>|<指纹>`；`progress.py rejects` 对 `appeal|` 前缀键显示
  「申诉已用（该指纹禁再申诉）」。**appeal| 键与介入协议语义隔离**——介入阈值只认
  无前缀打回键（record_trace 触发分支按前缀跳过 + rejects 的 INTERVENTION 判定排除
  appeal 键，双向隔离；risk §5.5 负向断言入 CI）。
- **主理人三步裁决**：① A1/A2 校验不过 → 不受理（trace 记 appeal_denied，不计打回
  计数）；② 受理 → 派 examiner 只核新证据本身、不重开全轮（结论三选一：维持/撤销/
  部分撤销）；③ 成立 → `progress.py resolve` 撤销 blocking + trace 记 appeal_granted；
  不成立 → 维持原判 + 原指纹 reject-key 累加（与介入协议自然衔接）。
- **契约同步**：harness §0「判定冲突」行下补申诉流程段；subject-writer「SendMessage
  回传」补申诉信封通道（禁止正文口头申诉、抗辩不豁免返修时限）；quality-examiner
  补申诉复核职责（核心能力 6）。
- **测试与 CI**：静态契约 +4 计分项（F40a–F40d：声明存在性 / appeal 键隔离 / 两端
  契约 / CI 探针在场），273 → **277**；CI +1 步「申诉通道冒烟」（appeal 键两次写 →
  申诉已用显示 + INTERVENTION=0；block→resolve 撤销闭环；A1 不受理无键增量；对照
  组无前缀键照常触发介入），CI 18 → **19 步**。

### 横切验收口径（GATE2 §6，批次 B6）

- **M1 · 破坏样本 15/15 判据族**：CI 步骤「门禁4负向实验扩容」为 4.0–4.14 每族构造
  最小破坏样本（frontmatter 缺项/标题跳级/图位缺题注/悬空引用/文献断号/docx 坏 zip/
  图未栅格化/字数偏离/习题断号/无思政标记/数据图无 notebook/禁用写法/溯源表缺失/
  孤立修订标记/R5 总分不达标），断言 --strict exit≠0（4.9 存在性为 advisory 级，
  按设计断言「被标记」不阻断）。负向覆盖 4/14 族 → **15/15**（含 B4 新增 4.14）。
- **M2 · 原场景不退化**：元规则入 CONTRIBUTING（修 A 必须同时交 ① A 的新负向用例
  ② 修复前拦住过的东西修复后仍被拦住的回归用例）；M1 基线前置「破坏样本前先证明
  基线绿」即该规则的执行体。
- **M3 · 声明与行为解耦校验**：新增 `scripts/check_declaration.py`——文档「由 X 拦截/
  由 Y 生成」三模式反查（判据号→r.add 实现行 / 脚本能力词→工件词表可反查 /
  --flag→argparse 注册），查不到 → WARN 进技术债清单。首跑揪出 5 条真债并全部处置：
  **B-12 PDF 虚构职责**（path-ownership.md:41 声明 .pdf 产出、脚本无 PDF 代码 →
  对齐 D-11 口径改 PNG/SVG）、`build_chapter.py` 两处幽灵脚本引用（勘误措辞改写）、
  `--skip-skill-preload` flag 无实现（补进 assemble_spawn_prompt.py shim 包私有增量：
  注入降级指令，联邦 core 零改动）。终态 **TECH_DEBT=0**（93 条声明全反查）。
- 静态契约 269 → **273 计分项**（F39a–F39d 4 项横切守护），1.000 全绿；CI 步骤 17 → **18**。

### 硬门槛落盘（ADR-05，批次 B4）

- **R5 评分机械化**：新增 `scripts/score_quality.py`——五维得分（`--dim 名称=得分`）+
  逐维证据位置（`--evidence`）进脚本，加权/红线/权重和判定机械落盘 `运行态/r5-score.json`；
  rubric SSOT = `chapter-structure.md §2` 五维表（`--rubric` 可换六维 profile）。
- **判据 4.14 R5 硬门槛**（check_manuscript）：`r5-score.json` 存在时——total≥80 ∧
  total==Σ(维度×权重)/100（**独立重算防手改**）∧ 权重和==100（**防伪造权重**）∧
  每维 ≥1 证据位置 ∧ 缺省五维下权重与 rubric 一致（4.14f）；不存在 → N/A 不阻塞
  （可先上线观察一月再转 FAIL）。判据表（manuscript-delivery §4）同步补 4.14 行。
- **打回计数机械化**：`record_trace.py --reject-key "<correlation_id>|<问题指纹>"` 累加
  `运行态/reject-counts.json`，计数 ≥2 **自动触发介入协议**（打印 INTERVENTION_TRIGGERED）；
  `progress.py rejects` 可视入口。介入触发从「人工判 2 轮」改为脚本值。
- **trace 字段补齐**：`confidence` / `gate_verdict`（JSON 化 pass-fail 清单）/ `issues` /
  `root_cause`（A/B/C/D）4 新字段；`--from-envelope` 5 → **19 字段全解析**
  （ENVELOPE_FIELDS_PARSED=n/19，解析结果整体落 trace `envelope` 子对象——消除
  「trace 与信封两张皮」A-09/A-26）。
- **预算可行化四件套**（harness §2/§3.1）：硬上限 80K→**150K**（A-17：单 spawn 底噪
  19–29K × 6 ≥114K，80K 算术不可满足）；`tokens_per_phase` 4 态 → **全 13 相位**；
  黑板模板补 `budget.cuts` 键（A-24：规范要求了模板里不存在的键）；新增
  **`--skip-skill-preload` 降级档**（预算 ≥80% 跳过非关键 skill 预加载——原降级策略
  无可执行削减项，超限后无法回落到线内）。
- **R5 联动**：quality-examiner R5 改「**必须跑 score_quality.py**（脚本为主、LLM 为辅），
  禁止手写 r5-score.json 绕过脚本」（v2.1.0）。
- **附带清偿 B5 登记技术债**：build_manuscript 单章 PAGE 域改 `OxmlElement` 权威写法
  且不套吞错 except——旧 `add_fldChar` 调用 AttributeError 被静默吞掉，单章 docx
  页码域从未真正写入（F38g 守护：`run._r.add_fldChar` 调用绝迹）。
- **CI 修复（B5e 待确认点实证）**：「书稿交付链冒烟」夹具 2 处裸 `[实]` 被 B2 的
  4.12d 拦截（FAIL 1，实测确认）——补 `（PMID:38960123）` 锚后 FAIL 0 / PASS 25。
  新增 CI 步骤「4.14 硬门槛正负双向」：正向（score_quality 产出+4.14 放行+N/A 放行）
  + 四负向（total=79 拦 / 权重和≠100 拦 / 证据缺失拦 / 手改 total 拦）+ 打回计数
  （2 次触发介入）+ 信封 19/19，与 GATE2 量化标准逐条对齐。
- 静态契约 261 → **269 计分项**（F38a–F38h 8 项硬门槛守护），1.000 全绿。

### 全书层（ADR-01，批次 B5）

- **双层状态机**：`progress.py` `PHASE_ORDER` 扩为 23 相位（5 个 `BOOK_*` 全书相位 +
  18 个章域相位）；新增 `book init`（book-spec.md + 「Progress · 全书」段，幂等、章清单
  不符 exit 2 防串书）、`book-status`（全书进度矩阵）。单章 WORK_ROOT 行为零破坏：
  同一 WORK_ROOT 仅在「做过 book init」时允许多章，否则保留原 exit 2 硬失败。
- **新增 `scripts/check_book.py`**（全书门禁 5.1–5.5）：5.1 章清单完整 + 各章净字数和
  vs 总预算 ≤5%；5.2 每章知识域 + chapter-map 依赖序无环（DFS 三色判环，BOOK_SPEC
  未执行 N/A）；5.3 逐章复用 `check_manuscript --strict`（判据共源，不另立判据）；
  5.4 复用跨章六项（check_cross_chapter）；5.5 合稿 docx 可开（非 BadZipFile）+
  docx media 数 == 各章唯一图位对之和 + 字数达标（口径锚定各章交付 md 之和——合稿
  直数因删章级/增全书参考文献节必然漂移，装机实证）。
- **新增 `scripts/build_book.py`**（全书装配器）：各章交付 md + book-spec →
  `{教材名}_合稿.md` + `{教材名}.docx`。图号/表号按全书出现顺序重排（题注/图位/
  交叉引用同一映射，key=(章序,前缀,序) 三元组——(前缀,序) 二元组会让各章「图 1-1」
  撞成同一张）；参考文献跨章按条目串去重合并 + 全书重编号；单 pandoc 调用
  （`--toc` → TOC 域、单 sectPr → 页码连续不分节重启）；版式常量复用 build_manuscript
  TYPESET。**修复附带发现**：python-docx 的 `CT_R` 无 `add_fldChar` 方法——单章
  postprocess 的 PAGE 域写入一直在 AttributeError 后被静默吞掉；合稿版改用
  `OxmlElement` 手工构造域且不吞错。
- **新增 skill `skills/book-orchestration/SKILL.md`**（全书流程 SSOT）：BOOK_* 相位
  表 / 命令链 / book-spec 语义 / 5.1–5.5 判据表 / 与单章接缝。
- **跨章检查 3 → 6 项**（`check_cross_chapter.py`）：新增 ④难度递进（Bloom 单调不减）、
  ⑤字数分配（各章 vs 预算 ±10%）、⑥图号/表号章内连续性；术语一致性改读 profile §5.1
  五列表（ADR-02 口径），`--terms` 参数删除。
- **文档同步**：team-lead 新增 W5 全书工作流；harness §2 黑板 schema 加 `book` 段、
  §6.3 加全书续跑判定（23 相位）；manuscript-delivery 新增 §5.3 全书装配 + v1.2.0。
- **清单/安装器同步**：两份 plugin.json + marketplace.json + install.sh（3 处循环 +
  declared 集合）+ install.ps1（3 处循环）+ README（10 个 skill、261 计分项）全部登记
  book-orchestration——M7/M9a/M10b/M12d/M13a/M13c 六道清单门禁从红转绿。
- **CI 第 17 步「三章成书端到端」**：book init → 逐章 assemble → check_book --strict
  （正向 exit 0）→ build_book（合稿四要素断言：可开 / TOC 域 / 单节页码 / 参考文献去重
  合并）+ 三个负向（删 frontmatter → 5.3 拦、术语两写法 → 5.4 拦、字数偏离 15% →
  5.1 拦），与 GATE2 量化标准逐条对齐。
- 静态契约 258 → **261 计分项**（3 项清单断言），1.000 全绿。

### 反幻觉加固（ADR-03，批次 B2）

- **4.12d 逐处锚定**（修「空集恒真」）：每个 `[实]` 后 120 字符窗口内必须有可检索锚
  （PMID/DOI/ISBN/中文权威源/本地源三形态 `[[笔记]]`、`本地:路径#锚`、`ima:{kb}:{doc}`），
  裸 `[实]` FAIL（旧口径集合差为空恒 PASS，C-35 实测伪造合规结论）。
- **4.13a 逐处配对 + 显式声明**（修「全局单侧放行」）：每个 insertion 须满足
  同段配对 deletion（±200 字符）/ `[整段新增]` 标签 / 「新增章节」区锚定之一；
  `n_ins == n_del` 的计数巧合不再放行。
- `RE_SOURCE_ANCHOR` 收窄：「法」单字后缀误放行「7 日龄法氏囊病」，改 `《…法》` 书名号
  锚定并补「条例/规程」。
- H9N2 真实稿回归：FAIL 0（无误杀）；CI 负向⑤⑥⑦落地。

### 判据层学科化（ADR-02，批次 B3）

- **五项判据执行体下沉 profile**（§5.1 术语表五列 / §5.2 章节八要素 / §6 审查基准 /
  §7 数值触发词）：三 profile（veterinary/computer-science/law）齐备；veterinary §5.2
  八要素自 chapter-structure.md §1 逐字搬迁（兽医行为零退化）。
- **术语表三级查找**：`{WORK_ROOT}/学科标准/术语表.md` > profile §5.1 >
  `terminology-table.example.md`（包级单例降级为示例模板，改名保留历史）。
- **新增 `scripts/check_domain_neutral.py`**：学科常量词回潮通用层 → FAIL（HARD 执行体
  词 / SOFT 机构法规词 WARN）；`.py` 用 `ast` 识别 docstring（行级三引号开关曾把
  self_test 夹具误当代码——假阳性根因）；`.md` 只扫代码块。
- **新增 `scripts/_profile_loader.py`**（共享加载器）：`read_discipline` /
  `load_section7` / `load_term_table` 三脚本共源，消灭「同一概念多处定义」。
- CS 端到端：「人工智能（AI）」4.11 PASS（兽医域 AI 才是禁用）；「资产负债率 68.4%」
  无标签 3.1 报缺（旧写死 11 个兽医指标，非兽医学科恒绿）。
- CI 新增学科中立性门禁（正负双向）+ CS 教材章端到端。

### 状态机归一（ADR-04，批次 B1）

- **PHASE_ORDER 唯一权威归一**：僵尸态 `VERIFY-R4`/`VERIFY-R5` → `PROOFREAD-R4`/`PROOFREAD-R5`
  （R4/R5 属 PROOFREAD 态，旧名全包 0 处写入）；`PRODUCE`/`VERIFY`/`PROOFREAD` 粗粒度
  别名修正（`VERIFY` → `VERIFY-R3`）；四方文档（progress / pipeline / harness / team-lead）
  统一为「唯一权威 = PHASE_ORDER，业务视图只引用不复述枚举」。
- **相位字面量机械门禁**：新增 `scripts/check_phase_consistency.py`（A/B/C 三层自检：
  契约快照逐项且顺序比对 / 别名目标合法 / 废弃名不复活）；238 处相位字面量扫描
  **0 不一致**；CI 新增「相位一致性门禁」步（快失败位）。
- **LegacyPhaseError + `migrate`**：旧相位名写入报错并提示新名（exit 2）；
  `progress.py migrate` 一次性迁移旧运行态；续跑演练负向（`VERIFY-R4` 写入被拦）通过。
- **N-2 路径清理**：用户级插件安装根绝对路径硬编码 → 0 命中（`EXPERT_DIR` 显式解析优先，
  双宿主安装根兜底）。
- 静态契约 257 → **258 计分项**，1.000 全绿；行为语义零变化（执行顺序/门禁触发/审查
  轮次归属逐项不变）。

## [2.5.0] - 2026-11-01

### P1-P3 全量执行（真实章节全链路 + 遗留清单清零）

> **本轮性质**：上一轮（2.4.0）是"按诊断清单修"，本轮是**"拿真实章节去跑，让缺陷自己冒出来"**。
> 用真实题材（H9N2 禽流感，>2000 字 R1 全链验证稿）走完 SPECIFY→DELIVER，
> 实战暴露 4 个夹具测不出的缺陷；随后执行上一轮登记的 P2/P3 遗留 6 项。

### P1-1 真实章节全链路验证（实战暴露 4 缺陷，修 3）

- **轨道 B 补齐（高价值）**：数据图由 `ipynb` 直接产 PNG，md 里没有 mermaid/svg 代码块 →
  `build_manuscript.write_source_assets` 把它们全判成 orphan 图位，**docx 里一张图都没有**
  （4.6a 却显示 0 == 0 全绿）。现 `rasterize` 前先扫 `assets/{stem}.png` 并注册为
  `kind=data-png` 资产；图位替换按 `fence_start` 偏移定位，两侧永不分歧。
  实测 docx 187KB → 243KB，2 图真实嵌入。
- **4.12 口径修正**：`[实]` **处数** == 溯源**行数** 是错口径（同一 PMID 在一章内多处引用是
  教材常态，处数 >> 行数，恒 FAIL 且无法靠补日志修好）。改为**唯一标识符覆盖**：
  正文每个唯一 PMID/DOI 都必须有溯源行。
- **nbconvert 本机卡死**：`jupyter nbconvert --execute` 对任意 notebook 超时（内核启动挂死）。
  设计上改为双档执行（见 P2-4），不再把环境问题当稿件问题。
- **术语 AIV 残留**：真实稿把 `[引]` 写成裸标签（见 P2-6）。

### P1-2 terminology-table 真实化

- 由 4 条示例行 → 6 条**真实术语**（禽流感 / H9N2 亚型禽流感病毒 / 低致病性禽流感 /
  新城疫 / 传染性法氏囊病 / 大肠杆菌病），并在真实章节下复跑 4.11 全绿。
- **修 4.11b 子串误判**（真实章节踩中）：别名是标准写法**子串**时（`H9N2 亚型` ⊂
  `H9N2 亚型禽流感病毒`），旧判定 `std in text and alias in text` **恒真** →
  只要用全称就判"两种写法并存"，且改稿无法消除。新增 `_occurrences()` 区间覆盖算法：
  **独立出现才算并存**；含包含关系的条目显式豁免并在 detail 声明
  （`包含关系豁免 4.11b: [...]`），不外判也不静默。
- §2 补「填表铁律」：别名列只放别名本身（塞说明文字 → 判据去找永不存在的字符串 = 假绿）。

### P2-4 nbconvert 执行级校验入 CI

- 4.10 的「可执行」此前只是**人工承诺**：结构查得像契约，语法错/缺依赖/导出路径错一律查不出。
  新增 `--exec-notebooks`（判据 **4.10e**）：真跑 notebook，**双档**——
  优先 `nbconvert --execute`；环境不可用时降级「逐 cell 直执行」（跳过 IPython magic 行），
  detail **显式标注降级原因**，绝不静默等价。
- **修导出路径契约缺陷**（P1-1 发现 #2）：`savefig('figures/assets/{图号}.pdf')` 在执行
  cwd = assets 目录时会去找 `assets/figures/assets/…`（不存在）→ 必失败。改为**裸文件名**
  `savefig('{图号}.pdf')`，notebook 可整体搬移、可被原样执行。负向实测：改回旧路径
  立刻被 `FileNotFoundError` 抓住。
- 4.10 结构阈值对齐契约：docstring 写「≥4 cell」而代码只查「≥3」，现统一为
  `4 cell = md 图说明 + 原始数据 + 绘图 + 导出`。
- CI 新增「数据图执行级门禁」步（正负双向）：合规 notebook 必须 exit 0 且产出 PNG；
  故障 notebook 必须被 4.10e 拦住。本地抽 run 块复演通过。

### P2-5 4.11c 首见位置判据实现

- 该判据此前只在 `terminology-table.md §3` 声明、**脚本零实现**（"判据表有、校验器没有"
  = 门禁可被绕过的假绿）。现实现：当前章号 < 表声明首见章号 且术语在正文出现 → FAIL。
- 实测发现表内 `大肠杆菌病: ch04` 是模板占位值与真实稿件冲突（ch01 鉴别诊断已正常引用），
  按**真实首见**改 `ch01`，并写明口径：`首次出现` 记录真实首见章，不是"希望它出现在哪章"。

### P2-6 `[引]` 标签核验缺口修复（红队中危 #8）

- **缺口**：`[引]` 只有 writer 会产出，examiner R3 与 citation-verify **全程不核** →
  编造的结论打上 `[引]` 即可绕过 `[实]` 溯源链（`[实]` 进溯源表被 4.12/4.12b 管，
  `[引]` 无人管）。**真实章节当场命中 1 处**裸 `[引]`（指向《兽药典》却不在参考文献）。
- 机械层：新增 **4.12c**——每个 `[引]` 必须同句紧跟可检索来源标识符，且来源在
  «参考文献»节中存在；裸引 / 悬空 / 跨句蹭来源三类全部拦截（四向行为测试入 F37d）。
- 语义层：`citation-verify` **方法 4c**（结论级核验）——①来源可检索 ②原文确有该结论
  ③**断言强度不外推**（相关≠因果、可能≠确定、动物≠人、体外≠体内、特定条件≠普适）④时效性。
  版本 1.5.0 → 1.6.0。
- 三方口径闭环：writer（产出铁律）/ examiner（R3 扩核验对象）/ citation-verify（方法 4c）。

### P3-7 多章成书跨章检测实战

- 真实 ch01 + 构造 ch02 注入三类矛盾（术语别名 / 数据矛盾 / 长句重复）实测
  `check_cross_chapter.py`：**当场抓到检测器缺陷**——数据矛盾的对象名正则限定为纯汉字，
  而教材指标几乎都挂在病原名上（H9N2 / H5N1 / E. coli / PRRSV 全是 ASCII）→
  **真实稿件里最该抓的一类矛盾永远不命中**（ch01 1% vs ch02 25% 双章 `[实]` 静默放过）。
  修后三类全命中（脏态 `--strict` exit 1），清理后 0 矛盾 exit 0。

### P3-8 H 框架对照审计文档

- 新增 `docs/harness-framework-mapping.md`：本包「13 态 / 五档预算 / E 码 / 门禁 4」
  与 H=(E,T,C,S,L,V)+P 六层的概念映射 + 覆盖度标记 + 缺口反查。
- 复用 H 框架「必答设计问题」**问出本包 3 个真缺口**（已登记）：
  ① E 层无墙钟预算与并行度上限；② C 层无上下文压缩/蒸馏策略（靠分批落盘绕开上限）；
  ③ L 层只有流程级生命周期、无事件级 pre/post hook。
- 反向补充 3 条可移植实践：机械/语义双轨门禁及顺序、判据表↔实现↔契约三方断言（F37）、
  **降级必留痕**（不允许静默等价）。

### 测试与门禁

- 静态契约 253 → **257 计分项**（新增 F37a–F37d 判据表↔实现↔行为对齐守护）
- router 45/45、manifest 31/31、vendor 6/6 全绿；CI 12 步（新增执行级门禁步）
- **F37c 设计教训**：判据表出现「4.6 / 4.13」这类**族 ID**（脚本按 4.6a/4.13a 子判据实现），
  断言须按前缀命中判定，否则误报

## [2.4.0] - 2026-10-31

### 从零独立诊断（第三轮，9 维度 × 3 并行红队子代理 + 教职成厅函〔2025〕1 号对标）→ 批次 E-H

> **诊断实证**（每条附证据，共 6 高危 + 11 中危）：R4/R5 轮次归属三文件矛盾（R5 无人派工）；
> 节级推进只有规范无派工动作；generate_team 三维评估两维恒真（构造「量子计算」等全未命中域
> 仍输出「全部来自 profile 映射」——实跑复现）；4.12 标识符核验零实现（FAKE-DOI 可伪造溯源全绿）；
> 金教材硬指标只有 R5 评分端无生产端；4.11 三缺陷（示例行消费/无词界/转义不解析）。

### Added（批次 E：机制核心）
- **pipeline §轮次归属 SSOT**：VERIFY=R1-R3（内容正确性）、PROOFREAD=R4+R5（交付质量）——
  team-lead/examiner/pipeline 三处统一，R5 五维+80 分红线接入派工链（`review-score` task_type）
- `scripts/assemble_sections.py`（新）：节级拼接器——设计 §C 节序解析 + 节级自检前置
  （缺标签 exit 1 拒拼）+ `拼接清单.json`（返修定位锚）；team-lead Phase D 补逐节派工序列
- progress.py：`VERIFY-R5` 态 + `resolve` 子命令（H15 回填后机械清零，防螺旋死锁）
- check_manuscript：**4.12b** 溯源标识符↔参考文献机械核验（PMID/DOI/ISBN/中文源锚提取）

### Added（批次 F：金教材生产端——评分端之外补生产端）
- architect 能力 7「岗课赛证融通规划」：§B 逐节三锚点（1+X 对接 / 赛点标注 / 立体化资源位），
  规划缺失 = R1 blocking；writer 能力 6 融通行文（`[资源位]` 标记）
- gap-types 枚举 7→**7+1**（`vocational-skill`：证书/大赛/岗位标准，核验深度=版次现行）
- chapter-structure §2 对接教职成厅函〔2025〕1 号遴选原则（五维 ↔ 五原则映射表）
- terminology-table 补 **4.11d** 口径（表内标准写法唯一——此前 §5 引用悬空）

### Changed（批次 G：口径统一）
- 打回介入阈值统一 **=2**（harness 防逃逸条款对齐 pipeline SSOT；第 3 轮仍败才停机）
- 路由升级码 **R→ESC**（ESC1-4——消除与审查轮次/写作版本的 R 前缀三重命名空间碰撞）
- task_type 枚举 **15 类**（+`review-score`/`review-style` 重定义/`gap-retrieval`）；
  confidence 统一 **0-100**；下行 `type: TASK`→`STATUS`+`payload.direction`（入 §1 枚举）
- record_trace 新增 **tokens 子命令**（确定性累加 trace，estimated 单列告警——
  替代「手工 patch tokens_used」必漂移路径，harness §2 规则 6 同步）
- citation-verify **1.5.0**：方法 4b 补 4 行（司法判例 `[实·判例]` / 司法解释 /
  RFC·语言规范 `[实·规范]` / dblp——对接 law/cs profile §3，换学科 R3 无行可套修复）

### Hardened（批次 H：对抗硬化）
- CI 第 8 步「门禁 4 负向实验」：FAKE 标识符 / 孤立插入标记 / 缺 notebook / 禁用写法
  4 组破坏样本**必须全 FAIL** 才过（此前 4.10-4.13 声称负向守护但无实体，CI 回退不红）
- router 评测 40→**45 用例**（新枚举 3 类 + 量纲统一 0-100 + gap 分支前移修复截胡）
- architect/writer/designer 副作用与输出契约同步（gaps.md/sections/.ipynb 三处此前越界死锁）

### Fixed（复查第 2 轮，独立验收代理查出）
- examiner 延迟预算行重复损坏（R1-R4 段粘贴两遍）+ 总超 240s 与 ≤300s 目标矛盾
- pipeline §3.6 步骤④残留「R1-R4」与新 SSOT 打架（E1 漏改点）

### Verified
- 静态契约 **253/253 = 1.000** + router **45/45** + manifest 31/31 + vendor 6/6 + lint-ps1 PASS
- 负向实验本地演练 4/4 全拦截；generate_team 正负双向（全未命中 0/3 构造 vs 命中 2/2）
- assemble_sections 正负实测（缺标签拒拼 exit 1 / 修复后拼接+清单落盘）
- 4.12b 双向（真 PMID 过 / FAKE-DOI-999 拦截 strict exit 1）

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

### 红队复查轮（独立子代理对抗验证 → 5 高危 + 4 漂移当日修复，R5）
> 红队实测（未读对话、只以文件与实跑为准）：链路机械闭环成立，但存在 5 个高危缺口。
> 全部当日修复并复测。

- **[高危→已修] b2 静默改字盲区**：4.13b 只数修订个数，拦不住「关追踪修订直接改字」。
  初版快照式指纹（构建时存 hash、校验不重算）实测**拦不住就地改字**（属性原样保留）；
  且初版基于 python-docx 文本的 hash 对 **w:ins 内文本全盲**（修订内 run 对 python-docx
  不可见——XML 级篡改实测穿透）。终版 **4.13d 双向锚**：属性存 `document.xml` 原始字节
  hash，校验侧**重算**比对——改正文/改修订内文本/换外来 docx 三向全部实测拦截
- **[高危→已修] b3 审阅版法外区**：`_审阅.docx` 此前不在任何判据覆盖内 → 纳入 4.13d
  （`4.13d-交付` + `4.13d-审阅版` 双行）
- **[高危→已修] c 4.10 数据内联检测失效**：`str(source)` 的 repr 括号 + 文件名数字
  误命中 `\[.*\d.*\]`（纯 import 假 notebook 实测穿透）→ 改为**逐行字面判据**
  （`= [` / `= {` / `= 数字` / 裸数字行），假 notebook 实测 FAIL
- **[高危→已修] 回流吞图位**：docx 渲染态已删 `[图 X-Y]` 占位行，回流以 docx 为准覆写
  → 图位永久蒸发（4.10/4.6a 静默 N/A）→ 回流时按题注行定位**恢复**旧 md 独有的图位行
- **[高危→已修] 4.13c 兜底漂绿**：三件套缺失时的兜底文本「未完成校稿（...）」可被
  `结论[:：]` 正则匹配 → 改为不含可解析形态的措辞 + 修订计数只认**修订标记语法**
  （不认表格叙述字面量）
- **[中→已修] TOC 残留**：pandoc 3.13 回流输出无属性块的 `# Table of Contents`，
  旧正则（要求 `{...}`）失效 → 改为无属性兼容 + 大小写不敏感
- **[中→已修] 4.10 冒号口径漂移**：官方示例规格卡用「数据来源=」而校验只认「：」→
  兼容 `[:：=]`
- **[中→已修] 溯源表列错位**：examiner 4 列（位置|标识符|结果|动作）被直接切片进 5 列
  溯源表 → 语义重映射（位置|结果→陈述要点|标识符→来源|动作→核验状态）+ 异常行 WARN
- **[中→已修] 4.12 口径**：契约「==」实现「>=」→ 对齐 `==`（多行也 FAIL）
- **[中→已修] 4.13a 纯插入语义**：整章一致纯插入/纯删除被「插删等量」误杀 →
  改为「替换场景（两侧均 >0）须等量；单侧场景放行」

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
