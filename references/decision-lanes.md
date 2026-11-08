# decision-lanes.md — 裁决车道分级与进化安全规范（v2.11.0 ★C1/C2，2026-11-08）

> 立项依据：第六轮架构审计审计项 C（爆炸半径分级）——运行时「可逆局部却要人工（浪费）」
> 与「难逆转却可自动放行（危险）」并存；进化侧（改 skill 文件）零成文安全规范。
> 本文件是 C1（车道表）+ C2（进化安全）的成文落地；**只定义分级，不改任何现有门禁阈值**。

## 1. 三车道定义

| 车道 | 定义 | 放行方式 | 记录要求 |
|------|------|---------|---------|
| **绿** | 可逆 + 局部 + 有机械判据兜底 | 自动放行 | trace（既有埋点已覆盖） |
| **黄** | 可逆但影响面跨节/跨章，或判据半机械 | 确定性检查通过即放行 + 轨迹留存备审 | trace + 门禁结果落盘 |
| **红** | 难逆转 / 影响权威源 / 触及交付边界 | **永远人工**；**红道不设置信度阈值**——「模型自信」不是放行依据 | trace + interventions.md 人工签字行 |

## 2. 运行时裁决点分级表（对照现有组件逐一归道）

| 裁决点 | 所在组件 | 车道 | 归道理由 |
|--------|---------|------|---------|
| 节级自查未过 → 拒拼接 | assemble_sections §3.6 步骤② | **绿** | 机械判据（3.1/3.4 节内子集）+ 可逆（writer 重写该节） |
| contract_check 契约核对（PASS/PARTIAL/MISSING） | contract_check.py | **绿** | 逐项落盘机械核对；PARTIAL 处置仍由主理人按 on_partial 定 |
| 门禁 4.x 各判据（check_manuscript） | check_manuscript.py | **黄** | 机械可判但 blocking 直接决定返修方向（跨节影响）——检查自动、方向人工 |
| R2 波次 proposed_verdict | contract_check --wave | **黄** | 脚本给机器建议，`wave_verdict` 主理人落定（计划/授权分离纪律，不放宽） |
| R5 五维评分 <80 → 退回 | pipeline §PROOFREAD | **黄** | 评分为语义判断（LLM），但「退回」动作可逆且方向按维度定点 |
| 节级坍缩提案确认 | team-generation §0.1 | **红** | 团队构成 = 知识视角来源，confirmed_by_user 硬闸门（既有，不变） |
| E3 换成员 | harness §E3 | **红** | 换人不重置打回计数 + 审查职责不可被动态层绕过——影响协作结构 |
| 介入协议触发（打回 ≥2） | ADR-05 §5.2 | **红** | 根因 A/B/C/D 切换属策略变更，脚本只报不 spawn |
| B3 冻结基准重置（draft_r1_frozen） | pipeline §B3 | **红** | 冻结点是并行基准，重置 = 撕裂基准（回退成本高） |
| DELIVER 交付（md+docx 双格式） | manuscript-delivery §1 | **红** | 交付边界；check_book/check_manuscript 全绿也只是必要条件，放行永远人工终审 |
| 全书门禁 5.1-5.5 | check_book.py | **黄** | 机械可判；但 BOOK_DELIVER 进入本身是红道（见上） |

> 判道公式（供未来新增裁决点自归类）：`可逆性 × 影响面 × 判据机械化程度`。
> 三项全绿 → 绿；任一跨边界 → 至少黄；不可逆或影响权威源 → 红。

## 3. 进化安全规范（C2：改 skill / 脚本 / 测试）

### 3.1 进化红道（每次必须走完整惯例链）

改以下任一类文件 = 红道动作：
- `skills/*/SKILL.md`（协议/判据 SSOT）
- `scripts/progress.py` 的 PHASE_ORDER（结构不变式）
- `references/member-contracts.json`、`references/path-ownership.md`（契约/归属 SSOT）
- `.claude-plugin/plugin.json` 的 `agents[]`/`skills[]` 静态层

红道完整链（缺一 = 违规合入）：
**diff 预览确认 → 实现 → 测试（含反向例：不恒真放行、不静默吞错）→ 全量 pytest
+ CI 23 步全绿 → SKILL_CHANGELOG 登记 → 版本三处自洽（README/plugin.json×2/
install.sh + marketplace.json）→ package_release.sh --check → 推送**。

### 3.2 进化黄道（实现 + 回归即可，diff 可事后审）

- 新增 `scripts/*.py`（不触 SSOT）；
- `references/` 新增文档（不改既有归属表/契约表）；
- agents/*.md 的**措辞澄清**（不改变职责边界与产物路径）。

### 3.3 禁改项（任何车道都不可）

- 信封 21 字段集、path-ownership 唯一归属、PHASE_ORDER 23 相位、
  「脚本只报不 spawn」纪律、生成者/审查者分离。
  要改 = 先改本文件（新红道动作），走 §3.1 全链。

### 3.4 与 learn-protocol 的关系

候补池（`学习/候补/`）是**提案**层——本文件不改变「提案不自动合并」纪律。
提案被采纳 = 触发 §3.1/§3.2 对应车道流程。
