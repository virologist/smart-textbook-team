#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler.py — 章节级并行调度器（2026-11-04 诊断 H5 落地 · P1 批次）

问题背景
========
`scripts/progress.py` 的 `PHASE_ORDER` 是线性枚举（23 相位 = 5 个 BOOK_* 全书相位
+ 18 个章域相位），因此**跨相位并行度实测 = 1**——整本教材的实际执行形态是
「7 步串行链跑 23 遍」。而教材生产是典型的 embarrassingly parallel：
各章写独立路径（`章节/{ch##}/`），彼此无数据依赖 → 可以 Fan-out。

更具体地说，原诊断报告里 H5 的严重度定级依赖一个前提假设：
「并行度 = 1 指跨相位串行，不指同一相位内的分支数 ≤5」。本脚本把这条假设
变成可执行的调度层：读 book-spec + chapter-map + progress.md，算出
「**下一批可以同时开跑的章节**」，并给出每批的 spawn 指令。

并行度怎么定（用户 Q2 的落地）
==============================
用户明确：**「受限于 API 速率还是 token 预算」** —— 这意味着并行度**不是**
一个可以写死的常量，而是**运行时由预算与速率共同决定**的动态量。因此：

  · 本脚本**不内置任何默认并发数字**。未显式给 `--max-concurrency` 时，
    并发上限 = `min(可并行章节数, 速率上限, token 预算上限)`，
    其中后两者从环境变量/黑板读；都读不到 → **退化为 1（保守串行）**
    并在输出中明确告警「未获预算授权，已退化为串行」。
  · `--max-concurrency` 可以显式覆盖，但**上限受 `--branch-cap` 约束**
    （协议 SSOT：`skills/multi-agent-patterns` §模式五「分支数 ≤ 5」）。
    这个 5 是**协议硬上限**（不是假设），与 Q2 的动态并发不冲突：
    前者管「单批次内分支数」，后者管「批次大小 / 跨章并发」。

  · token 预算：`--token-budget`（本批总预算）或读黑板 `budget.tokens_limit`。
    每章预估消耗 = 书稿字数预算换算（见 `_estimate_chapter_tokens`），
    超预算的章节**不排进本批**，顺延到下一批（而不是截断执行）。

退出码
======
  0  调度计划生成成功
  1  调度前置不满足（如依赖成环 / 章清单缺失）—— 有问题可读
  2  输入缺失（work-root 不存在 / book-spec 不存在）
  3  预算或速率授权不可用且无法退化为安全模式

用法
====
  # 看当前可并行批次（人类可读）
  python3 scripts/scheduler.py --work-root "$WORK_ROOT" plan

  # 机器可读（供编排器消费）
  python3 scripts/scheduler.py --work-root "$WORK_ROOT" plan --json

  # 显式给并发上限（受 branch-cap 约束）
  python3 scripts/scheduler.py --work-root "$WORK_ROOT" plan --max-concurrency 3

  # 从环境变量取预算（推荐：跟随真实速率/预算）
  STB_MAX_CONCURRENCY=3 STB_TOKEN_BUDGET=400000 \\
      python3 scripts/scheduler.py --work-root "$WORK_ROOT" plan

  # 节级拓扑波次（Batch 4 升级 B；口径 SSOT = pipeline §搭接并行协议之升级 B）
  python3 scripts/scheduler.py --work-root "$WORK_ROOT" plan --mode sections \
      --chapter ch01 --json

节级模式（--mode sections）
==========================
读 `章节/{ch##}/chapter_design.md` 的 §C.1 机器可读依赖表，按 strong-dep 做
Kahn 拓扑分波，波内节并行、波间串行；并发度**复用章级 Q2 四级授权**
（`resolve_concurrency`），不另立一套默认值。token 预算不足时该波次
自动降为串行（优雅退化，不是失败），并在 `concurrency_notes` 留痕。
§C.1 格式与判据见 `skills/textbook-pipeline-workflow/SKILL.md` §节级并行调度。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 相位枚举 SSOT = progress.py PHASE_ORDER（与 check_phase_consistency 同源，
# 避免本脚本另立一份枚举造成漂移）
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from progress import PHASE_ORDER  # type: ignore
except Exception:  # pragma: no cover - progress.py 缺失时降级
    PHASE_ORDER = ['DELIVER']

