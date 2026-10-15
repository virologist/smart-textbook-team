# Changelog

All notable changes to **smart-textbook-team** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] - 2026-10-15

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
