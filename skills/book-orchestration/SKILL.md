---
name: book-orchestration
description: "Whole-book orchestration spec (ADR-01, dual-layer state machine): book domain (BOOK_* phases) vs chapter domain (18 phases), book-spec.md as the chapter manifest, three-phase assembly (per-chapter pipeline → cross-chapter six checks → book build), plus whole-book gates 5.1-5.5 (chapter list + word budget ≤5%, domain/deps DAG, per-chapter strict, cross-chapter six, merged docx verifiable). Load when the user asks for a multi-chapter textbook ('整本教材'/'多章成书'/'全书'), or whenever book-spec, chapter schedule, merged deliverable, whole-book figure renumbering, or merged references are in question. Trigger words: 全书 / 整本 / 多章 / book init / book-spec / 合稿 / 成书."
---

# book-orchestration — 全书编排规格（ADR-01 · B5）

## 0. 定位与铁律

单章流程（`textbook-pipeline-workflow`）只管**一章**；多章成书时，章与章之间的
编排、全书装配、全书门禁归本 skill。**不新增成员**：team-lead 兼任全书编排者，
本 skill 承载全书流程知识。

- **双层状态机**：`book` 域（BOOK_* 5 相位）+ `chapter` 域（18 相位），互不干扰；
  权威枚举 = `scripts/progress.py PHASE_ORDER`（23 相位），只许引用不许复述。
- **单章行为零破坏**：不做 `book init` 的单章 WORK_ROOT，行为与 B5 之前完全一致。
- **md 是源**：合稿 md 可独立交付，`交付/{教材名}.docx` 是它的渲染态；改书回各章
  draft.md → 重装各章 → 重建合稿，禁止手改合稿产物。

## 1. 全书相位与产物（BOOK_* 5 相位）

| 相位 | 产物 | 门禁 |
|---|---|---|
| BOOK_BOOTSTRAP | `运行态/book-spec.md`（章清单/每章字数/难度梯度/目标学段） | 5.1 章清单完整、字数总和与用户目标偏差 ≤5% |
| BOOK_SPEC | `章节/_book/chapter-map.md`（章→知识域→成员→依赖序） | 5.2 每章有知识域、依赖序无环 |
| CHAPTER_SCHEDULE | 逐章调用单章流水线；`progress.py update --chapter` 回写 | 5.3 每章 `check_manuscript --strict` 通过才可进下一章 |
| BOOK_CONSOLIDATION | `交付/{教材名}_合稿.md`（build_book.py） | 5.4 跨章六项（check_cross_chapter） |
| BOOK_DELIVER | `交付/{教材名}.docx`（TOC 域/连续页码/参考文献合并/图号全书序） | 5.5 合稿可开、图数一致、字数达标 |

## 2. 命令链（SSOT）

```bash
# ① 全书初始化：book-spec.md + progress.md「Progress · 全书」段
python3 scripts/progress.py --work-root "$WORK_ROOT" book init \
    --textbook 教材名 --chapters ch01,ch02,ch03 \
    [--audience <audience-profiles §0 枚举值>] [--word-budget 300000]

# ② 全书进度矩阵（各章处于哪一相位）
python3 scripts/progress.py --work-root "$WORK_ROOT" book-status

# ③ BOOK_SPEC：主理人手填 chapter-map.md（BOOK_BOOTSTRAP 生成的 spec 只有骨架）
#    表式：| 章 | 知识域 | 成员 | 依赖章 |（依赖列写章 id，无依赖写 —）

# ④ CHAPTER_SCHEDULE：逐章跑单章流水线（W1），每章 DELIVER 后：
python3 scripts/progress.py --work-root "$WORK_ROOT" update \
    --phase DELIVER --status DONE --summary "ch01 过 strict"

# ⑤ 全书门禁（5.1–5.5；--strict 任一 FAIL 即 exit 1）
python3 scripts/check_book.py --work-root "$WORK_ROOT" --strict

# ⑥ 全书装配：章交付 md → 合稿 md + docx
#    （TOC 域；单节连续页码；参考文献去重合并 + 全书重编号；图号重排为全书序）
python3 scripts/build_book.py --work-root "$WORK_ROOT" [--reference-doc tpl.docx]
```

## 3. book-spec.md（BOOK_BOOTSTRAP 产物）

由 `progress.py book init` 生成骨架；主理人在 BOOK_SPEC 相位补全
`difficulty`（L1/L2/L3 梯度）与 `domain`（知识域）。幂等：章清单一致重复 init
直接返回；不一致 exit 2（防串书）。

## 4. 全书装配语义（build_book.py）

- **确定性装配**：只搬移、拼接、重编号，不改写内容。
- **图号/表号全书序**：`图 {章}-{序}` 按全书出现顺序重排为 `图 {全书序}`；
  图位行、题注行、交叉引用用**同一映射**（分开映射必漂移）。
- **参考文献合并**：各章 `[n]` 引用与条目行按「条目串」去重合并、全书重编号；
  章级参考文献节删除，全书统一放末尾。
- **TOC + 连续页码**：单 pandoc 调用（`--toc` → TOC 域；单 sectPr → 页码不分节重启）。

## 5. 全书门禁（check_book.py 5.1–5.5）

| # | 判据 | 口径 |
|---|---|---|
| 5.1 | 章清单完整 + 全书字数 | 声明章 == 磁盘章（双向）；各章净字数和 vs `total_word_budget` ≤5% |
| 5.2 | 知识域 + 依赖序 | 每章 domain 非空；chapter-map 依赖序无环（DFS 三色判环）；BOOK_SPEC 未执行 → N/A |
| 5.3 | 单章门禁共源 | 每章 `check_manuscript --strict` exit 0（复用门禁 4，不另立判据） |
| 5.4 | 跨章六项 | 复用 check_cross_chapter（术语/数据矛盾/重复/难度/字数分配/图号连续） |
| 5.5 | 合稿可交付 | docx 可开（非 BadZipFile）；docx media 数 == 各章唯一图位对之和；各章净字数和 vs 总预算 ≤5% |

> 5.5 字数口径（装机实证）：合稿 md 直数 ≠ 各章净字数和（合稿删各章参考文献节、
> 追加全书节）。字数守恒锚定在**各章交付 md 净字数和**，合稿只验可开 + 图数。

## 6. 与单章流程的接缝

| 单章概念 | 全书层对应 |
|---|---|
| `progress.md`（单章段） | 「Progress · 全书」段 + 各章段并存 |
| 门禁 4（check_manuscript） | 5.3 逐章调用；5.1/5.2/5.4/5.5 为全书增量 |
| `check_cross_chapter.py` | 5.4 直接复用（B5b 扩到 6 项） |
| `build_manuscript.py`（章 docx） | `build_book.py`（书 docx），版式常量同源 TYPESET |
| W1（单章全流程） | **W5 全书工作流**：book init → BOOK_SPEC → 逐章 W1 → check_book → build_book → BOOK_DELIVER |