# ── 协议硬上限（SSOT = skills/multi-agent-patterns §模式五「分支数 ≤ 5」）──
# 注意：这是**单批次内 fan-out 分支数**的协议上限，与「跨章并发批次大小」
# 是两个量纲。Q2 的动态并发不能突破它，但也不受它单独限制。
BRANCH_CAP = 5

# ── 环境变量（速率/预算授权入口）────────────────────────────────────────
ENV_MAX_CONCURRENCY = 'STB_MAX_CONCURRENCY'
ENV_TOKEN_BUDGET = 'STB_TOKEN_BUDGET'
ENV_RATE_LIMIT = 'STB_RATE_LIMIT'

# ── token 估算系数（每汉字 token 数）────────────────────────────────────
# 实测量级参考：中文技术文本 1 汉字 ≈ 1.0~1.5 token。
# 这是**估算**，用于排批（判断一批装不装得下预算），不是计费依据。
TOKENS_PER_HANZI = 1.2
# 每章固定开销（系统提示 + 技能预加载 + 装配文案）
CHAPTER_FIXED_TOKENS = 25_000

BOOK_SPEC_REL = ('运行态', 'book-spec.md')
CHAPTER_MAP_REL = ('章节', '_book', 'chapter-map.md')
PROGRESS_REL = ('运行态', 'progress.md')

# 章节域相位（与 progress.py PHASE_ORDER 的章域部分一致）
# 注：这里只列**章内可并行/可判定**的相位，用于把章的进度映射到调度决策。
DONE_STATUSES = ('DONE', 'SKIPPED')

# ── 升级 B：节级依赖表（chapter_design §C.1）─────────────────────────────
# 与 B3 的知识块锚同一风格：HTML 注释包裹的机器可读表格，避免与 §C 正文表格混淆。
SECTION_DEPS_BEGIN = '<!-- SECTION_DEPS_BEGIN -->'
SECTION_DEPS_END = '<!-- SECTION_DEPS_END -->'
SECTION_DEPS_RE = re.compile(
    re.escape(SECTION_DEPS_BEGIN) + r'(.*?)' + re.escape(SECTION_DEPS_END), re.S)
SECTION_DEPS_HEADER = ('节号', 'strong-dep', 'no-dep', '关键术语', '字数目标')
NO_DEP_TOKENS = {'', '—', '-', '－', '无', 'none', 'n/a', 'N/A'}
SECTION_NO_RE = re.compile(r'^\d+(?:\.\d+)+$')
CHAPTER_RE = re.compile(r'^ch\d{2}$')


def _log(msg: str, level: str = 'INFO') -> None:
    print(f'[{level}] {msg}', file=sys.stderr)


# ── 读取层 ───────────────────────────────────────────────────────────────

def load_book_spec(work_root: Path) -> list[dict]:
    """读 book-spec.md 的 chapters 列表 → [{id, word_budget, difficulty, domain}]。

    与 check_cross_chapter.load_book_spec 同源正则（避免两处解析漂移）。
    """
    spec = work_root.joinpath(*BOOK_SPEC_REL)
    if not spec.is_file():
        return []
    txt = spec.read_text(encoding='utf-8')
    rows = []
    for m in re.finditer(
        r'^\s*- id: (\S+)\n\s*word_budget: (\d+)\n\s*difficulty: (\S*)\n\s*domain: (.*)$',
        txt, re.M):
        rows.append({'id': m.group(1), 'word_budget': int(m.group(2)),
                     'difficulty': m.group(3).strip(), 'domain': m.group(4).strip()})
    return rows


def load_chapter_map(work_root: Path) -> dict[str, list[str]]:
    """读 chapter-map.md → {章: [依赖章...]}。无文件返回 {}。

    表格式（BOOK_SPEC 产物，主理人手填）：| 章 | 知识域 | 成员 | 依赖章 |
    兼容 3 列（章 | 知识域 | 依赖章）。
    """
    cmap = work_root.joinpath(*CHAPTER_MAP_REL)
    if not cmap.is_file():
        return {}
    out: dict[str, list[str]] = {}
    for line in cmap.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|') or '---' in line:
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 3 or cells[0] in ('章', '章节', ''):
            continue
        dep_cell = cells[3] if len(cells) >= 4 else cells[2]
        deps = [d.strip() for d in re.split(r'[、，,]', dep_cell)
                if d.strip() and d.strip() not in ('—', '-', '无', '')]
        out[cells[0]] = deps
    return out


def load_chapter_phases(work_root: Path) -> dict[str, list[tuple[str, str]]]:
    """读 progress.md 各章段 → {章: [(phase, status), ...]}（按文件序）。"""
    prog = work_root.joinpath(*PROGRESS_REL)
    if not prog.is_file():
        return {}
    txt = prog.read_text(encoding='utf-8')
    out: dict[str, list[tuple[str, str]]] = {}
    for m in re.finditer(r'^# Progress · (\S+)\s*\n(.*?)(?=^# Progress · |\Z)',
                         txt, re.S | re.M):
        name = m.group(1)
        if name == '全书':
            continue
        rows = re.findall(r'^\| ([A-Z][A-Z0-9-]*) \| ([A-Z_]+) \|', m.group(2), re.M)
        out[name] = rows
    return out


def _furthest_phase(rows: list[tuple[str, str]]) -> tuple[str, str]:
    """取该章**最远**的相位与其状态（按 PHASE_ORDER 序，非文件行序）。

    rows = [(phase, status), ...]（来自 progress.md 章段表，按文件序）。
    返回 (phase, status)；无记录返回 ('', '')。
    """
    if not rows:
        return '', ''
    idx = {p: i for i, p in enumerate(PHASE_ORDER)}
    best = max(rows, key=lambda r: idx.get(r[0], -1))
    return best[0], best[1]


def has_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """DFS 三色判环。返回环上的节点列表；无环返回 None。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in edges}
    for vs in edges.values():
        for v in vs:
            color.setdefault(v, WHITE)
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        stack.append(u)
        for v in edges.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return stack[stack.index(v):] + [v]
            if color.get(v, WHITE) == WHITE:
                r = dfs(v)
                if r:
                    return r
        stack.pop()
        color[u] = BLACK
        return None

    for n in list(color):
        if color[n] == WHITE:
            r = dfs(n)
            if r:
                return r
    return None


# ── 预算/速率授权（Q2 落地核心）─────────────────────────────────────────

def resolve_concurrency(ready_count: int, max_concurrency: int | None,
                        rate_limit: int | None) -> tuple[int, list[str]]:
    """决定本批并发上限。返回 (并发数, 说明列表)。

    优先级（Q2：**并发度由 API 速率 / token 预算动态决定，不写死**）：
      1. 显式 --max-concurrency（人工授权）
      2. 环境变量 STB_MAX_CONCURRENCY
      3. 环境变量 STB_RATE_LIMIT（速率上限折算）
      4. 都没有 → 退化为 1（保守串行）+ 明确告警

    无论来源如何，最终并发数都受：可并行章节数、协议分支上限 BRANCH_CAP 约束。
    """
    notes: list[str] = []
    chosen: int | None = None
    source = ''

    if max_concurrency is not None:
        chosen, source = max_concurrency, '--max-concurrency'
    elif os.environ.get(ENV_MAX_CONCURRENCY):
        try:
            chosen = int(os.environ[ENV_MAX_CONCURRENCY])
            source = f'${ENV_MAX_CONCURRENCY}'
        except ValueError:
            notes.append(f'${ENV_MAX_CONCURRENCY} 非整数，忽略')
    elif rate_limit is not None:
        chosen, source = rate_limit, f'${ENV_RATE_LIMIT}'
    elif os.environ.get(ENV_RATE_LIMIT):
        try:
            chosen = int(os.environ[ENV_RATE_LIMIT])
            source = f'${ENV_RATE_LIMIT}'
        except ValueError:
            notes.append(f'${ENV_RATE_LIMIT} 非整数，忽略')

    if chosen is None:
        notes.append(
            '未获并发授权（未给 --max-concurrency，且 '
            f'{ENV_MAX_CONCURRENCY}/{ENV_RATE_LIMIT} 均未设置）'
            '→ **退化为串行（并发=1）**。这是 Q2 的保守默认，不是写死的策略。')
        chosen = 1
    else:
        notes.append(f'并发上限来源={source}，值={chosen}')

    if chosen < 1:
        notes.append(f'并发上限 {chosen} 非法（<1）→ 修正为 1')
        chosen = 1
    if chosen > BRANCH_CAP:
        notes.append(f'并发上限 {chosen} 超出协议分支硬上限 {BRANCH_CAP}'
                     f'（multi-agent-patterns §模式五）→ 收敛到 {BRANCH_CAP}')
        chosen = BRANCH_CAP
    if ready_count and chosen > ready_count:
        notes.append(f'并发上限 {chosen} > 可并行章节数 {ready_count} → 收敛到 {ready_count}')
        chosen = ready_count
    return chosen, notes


def resolve_token_budget(token_budget: int | None, work_root: Path) -> tuple[int | None, str]:
    """决定本批 token 预算上限。返回 (预算, 来源说明)。

    优先级：--token-budget > 环境变量 > 黑板 budget.tokens_limit > 无限制。
    「无限制」是合法的（用户 Q3：单章 token 不受限）——此时不按 token 排批。
    """
    if token_budget is not None:
        return token_budget, '--token-budget'
    env = os.environ.get(ENV_TOKEN_BUDGET)
    if env:
        try:
            return int(env), f'${ENV_TOKEN_BUDGET}'
        except ValueError:
            _log(f'{ENV_TOKEN_BUDGET} 非整数，忽略', 'WARN')
    bb = work_root / '运行态' / 'workflow-state.yaml'
    if bb.is_file():
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(bb.read_text(encoding='utf-8')) or {}
            lim = (data.get('budget') or {}).get('tokens_limit')
            if lim:
                return int(lim), '黑板 budget.tokens_limit'
        except Exception:
            pass
    return None, '无预算上限（用户 Q3：单章 token 不受限）'


def estimate_chapter_tokens(word_budget: int) -> int:
    """估算单章 token 消耗（字数预算 × 系数 + 固定开销）。仅用于排批。"""
    return int(word_budget * TOKENS_PER_HANZI) + CHAPTER_FIXED_TOKENS


# ── 调度核心 ────────────────────────────────────────────────────────────

def compute_plan(work_root: Path, max_concurrency: int | None = None,
                 token_budget: int | None = None,
                 rate_limit: int | None = None) -> dict:
    """算出下一批可并行章节。返回结构化计划。"""
    spec = load_book_spec(work_root)
    if not spec:
        return {
            'ok': False, 'reason': 'BOOK_SPEC_MISSING',
            'detail': f'未找到 {"/".join(BOOK_SPEC_REL)}——先执行 '
                      f'`progress.py book init --textbook ... --chapters ...`',
            'batches': [],
        }

    chapter_ids = [r['id'] for r in spec]
    deps_map = load_chapter_map(work_root)
    phases = load_chapter_phases(work_root)

    # 依赖成环 → 不可调度（这是硬前置，不是可恢复错误）
    cycle = has_cycle(deps_map)
    if cycle:
        return {
            'ok': False, 'reason': 'DEPENDENCY_CYCLE',
            'detail': '章节依赖成环：' + ' → '.join(cycle),
            'batches': [],
        }

    budget, budget_src = resolve_token_budget(token_budget, work_root)

    # ── 逐章判定「是否已完成 / 是否可开跑」────────────────────────────
    # 「最新相位」按 SSOT（progress.py PHASE_ORDER）取**最远**相位，
    # 而不是 progress.md 里的最后一行——后者是插入序而非相位序，
    # 回填旧相位行会让末行不代表进度（实测：回填 PRODUCE-R1 后末行变 PRODUCE-R1，
    # 而实际已到 DELIVER → 该章被误判为未完成）。
    chapters: list[dict] = []
    for row in spec:
        cid = row['id']
        deps = deps_map.get(cid, [])
        rows = phases.get(cid, [])
        done_phases = [p for p, s in rows if s in DONE_STATUSES]
        latest, latest_status = _furthest_phase(rows)
        chapters.append({
            'id': cid,
            'domain': row['domain'],
            'word_budget': row['word_budget'],
            'estimated_tokens': estimate_chapter_tokens(row['word_budget']),
            'depends': deps,
            'done_phases': done_phases,
            'latest_phase': latest,
            'latest_status': latest_status,
            # 章完成 = 已到 DELIVER 且状态为 DONE/SKIPPED
            'completed': latest in ('DELIVER',) and latest_status in DONE_STATUSES,
            'state': 'PENDING',
        })

    # 依赖满足判定：依赖章必须**整章完成**（DELIVER+DONE）才算满足。
    # 2026-11-04 实测修正：此前用「依赖章有任一相位 DONE」作满足条件，
    # 导致 ch04（依赖 ch02+ch03）在 ch02 只完成 PRODUCE-R1 时就被放行——
    # 下游会拿到**未完成的**上游内容。
    completed_ids = {c['id'] for c in chapters if c['completed']}
    for c in chapters:
        deps_pending = [d for d in c['depends'] if d not in completed_ids]
        deps_unknown = [d for d in c['depends'] if d not in chapter_ids]
        c['deps_pending'] = deps_pending
        c['deps_unknown'] = deps_unknown
        c['state'] = ('READY' if not deps_pending and not deps_unknown
                      and not c['completed'] else
                      'COMPLETED' if c['completed'] else 'WAITING')

    ready = [c for c in chapters if c['state'] == 'READY' and not c['completed']]
    waiting = [c for c in chapters if c['state'] == 'WAITING']
    completed = [c for c in chapters if c['completed']]

    concurrency, notes = resolve_concurrency(len(ready), max_concurrency, rate_limit)

    # ── 按预算切批 ─────────────────────────────────────────────────────
    batches: list[dict] = []
    cur: list[dict] = []
    cur_tokens = 0
    for c in ready:
        need = c['estimated_tokens']
        if budget is not None and cur and (cur_tokens + need) > budget:
            batches.append({'chapters': cur, 'estimated_tokens': cur_tokens})
            cur, cur_tokens = [], 0
        cur.append(c)
        cur_tokens += need
        if len(cur) >= concurrency:
            batches.append({'chapters': cur, 'estimated_tokens': cur_tokens})
            cur, cur_tokens = [], 0
    if cur:
        batches.append({'chapters': cur, 'estimated_tokens': cur_tokens})

    # ── 为每批生成 spawn 指令 ──────────────────────────────────────────
    for i, b in enumerate(batches, 1):
        b['batch_id'] = i
        b['tasks'] = []
        for c in b['chapters']:
            phase = c['latest_phase'] or 'BOOTSTRAP'
            b['tasks'].append({
                'chapter': c['id'],
                'phase': phase,
                'task_id': f"{c['id']}-{phase}",
                'correlation_id': c['id'],
                'depends': c['depends'],
                'target_dir': f"章节/{c['id']}/",
                'note': '各章写独立路径 → 满足 path-ownership §1.4 并行前置检查',
            })

    return {
        'ok': True,
        'reason': None,
        'concurrency': concurrency,
        'concurrency_notes': notes,
        'token_budget': budget,
        'token_budget_source': budget_src,
        'branch_cap': BRANCH_CAP,
        'chapters': chapters,
        'ready': [c['id'] for c in ready],
        'waiting': [{'id': c['id'], 'deps_pending': c['deps_pending'],
                     'deps_unknown': c['deps_unknown']} for c in waiting],
        'completed': [c['id'] for c in completed],
        'batches': batches,
    }


# ── 升级 B：节级拓扑波次调度（诊断 §3.2 升级 B / Q2）─────────────────────

def _split_cells(line: str) -> list[str]:
    """拆 Markdown 表格行（与 parallel_gate 的锚表同一口径）。"""
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _parse_bool_dep(raw: str) -> bool | None:
    """no-dep 列归一；无法判定的值返回 None（由调用方报输入错误，不猜）。"""
    v = raw.strip().lower()
    if v in ('yes', 'true', '1', 'y', '可并行', '无依赖'):
        return True
    if v in ('no', 'false', '0', 'n', '不可并行'):
        return False
    return None


def load_section_deps(work_root: Path, chapter: str) -> tuple[list[dict], str | None]:
    """读 chapter_design §C.1 依赖表。返回 (行列表, 错误原因)。

    行 = {节号, strong_dep, no_dep, terms, word_budget, estimated_tokens}。
    **任何解析歧义都返回错误**，绝不静默当「无依赖」放行——那会把有强依赖的节
    误排进同一波次，直接违反升级 B 的术语一致性保障。
    """
    design = work_root / '章节' / chapter / 'chapter_design.md'
    if not design.is_file():
        return [], f'教学设计不存在: {design}'
    try:
        text = design.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as e:
        return [], f'教学设计无法读取: {design}（{e}）'
    m = SECTION_DEPS_RE.search(text)
    if not m:
        return [], (f'未找到 §C.1 节依赖表（须含 {SECTION_DEPS_BEGIN} … '
                    f'{SECTION_DEPS_END}）——不得按「全无依赖」默认放行')
    lines = [ln.strip() for ln in m.group(1).splitlines()
             if ln.strip().startswith('|')]
    if len(lines) < 2:
        return [], '§C.1 表不足 2 行（表头 + 至少 1 个节）'
    header = _split_cells(lines[0])
    if tuple(header) != SECTION_DEPS_HEADER:
        return [], (f'§C.1 表头不符：期望 {list(SECTION_DEPS_HEADER)}，'
                    f'实为 {header}（列顺序固定，不猜列义）')
    body = lines[1:]
    if body and all(re.fullmatch(r':?-{3,}:?', c or '') for c in _split_cells(body[0])):
        body = body[1:]
    if not body:
        return [], '§C.1 表无数据行（空表不得判 PASS）'

    rows: list[dict] = []
    seen: set[str] = set()
    for lineno, line in enumerate(body, 1):
        cells = _split_cells(line)
        if len(cells) != len(SECTION_DEPS_HEADER):
            return [], (f'§C.1 第 {lineno} 行有 {len(cells)} 列，'
                        f'表头 {len(SECTION_DEPS_HEADER)} 列——列错位禁止放行')
        sec, strong_raw, nodep_raw, terms_raw, words_raw = cells
        if not SECTION_NO_RE.fullmatch(sec):
            return [], f'§C.1 第 {lineno} 行节号非法: {sec!r}（须如 1.1 / 3.2.1）'
        if sec in seen:
            return [], f'§C.1 节号重复: {sec}（同一节两行无法定波次）'
        seen.add(sec)
        nodep = _parse_bool_dep(nodep_raw)
        if nodep is None:
            return [], (f'§C.1 第 {lineno} 行 no-dep 值无法判定: '
                        f'{nodep_raw!r}（合法：yes/no/true/false/可并行/不可并行）')
        deps = [d.strip() for d in re.split(r'[、，,;；]', strong_raw)
                if d.strip() and d.strip() not in NO_DEP_TOKENS]
        for d in deps:
            if not SECTION_NO_RE.fullmatch(d):
                return [], f'§C.1 第 {lineno} 行 strong-dep 节号非法: {d!r}'
        if deps and nodep:
            return [], (f'§C.1 第 {lineno} 行矛盾：{sec} 有 strong-dep '
                        f'{deps} 却标 no-dep=yes（可并行）')
        terms = [t.strip() for t in re.split(r'[、，,;；]', terms_raw)
                 if t.strip() and t.strip() not in NO_DEP_TOKENS]
        try:
            words = int(words_raw)
        except ValueError:
            return [], f'§C.1 第 {lineno} 行字数目标非整数: {words_raw!r}'
        if words <= 0:
            return [], f'§C.1 第 {lineno} 行字数目标须 >0，实为 {words}'
        rows.append({
            '节号': sec, 'strong_dep': deps, 'no_dep': nodep,
            'terms': terms, 'word_budget': words,
            'estimated_tokens': estimate_chapter_tokens(words),
        })
    return rows, None


def section_waves(rows: list[dict]) -> tuple[list[list[dict]] | None, list[str]]:
    """Kahn 拓扑分波：波内无强依赖（可并行），波间满足依赖先后。

    返回 (波次列表, 成环节号列表)；无环时后者为空。
    """
    remaining = {r['节号'] for r in rows}
    waves: list[list[dict]] = []
    while remaining:
        wave = [r for r in rows
                if r['节号'] in remaining
                and all(d not in remaining for d in r['strong_dep'])]
        if not wave:
            return None, sorted(remaining)
        waves.append(wave)
        remaining -= {r['节号'] for r in wave}
    return waves, []


def compute_section_plan(work_root: Path, chapter: str,
                         max_concurrency: int | None = None,
                         token_budget: int | None = None,
                         rate_limit: int | None = None) -> dict:
    """节级调度计划：拓扑波次 + Q2 四级并发度 + 预算降级串行。"""
    rows, err = load_section_deps(work_root, chapter)
    if err:
        return {'ok': False, 'mode': 'sections', 'reason': 'SECTION_DEPS_INVALID',
                'detail': err, 'waves': []}

    ids = {r['节号'] for r in rows}
    for r in rows:
        unknown = [d for d in r['strong_dep'] if d not in ids]
        if unknown:
            return {'ok': False, 'mode': 'sections',
                    'reason': 'SECTION_DEPS_INVALID',
                    'detail': f"{r['节号']} 的 strong-dep 引用了不在 §C.1 表内的节: {unknown}",
                    'waves': []}

    waves, cycle = section_waves(rows)
    if cycle:
        return {'ok': False, 'mode': 'sections',
                'reason': 'SECTION_DEPENDENCY_CYCLE',
                'detail': '节依赖成环（无法分波）: ' + ', '.join(cycle), 'waves': []}

    budget, budget_src = resolve_token_budget(token_budget, work_root)
    max_wave = max((len(w) for w in waves or []), default=0)
    # 复用章级 Q2 四级授权，不另立默认值（诊断「沿用 Q2 现有 4 级决策」）
    concurrency, notes = resolve_concurrency(max_wave, max_concurrency, rate_limit)
    by_id = {r['节号']: r for r in rows}

    out_waves: list[dict] = []
    for i, wave in enumerate(waves or [], 1):
        est = sum(r['estimated_tokens'] for r in wave)
        wave_conc = min(concurrency, len(wave))
        degraded = False
        if budget is not None and est > budget:
            wave_conc = 1
            degraded = True
            notes.append(f'第 {i} 波估 {est} tok > 预算 {budget}（{budget_src}）'
                         f' ⇒ 降为串行（优雅退化，不截断执行）')
        tasks = []
        for r in wave:
            # strong-dep 节的关键术语必须已在上游定义；派单时注入给 writer
            required_terms = sorted({t for d in r['strong_dep']
                                     for t in by_id[d]['terms']})
            tasks.append({
                '节号': r['节号'],
                'chapter': chapter,
                'phase': 'PRODUCE-R1',
                'task_id': f"{chapter}-PRODUCE-R1-节{r['节号']}",
                'correlation_id': chapter,
                'must_produce': f"章节/{chapter}/sections/{r['节号']}.md",
                'strong_dep': r['strong_dep'],
                'required_terms': required_terms,
                'word_budget': r['word_budget'],
                'estimated_tokens': r['estimated_tokens'],
                'note': '每节写独立文件 → path-ownership §1.4 允许波内并行；'
                        'required_terms 由上游 §C.1 注入，writer 不得自行定义',
            })
        out_waves.append({
            'wave_id': i, 'sections': [r['节号'] for r in wave],
            'concurrency': wave_conc, 'estimated_tokens': est,
            'budget_degraded': degraded, 'tasks': tasks,
        })

    return {
        'ok': True, 'mode': 'sections', 'chapter': chapter,
        'reason': None,
        'concurrency': concurrency, 'concurrency_notes': notes,
        'token_budget': budget, 'token_budget_source': budget_src,
        'branch_cap': BRANCH_CAP,
        'sections': rows, 'waves': out_waves,
    }


def render_sections(plan: dict) -> str:
    """节级计划的人类可读渲染。"""
    lines: list[str] = []
    if not plan.get('ok'):
        lines.append(f'[FAIL] 节级调度前置不满足：{plan.get("reason")}')
        lines.append(f'  {plan.get("detail")}')
        return '\n'.join(lines)
    lines.append(f'═══ 节级并行调度计划 · {plan["chapter"]} ═══')
    lines.append(f'并发上限 = {plan["concurrency"]}'
                 f'（协议分支硬上限 {plan["branch_cap"]}）')
    for n in plan['concurrency_notes']:
        lines.append(f'  · {n}')
    lines.append(f'token 预算 = {plan["token_budget"]}'
                 f'（来源：{plan["token_budget_source"]}）')
    for w in plan['waves']:
        tag = ' · 预算降级串行' if w['budget_degraded'] else ''
        lines.append(f'── 第 {w["wave_id"]} 波（{len(w["sections"])} 节 / '
                     f'并发 {w["concurrency"]} / 估 {w["estimated_tokens"]} tok）{tag} ──')
        for t in w['tasks']:
            terms = ('术语=' + ','.join(t['required_terms'])
                     if t['required_terms'] else '术语=—')
            lines.append(f'  spawn {t["task_id"]:<30} → {t["must_produce"]}  {terms}')
    return '\n'.join(lines)


def render(plan: dict) -> str:
    """人类可读渲染。"""
    lines: list[str] = []
    if not plan.get('ok'):
        lines.append(f'[FAIL] 调度前置不满足：{plan.get("reason")}')
        lines.append(f'  {plan.get("detail")}')
        return '\n'.join(lines)

    lines.append('═══ 章节级并行调度计划 ═══')
    lines.append(f'并发上限 = {plan["concurrency"]}'
                 f'（协议分支硬上限 {plan["branch_cap"]}）')
    for n in plan['concurrency_notes']:
        lines.append(f'  · {n}')
    lines.append(f'token 预算 = {plan["token_budget"]}（来源：{plan["token_budget_source"]}）')

    lines.append('')
    lines.append('── 章状态 ──')
    for c in plan['chapters']:
        mark = {'READY': '○可跑', 'WAITING': '·等待',
                'COMPLETED': '●已完成'}.get(c['state'], '?')
        extra = ''
        if c['deps_pending']:
            extra = f'（待依赖 {", ".join(c["deps_pending"])}）'
        if c['deps_unknown']:
            extra = f'（依赖章不在清单：{", ".join(c["deps_unknown"])}）'
        if c['completed']:
            mark = '●已完成'
        lines.append(f'  {mark} {c["id"]:<8} {c["latest_phase"] or "-":<14} '
                     f'估 {c["estimated_tokens"]:>7d} tok  {c["domain"]}{extra}')

    if plan['waiting']:
        lines.append('')
        lines.append('── 阻塞在依赖上的章 ──')
        for w in plan['waiting']:
            lines.append(f'  {w["id"]}: 待 {", ".join(w["deps_pending"]) or "-"}'
                         + (f' 未知依赖 {", ".join(w["deps_unknown"])}'
                            if w['deps_unknown'] else ''))

    lines.append('')
    if not plan['batches']:
        lines.append('（无可并行批次：所有章已完成或均在等待依赖）')
    for b in plan['batches']:
        ids = ', '.join(c['id'] for c in b['chapters'])
        lines.append(f'── 第 {b["batch_id"]} 批（{len(b["chapters"])} 章并行，'
                     f'估 {b["estimated_tokens"]} tok）──')
        lines.append(f'  章：{ids}')
        for t in b['tasks']:
            lines.append(f'  spawn {t["correlation_id"]:<8} phase={t["phase"]:<14} '
                         f'task_id={t["task_id"]:<24} 路径={t["target_dir"]}')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description='scheduler — 章节级并行调度器（并发度由速率/token 预算动态决定）')
    ap.add_argument('--work-root', required=True)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_plan = sub.add_parser('plan', help='生成下一批可并行章节的调度计划')
    p_plan.add_argument('--max-concurrency', type=int, default=None,
                        help='显式并发上限（仍受协议分支硬上限 5 约束）')
    p_plan.add_argument('--token-budget', type=int, default=None,
                        help='本批 token 预算上限（超出则顺延到下一批，不截断执行）')
    p_plan.add_argument('--rate-limit', type=int, default=None,
                        help='API 速率上限（并发上限来源之一）')
    p_plan.add_argument('--mode', choices=['chapters', 'sections'], default='chapters',
                        help='chapters=章级批次（默认，兼容既有调用）；sections=节级拓扑波次（升级 B）')
    p_plan.add_argument('--chapter', default='',
                        help='--mode sections 时必填，如 ch01')
    p_plan.add_argument('--json', action='store_true', help='以 JSON 输出')

    args = ap.parse_args()
    wr = Path(args.work_root).expanduser().resolve()
    if not wr.is_dir():
        print(f'ERROR  WORK_ROOT 不存在: {wr}', file=sys.stderr)
        return 2

    if args.cmd == 'plan':
        if args.mode == 'sections':
            if not CHAPTER_RE.fullmatch(args.chapter or ''):
                print(f'[ERROR] --mode sections 必须给合法 --chapter（ch##），'
                      f'实为 {args.chapter!r}', file=sys.stderr)
                return 2
            plan = compute_section_plan(wr, args.chapter,
                                        max_concurrency=args.max_concurrency,
                                        token_budget=args.token_budget,
                                        rate_limit=args.rate_limit)
            if args.json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print(render_sections(plan))
            if not plan.get('ok'):
                # 输入缺失/格式非法 = 2；依赖成环 = 1（与章级 DEPENDENCY_CYCLE 同口径）
                return 2 if plan.get('reason') == 'SECTION_DEPS_INVALID' else 1
            return 0

        plan = compute_plan(wr, max_concurrency=args.max_concurrency,
                            token_budget=args.token_budget,
                            rate_limit=args.rate_limit)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(render(plan))
        if not plan.get('ok'):
            # 退出码严格对齐文档（§退出码）：
            #   1 = 调度前置不满足（依赖成环 / 章清单缺失等可恢复问题）
            #   2 = 输入缺失（work-root / book-spec 不存在）
            # 此前两者都返回 1 → 与文档不符（2026-11-04 P1-4 修正）。
            reason = plan.get('reason')
            if reason in ('BOOK_SPEC_MISSING', 'WORK_ROOT_MISSING'):
                return 2
            return 1
        return 0

    return 0


if __name__ == '__main__':
    sys.exit(main())
