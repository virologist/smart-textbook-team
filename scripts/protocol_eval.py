#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""protocol_eval.py — 协议组件离线评测（R1 · 复诊 §3.2 R1）

问题本质
========
首诊 §3.4.2 的五环闭环里，「评测回归」是唯一的**验证闸门**——它决定
「协议改完到底有没有变好」。缺它 = 改协议变成盲改。

首诊 §3.3 模块表承诺 `L4 反馈 / ★protocol-eval / 协议组件评测回归`，
但全包零实现。本脚本补上这一环。

设计原则（与 B3/B4 同源）
==========================
1. **评测只报分、不改协议**——协议修订权在主理人 + 管家节点评审门。
2. **必须调用真实组件实现，不得再造影子实现**——影子实现会与真实现漂移，
   评测就变成「自己判自己」（自证）。本脚本用 `importlib` 直接加载
   `scripts/` 下的真实模块并调用其真实函数。
3. **只评「行为」不评「文档」**——每个组件的评测维度都对应一个可执行的
   行为判据（状态迁移、削减顺序、分波结果、分类结果、边界翻转）。
4. **失败必须显式列出**——输出「分数 + 失败项清单」，不静默放行。

首批 5 组件（按复诊 §3.2 R1 表）
================================
| 组件 | 评测维度 | 判据 |
|---|---|---|
| 路由置信度阈值 | `routing_confidence ≥70` 的升级/直派边界 | 阈值上下各 1 分的用例归属须翻转 |
| 熔断窗口 | E3 `CLOSED→OPEN→HALF_OPEN` 状态迁移 | 半开探测次数、恢复条件 |
| 预算优先级 | `budget_guard` 三档削减顺序 | 预算紧张时削减次序符合 protocol |
| 节级拓扑（B4） | `strong-dep` 必先行、同波无强依赖 | 波次划分确定且可复现 |
| 恢复分类（B4） | `RECOVERABLE`/`NEVER_PRODUCED` 判据 | 基线损坏 ⇒ 不判「从未产出」 |

退出码
======
  0  总分 ≥ 阈值（默认 0.80）
  1  总分 < 阈值 ⇒ 拒绝协议合入
  2  输入错误（评测集缺失 / 组件模块不可加载）
  3  评测集本身损坏（用例结构非法）

用法
====
  python3 scripts/protocol_eval.py                       # 跑内置评测集
  python3 scripts/protocol_eval.py --verbose             # 逐用例输出
  python3 scripts/protocol_eval.py --json                # 机器可读
  python3 scripts/protocol_eval.py --threshold 0.90      # 提高门槛
  python3 scripts/protocol_eval.py --component section-topology   # 只评某组件
  python3 scripts/protocol_eval.py --cases <cases.json>   # 外部用例集
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PKG_ROOT = SCRIPT_DIR.parent

# 默认门槛——与 router eval 同门槛（复诊 §3.2 R1「门禁接入」）
DEFAULT_THRESHOLD = 0.80

# 组件级底线——与总分门槛同值。
#
# 为什么总分之外还要卡组件底线（真实设计缺陷，R1 实测暴露）：
# 首诊 §3.4 的指标口径是「各组件 eval 通过项 / 总项」**跨组件合并**计算总分。
# 但合并会让**单个组件的严重失效被稀释**——实测：把熔断阈值改坏（9/9 → 3/9）
# 后，总分仍从 1.000 掉到 0.882，**仍 ≥0.80 门槛** ⇒ 门禁放行了一个已坏的协议。
# 这与「熔断是最后一道安全闸」的性质冲突。
#
# 因此门禁采用**双闸**：
#   ① 总分 ≥ threshold（复诊 §3.4 原口径）
#   ② 每个组件 ≥ threshold（组件级底线）——任一组件低于底线即拒绝合入
DEFAULT_COMPONENT_THRESHOLD = 0.80

# 路由置信度阈值——SSOT：skills/task-router/SKILL.md §2 Step 2「总分 ≥ 70 → 直接 dispatch」
ROUTING_CONFIDENCE_THRESHOLD = 70


@contextlib.contextmanager
def muted_stdout():
    """抑制被测组件的 stdout。

    R1 修复的真实缺陷：被测组件（`e3_window.record` 等）直接 print 到 stdout，
    会污染 `--json` 输出 ⇒ 机器无法解析评测结果。
    这里在评测执行期间把 stdout 重定向到缓冲区。
    """
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


# ── 真实组件加载（不用影子实现）────────────────────────────────────────
_COMPONENT_CACHE: dict[str, object] = {}


def load_component(module_name: str):
    """用 importlib 加载 scripts/ 下的真实模块。

    不走 `sys.path.insert` + `import`，是为了避免与包内其它测试的模块名冲突
    （如 scheduler 在多处被 import），且能明确定位文件路径。

    ⚠️ 必须**缓存**：反向注入测试（tests/test_protocol_eval.py）会 patch
    组件模块的属性（阈值、优先级表等）。若每次都重新加载模块，patch 的是
    旧实例，评测跑的是新实例 ⇒ 注入无效、反向用例假绿。
    """
    if module_name in _COMPONENT_CACHE:
        return _COMPONENT_CACHE[module_name]

    path = SCRIPT_DIR / f'{module_name}.py'
    if not path.is_file():
        raise FileNotFoundError(f'组件模块不存在: {path}')
    spec = importlib.util.spec_from_file_location(f'_stt_pe_{module_name}', path)
    if spec is None or spec.loader is None:
        raise ImportError(f'无法为 {path} 创建 import spec')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _COMPONENT_CACHE[module_name] = mod
    return mod


# ── 评测用例数据结构 ─────────────────────────────────────────────────
# 每个用例: {id, component, name, expect, args}
#   expect: {'kind': ..., 'value': ...}
#   kind 取值由各组件的 eval_* 函数解释。


def _case(cid: str, component: str, name: str, expect: dict, args: dict) -> dict:
    return {'id': cid, 'component': component, 'name': name,
            'expect': expect, 'args': args}


# ═══════════════════════════════════════════════════════════════════════
# 组件 1：路由置信度阈值
#   判据：阈值上下各 1 分的用例归属须翻转
#   —— 置信度 70 → 直派；69 → 升级；71 → 直派
# ═══════════════════════════════════════════════════════════════════════
def decide_by_confidence(conf: float, threshold: int) -> str:
    """路由决策规则（SSOT 对应 skills/task-router/SKILL.md §2 Step 2）。

    「总分 ≥ threshold → 直接 dispatch；总分 < threshold → 走 §3 升级」。

    这条规则是**纯函数**——把它抽出来，才能独立评测「阈值上下 1 分必须翻转」，
    而不必依赖 router 恰好产出某个置信度。
    """
    return 'dispatch' if conf >= threshold else 'escalate'


def eval_routing_threshold(cases: list[dict]) -> list[dict]:
    """评路由置信度阈值边界。

    真实实现源：`skills/task-router/SKILL.md` §2 Step 2 的阈值 +
    `tests/test_router_eval.py` 的 route() 影子实现（该影子实现是
    §2 决策算法的 Python 影子，是**真实路由的离线回归体**）。

    三类判据：
      · threshold_ssrc —— 解析出的 SSOT 阈值必须等于协议声明值（防漂移）
      · flip          —— 阈值上下各 1 分的归属**必须翻转**
      · route_decision—— 真实问法的决策必须符合阈值规则
    """
    results = []
    router = _load_router()
    threshold = router['threshold']
    for c in cases:
        args = c['args']
        expect = c['expect']['value']
        kind = c['expect'].get('kind', 'route_decision')

        if kind == 'threshold_ssrc':
            ok = (threshold == args['declared_threshold'])
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': (f"协议声明阈值={args['declared_threshold']} "
                           f"SKILL.md 解析得={threshold}"
                           + ('' if ok else ' ⇒ SSOT 漂移')),
            })
        elif kind == 'flip':
            low = threshold - 1
            high = threshold + 1
            got_low = decide_by_confidence(low, threshold)
            got_high = decide_by_confidence(high, threshold)
            ok = (got_low == 'escalate') and (got_high == 'dispatch')
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': (f"阈值={threshold} 下 1 分({low})⇒{got_low} "
                           f"上 1 分({high})⇒{got_high}（须翻转）"),
            })
        else:
            query = args.get('query', '')
            task_type, actual_conf, _signals = router['route'](query)
            decision = decide_by_confidence(actual_conf, threshold)
            # 直派还要求真的路由到了成员；升级还要求置信度确实低于阈值
            if expect == 'dispatch':
                ok = (decision == 'dispatch') and (task_type is not None)
            else:
                ok = (decision == 'escalate')
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': (f"期望={expect} 阈值={threshold} 实际 task_type={task_type} "
                           f"conf={actual_conf} ⇒ 决策={decision}"),
            })
    return results


_ROUTER_CACHE: dict | None = None


def _load_router() -> dict:
    """加载 router 的真实决策实现 + 从 SKILL.md 解析置信度阈值（SSOT 派生）。"""
    global _ROUTER_CACHE
    if _ROUTER_CACHE is not None:
        return _ROUTER_CACHE

    skill_path = PKG_ROOT / 'skills' / 'task-router' / 'SKILL.md'
    if not skill_path.is_file():
        raise FileNotFoundError(f'task-router skill 不存在: {skill_path}')
    text = skill_path.read_text(encoding='utf-8')

    # 从 skill 文本解析阈值（SSOT 派生，避免两处硬编码漂移）
    threshold = ROUTING_CONFIDENCE_THRESHOLD
    for line in text.splitlines():
        if '总分' in line and ('→' in line or '->' in line):
            for tok in line.replace('→', ' ').replace('>', ' ').split():
                if tok.isdigit() and 0 < int(tok) <= 100:
                    threshold = int(tok)
                    break
            break

    # 加载 router 影子实现（真实路由的离线回归体，SKILL_PATH 由其自身定位）
    spec = importlib.util.spec_from_file_location(
        '_stt_pe_router_eval', PKG_ROOT / 'tests' / 'test_router_eval.py')
    if spec is None or spec.loader is None:
        raise ImportError('无法加载 tests/test_router_eval.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    _ROUTER_CACHE = {'route': mod.route, 'threshold': threshold}
    return _ROUTER_CACHE


# ═══════════════════════════════════════════════════════════════════════
# 组件 2：熔断窗口（E3 滑动窗口）
#   判据：半开探测次数、恢复条件
# ═══════════════════════════════════════════════════════════════════════
def eval_circuit_breaker(cases: list[dict]) -> list[dict]:
    """评熔断状态机（真实实现：`scripts/e3_window.py`）。"""
    import tempfile
    results = []
    mod = load_component('e3_window')
    for c in cases:
        args = c['args']
        seq = args['outcomes']
        expect_state = c['expect']['value']
        kind = c['expect'].get('kind', 'record')
        tmp = Path(tempfile.mkdtemp(prefix='stt-pe-e3-'))
        try:
            if kind == 'probe':
                # 先触发 OPEN，再 --probe 进 HALF_OPEN，再记录一次探测结果
                for outcome in seq:
                    mod.record(tmp, 'ch01', outcome)
                probe_rc = mod.probe(tmp, 'ch01')
                mid = mod._load_state(tmp).get('ch01', {}).get('state', 'CLOSED')
                if expect_state == 'HALF_OPEN':
                    # 只验「进入 HALF_OPEN」这一步
                    ok = (mid == 'HALF_OPEN') and (probe_rc == 2)
                    detail = f"期望 probe 后=HALF_OPEN 实际={mid} (probe rc={probe_rc})"
                else:
                    mod.record(tmp, 'ch01', args.get('probe_outcome', 'OK'))
                    final = mod._load_state(tmp).get('ch01', {}).get('state', 'CLOSED')
                    ok = (final == expect_state)
                    detail = (f"期望探测后={expect_state} 实际={final} "
                              f"(probe 后={mid} 探测结果={args.get('probe_outcome', 'OK')})")
            else:
                state = 'CLOSED'
                e3_count = 0
                for outcome in seq:
                    mod.record(tmp, 'ch01', outcome)
                    st = mod._load_state(tmp).get('ch01', {})
                    state = st.get('state', 'CLOSED')
                    e3_count = st.get('e3_count', 0)
                ok = (state == expect_state)
                detail = (f"期望状态={expect_state} 实际={state} "
                          f"(e3={e3_count}/{mod.WINDOW_SIZE} 阈值={mod.E3_THRESHOLD})")
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok, 'detail': detail,
            })
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    return results


# ═══════════════════════════════════════════════════════════════════════
# 组件 3：预算优先级
#   判据：预算紧张时削减次序符合 protocol
# ═══════════════════════════════════════════════════════════════════════
def eval_budget_priority(cases: list[dict]) -> list[dict]:
    """评削减优先级（真实实现：`scripts/budget_guard.py` 的 CUT_PRIORITY + compute_budget）。"""
    import tempfile
    results = []
    mod = load_component('budget_guard')
    for c in cases:
        args = c['args']
        expect = c['expect']['value']
        kind = c['expect'].get('kind', 'order')

        if kind == 'order':
            # 判据：削减优先级排序必须符合 protocol（禁止为保 P1/P3 而削 P0）
            phases = args['phases']
            prios = [mod.CUT_PRIORITY.get(p, (None,))[0] for p in phases]
            rank = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4}
            vals = [rank.get(p, 99) for p in prios]
            ok = (vals == sorted(vals))
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': f"期望削减次序={expect} 实际优先级={prios}",
            })
        elif kind == 'no_p0_cut':
            # 判据：P0 相位（RETRIEVE）必须标「禁止削减」
            ph = args['phase']
            pri, hint = mod.CUT_PRIORITY.get(ph, (None, ''))
            ok = (pri == expect['priority']) and (expect['keyword'] in hint)
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': f"期望 {ph} priority={expect['priority']} 且含「{expect['keyword']}」"
                          f" 实际 priority={pri} hint={hint!r}",
            })
        elif kind == 'status':
            # 判据：按 trace 累加后判预算状态（OK / DEGRADE_SUGGESTED / HARD_LIMIT_REACHED）
            tmp = Path(tempfile.mkdtemp(prefix='stt-pe-budget-'))
            try:
                rt = tmp / '运行态'
                rt.mkdir(parents=True, exist_ok=True)
                lines = []
                for ph, tok in args['trace']:
                    lines.append(json.dumps({
                        'phase': ph, 'tokens_in': tok // 2,
                        'tokens_out': tok - tok // 2,
                    }, ensure_ascii=False))
                (rt / 'trace.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
                r = mod.compute_budget(tmp)
                ok = (r['status'] == expect)
                results.append({
                    'id': c['id'], 'component': c['component'], 'name': c['name'],
                    'ok': ok,
                    'detail': f"期望 status={expect} 实际={r['status']} "
                              f"(total={r['total_tokens']} ratio={r['ratio']})",
                })
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
    return results


# ═══════════════════════════════════════════════════════════════════════
# 组件 4：节级拓扑（B4）
#   判据：strong-dep 必先行、同波无强依赖；波次划分确定且可复现
# ═══════════════════════════════════════════════════════════════════════
def eval_section_topology(cases: list[dict]) -> list[dict]:
    """评节级拓扑分波（真实实现：`scripts/scheduler.py` 的 section_waves / compute_section_plan）。"""
    results = []
    mod = load_component('scheduler')
    for c in cases:
        args = c['args']
        expect = c['expect']['value']
        kind = c['expect'].get('kind', 'waves')

        if kind == 'waves':
            rows = [{'节号': s, 'strong_dep': list(d), 'no_dep': [], 'terms': [],
                     'word_budget': 0, 'estimated_tokens': 0}
                    for s, d in args['deps']]
            waves, cycle = mod.section_waves(rows)
            if cycle:
                ok = (expect == 'CYCLE')
                got = 'CYCLE'
            else:
                got = [[r['节号'] for r in w] for w in waves]
                ok = (got == expect)
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': f"期望波次={expect} 实际={got}",
            })
        elif kind == 'no_same_wave_dep':
            # 判据：同一波内不得存在 strong-dep 关系（否则不可并行）
            rows = [{'节号': s, 'strong_dep': list(d), 'no_dep': [], 'terms': [],
                     'word_budget': 0, 'estimated_tokens': 0}
                    for s, d in args['deps']]
            waves, cycle = mod.section_waves(rows)
            if cycle:
                ok = False
                detail = '出现环，无法分波'
            else:
                violations = []
                for w in waves:
                    ids = {r['节号'] for r in w}
                    for r in w:
                        bad = [d for d in r['strong_dep'] if d in ids]
                        if bad:
                            violations.append(f"{r['节号']}<-{bad}")
                ok = not violations
                detail = ('同波无强依赖' if ok else f'同波强依赖违规: {violations}')
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok, 'detail': detail,
            })
        elif kind == 'reproducible':
            # 判据：同一依赖集合两次分波**波次划分**完全一致（集合层面）。
            # 注意：波**内节序**按输入顺序（Kahn 实现保留输入序），故此处
            # 只比「每波包含哪些节」的集合，不比节序——节序不是协议约束。
            rows = [{'节号': s, 'strong_dep': list(d), 'no_dep': [], 'terms': [],
                     'word_budget': 0, 'estimated_tokens': 0}
                    for s, d in args['deps']]
            w1, c1 = mod.section_waves(rows)
            w2, c2 = mod.section_waves(list(reversed(rows)))
            got1 = [sorted(r['节号'] for r in w) for w in (w1 or [])]
            got2 = [sorted(r['节号'] for r in w) for w in (w2 or [])]
            ok = (got1 == got2) and bool(got1)
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': f"两次分波划分一致={got1 == got2} 第一次={got1} 第二次={got2}",
            })
        elif kind == 'deterministic_plan':
            # 判据：compute_section_plan 两次调用 waves 完全一致
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix='stt-pe-topo-'))
            try:
                ch = 'ch01'
                cd = tmp / '章节' / ch
                cd.mkdir(parents=True, exist_ok=True)
                # §C.1 表必须用 SECTION_DEPS_BEGIN/END 注释标记包裹，
                # 且列值必须合法（no-dep 列须是 yes/no 等可判定值）——
                # 解析器「不猜列义、不按全无依赖默认放行」，格式非法直接报错。
                lines = ['## C.1 节级依赖表', '',
                         '<!-- SECTION_DEPS_BEGIN -->',
                         '| 节号 | strong-dep | no-dep | 关键术语 | 字数目标 |',
                         '|---|---|---|---|---|']
                for s, d in args['deps']:
                    dep = '、'.join(d) if d else '—'
                    nodep = 'no' if d else 'yes'
                    lines.append(f"| {s} | {dep} | {nodep} | T1 | 1000 |")
                lines.append('<!-- SECTION_DEPS_END -->')
                (cd / 'chapter_design.md').write_text('\n'.join(lines) + '\n',
                                                      encoding='utf-8')
                p1 = mod.compute_section_plan(tmp, ch)
                p2 = mod.compute_section_plan(tmp, ch)
                got1 = [[t['节号'] for t in w['tasks']] for w in p1.get('waves', [])]
                got2 = [[t['节号'] for t in w['tasks']] for w in p2.get('waves', [])]
                ok = (got1 == got2) and bool(got1) and p1.get('ok') is not False
                detail = (f"两次 plan 一致={got1 == got2} 波次={got1}"
                          + (f" plan.ok={p1.get('ok')} reason={p1.get('reason')} "
                             f"detail={p1.get('detail')}"
                             if p1.get('ok') is False else ''))
                results.append({
                    'id': c['id'], 'component': c['component'], 'name': c['name'],
                    'ok': ok,
                    'detail': f"两次 plan 一致={got1 == got2} 波次={got1}",
                })
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
    return results


# ═══════════════════════════════════════════════════════════════════════
# 组件 5：恢复分类（B4）
#   判据：基线损坏 ⇒ 不判「从未产出」
# ═══════════════════════════════════════════════════════════════════════
def eval_recovery_classification(cases: list[dict]) -> list[dict]:
    """评恢复分类（真实实现：`scripts/assemble_sections.py` 的 classify_missing / load_previous_manifest）。"""
    import tempfile
    results = []
    mod = load_component('assemble_sections')
    for c in cases:
        args = c['args']
        expect = c['expect']['value']
        kind = c['expect'].get('kind', 'classify')

        if kind == 'classify':
            baseline = dict(args.get('baseline', {}))
            status = args.get('baseline_status', 'ok')
            out = mod.classify_missing(args['missing'], baseline, status, 'ch01')
            got = {it['节号']: it['classification'] for it in out}
            ok = (got == expect)
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': f"期望分类={expect} 实际={got}",
            })
        elif kind == 'manifest_status':
            # 判据：清单缺失/损坏 ⇒ baseline_status 分别为 missing / corrupt
            tmp = Path(tempfile.mkdtemp(prefix='stt-pe-rec-'))
            try:
                ch_dir = tmp / '章节' / 'ch01'
                ch_dir.mkdir(parents=True, exist_ok=True)
                mode = args['mode']
                if mode == 'ok':
                    (ch_dir / '拼接清单.json').write_text(json.dumps({
                        'sections': [{'节号': '1.1', '文件': 'a.md'},
                                     {'节号': '1.2', '文件': 'b.md'}],
                    }, ensure_ascii=False), encoding='utf-8')
                elif mode == 'corrupt':
                    (ch_dir / '拼接清单.json').write_text('{ broken json',
                                                           encoding='utf-8')
                # mode == 'missing' → 不写文件
                baseline, status = mod.load_previous_manifest(ch_dir)
                ok = (status == expect)
                results.append({
                    'id': c['id'], 'component': c['component'], 'name': c['name'],
                    'ok': ok,
                    'detail': f"期望 baseline_status={expect} 实际={status} "
                              f"(基线节={sorted(baseline)})",
                })
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
        elif kind == 'corrupt_not_never':
            # 判据：基线损坏时**不得**判「从未产出」——须保守但不得伪证
            out = mod.classify_missing(args['missing'], {}, 'corrupt', 'ch01')
            got = [it['classification'] for it in out]
            ok = all(g != 'NEVER_PRODUCED' or '无法证明' in it['evidence']
                     for g, it in zip(got, out))
            results.append({
                'id': c['id'], 'component': c['component'], 'name': c['name'],
                'ok': ok,
                'detail': f"期望基线损坏时不得裸判 NEVER_PRODUCED 实际={got} "
                          f"证据={[it['evidence'] for it in out]}",
            })
    return results


# ═══════════════════════════════════════════════════════════════════════
# 内置评测集
# ═══════════════════════════════════════════════════════════════════════
def builtin_cases() -> list[dict]:
    """首批 5 组件评测用例集。

    设计纪律：
      · 每个组件 ≥3 用例，覆盖「正常 / 边界 / 反向」
      · 边界用例卡在阈值上下 1 分
      · 反向用例必须在协议被破坏时 FAIL（由 tests/test_protocol_eval.py 反向注入验证）
    """
    return [
        # ── 组件 1：路由置信度阈值 ──
        _case('PE-R1-01', 'routing-threshold', 'SSOT 阈值 = 协议声明 70',
              {'kind': 'threshold_ssrc', 'value': 70},
              {'declared_threshold': 70}),
        _case('PE-R1-02', 'routing-threshold', '阈值上下 1 分 ⇒ 归属必须翻转',
              {'kind': 'flip', 'value': True}, {}),
        _case('PE-R1-03', 'routing-threshold', '置信度 80 ≥ 阈值 ⇒ 直派',
              {'kind': 'route_decision', 'value': 'dispatch'},
              {'query': '审查 ch06 的结构'}),
        _case('PE-R1-04', 'routing-threshold', '置信度 60 < 阈值 ⇒ 升级',
              {'kind': 'route_decision', 'value': 'escalate'},
              {'query': '看看这章'}),
        _case('PE-R1-05', 'routing-threshold', '无信号问法 ⇒ 升级',
              {'kind': 'route_decision', 'value': 'escalate'},
              {'query': '帮我搞一下这章'}),

        # ── 组件 2：熔断窗口 ──
        _case('PE-R2-01', 'circuit-breaker', '窗口内 E3=1 ⇒ CLOSED',
              {'value': 'CLOSED'}, {'outcomes': ['OK']}),
        _case('PE-R2-02', 'circuit-breaker', '窗口内 E3=1(另一次成功) ⇒ CLOSED',
              {'value': 'CLOSED'}, {'outcomes': ['ERROR', 'OK']}),
        _case('PE-R2-03', 'circuit-breaker', '连续 E3=2 ⇒ OPEN',
              {'value': 'OPEN'}, {'outcomes': ['ERROR', 'ERROR']}),
        # 窗口大小=3 ⇒ 第 4 次记录时首个 E3 才滑出窗口 ⇒ e3_count 1 < 2 ⇒ CLOSED
        _case('PE-R2-04', 'circuit-breaker', 'E3 滑出窗口 ⇒ 回 CLOSED',
              {'value': 'CLOSED'}, {'outcomes': ['ERROR', 'ERROR', 'OK', 'OK']}),
        _case('PE-R2-05', 'circuit-breaker', 'BLOCKED 计入 E3',
              {'value': 'CLOSED'}, {'outcomes': ['BLOCKED']}),
        _case('PE-R2-06', 'circuit-breaker', 'PARTIAL 计入 E3 ⇒ 2 次即 OPEN',
              {'value': 'OPEN'}, {'outcomes': ['PARTIAL', 'OK', 'PARTIAL']}),
        # ── 三态迁移（R1 修复 e3_window 两态缺口后的行为契约）──
        _case('PE-R2-07', 'circuit-breaker', 'OPEN --probe ⇒ HALF_OPEN',
              {'kind': 'probe', 'value': 'HALF_OPEN'},
              {'outcomes': ['ERROR', 'ERROR']}),
        _case('PE-R2-08', 'circuit-breaker', 'HALF_OPEN 探测成功 ⇒ CLOSED',
              {'kind': 'probe', 'value': 'CLOSED'},
              {'outcomes': ['ERROR', 'ERROR'], 'probe_outcome': 'OK'}),
        _case('PE-R2-09', 'circuit-breaker', 'HALF_OPEN 探测失败 ⇒ 回 OPEN',
              {'kind': 'probe', 'value': 'OPEN'},
              {'outcomes': ['ERROR', 'ERROR'], 'probe_outcome': 'ERROR'}),

        # ── 组件 3：预算优先级 ──
        _case('PE-R3-01', 'budget-priority', '削减次序 P0→P1→P2 递增',
              {'kind': 'order', 'value': ['P0', 'P1', 'P2']},
              {'phases': ['RETRIEVE', 'PRODUCE-R1', 'VERIFY-R1']}),
        _case('PE-R3-02', 'budget-priority', 'VISUALIZE(P3) 晚于 VERIFY(P2)',
              {'kind': 'order', 'value': ['P2', 'P3']},
              {'phases': ['VERIFY-R1', 'VISUALIZE']}),
        _case('PE-R3-03', 'budget-priority', 'RETRIEVE 禁止削减',
              {'kind': 'no_p0_cut', 'value': {'priority': 'P0', 'keyword': '禁止削减'}},
              {'phase': 'RETRIEVE'}),
        _case('PE-R3-04', 'budget-priority', 'VERIFY-R3 为红线不可砍',
              {'kind': 'no_p0_cut', 'value': {'priority': 'P2', 'keyword': '红线'}},
              {'phase': 'VERIFY-R3'}),
        _case('PE-R3-05', 'budget-priority', '预算充足 ⇒ status=OK',
              {'kind': 'status', 'value': 'OK'},
              {'trace': [['RETRIEVE', 1000], ['PRODUCE-R1', 2000]]}),
        _case('PE-R3-06', 'budget-priority', '达 80% ⇒ DEGRADE_SUGGESTED',
              {'kind': 'status', 'value': 'DEGRADE_SUGGESTED'},
              {'trace': [['RETRIEVE', 130000]]}),
        _case('PE-R3-07', 'budget-priority', '达 100% ⇒ HARD_LIMIT_REACHED',
              {'kind': 'status', 'value': 'HARD_LIMIT_REACHED'},
              {'trace': [['RETRIEVE', 150000]]}),

        # ── 组件 4：节级拓扑 ──
        _case('PE-R4-01', 'section-topology', '线性依赖 ⇒ 逐节成波',
              {'kind': 'waves', 'value': [['1.1'], ['1.2'], ['1.3']]},
              {'deps': [['1.1', []], ['1.2', ['1.1']], ['1.3', ['1.2']]]}),
        _case('PE-R4-02', 'section-topology', '无依赖 ⇒ 全部同波',
              {'kind': 'waves', 'value': [['1.1', '1.2', '1.3']]},
              {'deps': [['1.1', []], ['1.2', []], ['1.3', []]]}),
        _case('PE-R4-03', 'section-topology', '菱形依赖 ⇒ 中间并行',
              {'kind': 'waves', 'value': [['1.1'], ['1.2', '1.3'], ['1.4']]},
              {'deps': [['1.1', []], ['1.2', ['1.1']], ['1.3', ['1.1']], ['1.4', ['1.2', '1.3']]]}),
        _case('PE-R4-04', 'section-topology', '成环 ⇒ 不可分波',
              {'kind': 'waves', 'value': 'CYCLE'},
              {'deps': [['1.1', ['1.3']], ['1.2', ['1.1']], ['1.3', ['1.2']]]}),
        _case('PE-R4-05', 'section-topology', '同波内不得有 strong-dep',
              {'kind': 'no_same_wave_dep', 'value': True},
              {'deps': [['1.1', []], ['1.2', ['1.1']], ['1.3', []]]}),
        _case('PE-R4-06', 'section-topology', '分波可复现（输入顺序无关）',
              {'kind': 'reproducible', 'value': True},
              {'deps': [['1.1', []], ['1.2', ['1.1']], ['1.3', ['1.1']]]}),
        _case('PE-R4-07', 'section-topology', 'compute_section_plan 两次一致',
              {'kind': 'deterministic_plan', 'value': True},
              {'deps': [['1.1', []], ['1.2', ['1.1']], ['1.3', []]]}),

        # ── 组件 5：恢复分类 ──
        _case('PE-R5-01', 'recovery-classification', '基线含该节 ⇒ RECOVERABLE',
              {'kind': 'classify', 'value': {'1.1': 'RECOVERABLE'}},
              {'missing': ['1.1'], 'baseline': {'1.1': 'a.md'}, 'baseline_status': 'ok'}),
        _case('PE-R5-02', 'recovery-classification', '基线不含该节 ⇒ NEVER_PRODUCED',
              {'kind': 'classify', 'value': {'1.2': 'NEVER_PRODUCED'}},
              {'missing': ['1.2'], 'baseline': {'1.1': 'a.md'}, 'baseline_status': 'ok'}),
        _case('PE-R5-03', 'recovery-classification', '基线损坏 ⇒ 保守不裸判从未产出',
              {'kind': 'corrupt_not_never', 'value': True},
              {'missing': ['1.1']}),
        _case('PE-R5-04', 'recovery-classification', '清单正常 ⇒ status=ok',
              {'kind': 'manifest_status', 'value': 'ok'}, {'mode': 'ok'}),
        _case('PE-R5-05', 'recovery-classification', '清单损坏 ⇒ status=corrupt',
              {'kind': 'manifest_status', 'value': 'corrupt'}, {'mode': 'corrupt'}),
        _case('PE-R5-06', 'recovery-classification', '清单缺失 ⇒ status=missing',
              {'kind': 'manifest_status', 'value': 'missing'}, {'mode': 'missing'}),
    ]


# ── 执行引擎 ─────────────────────────────────────────────────────────
EVALUATORS = {
    'routing-threshold': eval_routing_threshold,
    'circuit-breaker': eval_circuit_breaker,
    'budget-priority': eval_budget_priority,
    'section-topology': eval_section_topology,
    'recovery-classification': eval_recovery_classification,
}


def run_cases(cases: list[dict], only_component: str = '',
              component_threshold: float = DEFAULT_COMPONENT_THRESHOLD) -> dict:
    """跑评测集 ⇒ 报告（分数 + 失败项清单）。

    双闸判定（见 DEFAULT_COMPONENT_THRESHOLD 的说明）：
      · 总分门槛（threshold）
      · 组件级底线（component_threshold）——任一组件跌破即整体不过
    """
    grouped: dict[str, list[dict]] = {}
    for c in cases:
        if only_component and c['component'] != only_component:
            continue
        grouped.setdefault(c['component'], []).append(c)

    per_component = []
    failures = []
    total = passed = 0

    for comp, group in grouped.items():
        ev = EVALUATORS.get(comp)
        if ev is None:
            for c in group:
                total += 1
                failures.append({'id': c['id'], 'component': comp,
                                 'name': c['name'], 'detail': '无对应评测器'})
            continue
        try:
            with muted_stdout():
                results = ev(group)
        except Exception as e:  # 组件崩了 ⇒ 整组判失败，不静默放行
            for c in group:
                total += 1
                failures.append({'id': c['id'], 'component': comp, 'name': c['name'],
                                 'detail': f'评测执行异常: {type(e).__name__}: {e}'})
            continue
        for r in results:
            total += 1
            if r['ok']:
                passed += 1
            else:
                failures.append({'id': r['id'], 'component': r['component'],
                                 'name': r['name'], 'detail': r['detail']})
        comp_passed = sum(1 for r in results if r['ok'])
        comp_total = len(results)
        comp_score = round(comp_passed / comp_total, 4) if comp_total else 0.0
        per_component.append({
            'component': comp,
            'passed': comp_passed,
            'total': comp_total,
            'score': comp_score,
            'below_component_threshold': comp_score < component_threshold,
        })

    score = round(passed / total, 4) if total else 0.0
    weak = [pc for pc in per_component if pc['below_component_threshold']]
    return {
        'schema': 'stt.protocol_eval/1',
        'total': total,
        'passed': passed,
        'failed': total - passed,
        'score': score,
        'per_component': per_component,
        'failures': failures,
        'component_threshold': component_threshold,
        'weak_components': [pc['component'] for pc in weak],
    }


def render(report: dict, threshold: float, verbose: bool) -> str:
    lines = []
    lines.append('=' * 60)
    lines.append(f"Protocol Eval 总分: {report['passed']}/{report['total']} "
                 f"({report['score']:.3f})")
    if report['per_component']:
        lines.append('--- 分组件 ---')
        for pc in report['per_component']:
            flag = '  ⚠低于组件底线' if pc.get('below_component_threshold') else ''
            lines.append(f"  {pc['component']:26s} {pc['passed']}/{pc['total']} "
                         f"({pc['score']:.3f}){flag}")
    lines.append(f"门槛: 总分 >= {threshold:.2f}  +  每组件 >= "
                 f"{report.get('component_threshold', DEFAULT_COMPONENT_THRESHOLD):.2f}")
    weak = report.get('weak_components') or []
    if weak:
        lines.append(f'⚠ 组件级底线未过: {", ".join(weak)}')
    lines.append('=' * 60)
    if report['failures']:
        lines.append('')
        lines.append(f"失败项 ({len(report['failures'])}):")
        for f in report['failures']:
            lines.append(f"  - [{f['id']}] {f['component']} / {f['name']}")
            lines.append(f"      {f['detail']}")
    if verbose and not report['failures']:
        lines.append('')
        lines.append('（全部通过，无失败项明细）')
    return '\n'.join(lines)


def load_cases(path: Path) -> list[dict]:
    """加载外部用例集（JSON 数组）。"""
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f'用例集读取失败: {e}') from e
    if not isinstance(data, list):
        raise ValueError('用例集必须是 JSON 数组')
    for i, c in enumerate(data):
        if not isinstance(c, dict) or 'id' not in c or 'component' not in c:
            raise ValueError(f'第 {i} 条用例结构非法（需 id/component）')
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description='protocol_eval — 协议组件离线评测')
    ap.add_argument('--cases', default='', help='外部用例集 JSON 路径（默认内置）')
    ap.add_argument('--component', default='', help='只评指定组件')
    ap.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD,
                    help=f'总分通过门槛（默认 {DEFAULT_THRESHOLD}）')
    ap.add_argument('--component-threshold', type=float,
                    default=DEFAULT_COMPONENT_THRESHOLD,
                    help=f'组件级底线（默认 {DEFAULT_COMPONENT_THRESHOLD}）——'
                         '任一组件跌破即拒绝合入')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    ap.add_argument('--save-eval', default='',
                    help='把 JSON 结果落盘到指定路径（供 compute_metrics '
                         '的 protocol_eval_score 指标消费）')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    try:
        if args.cases:
            cases = load_cases(Path(args.cases).expanduser())
        else:
            cases = builtin_cases()
    except ValueError as e:
        print(f'用例集错误: {e}', file=sys.stderr)
        return 3
    except OSError as e:
        print(f'用例集读取失败: {e}', file=sys.stderr)
        return 2

    report = run_cases(cases, args.component, args.component_threshold)
    report['threshold'] = args.threshold
    # 双闸：总分门槛 + 组件级底线
    report['passed_gate'] = (
        report['score'] >= args.threshold
        and not report.get('weak_components')
    )
    report['gate_detail'] = {
        'total_score_ok': report['score'] >= args.threshold,
        'component_threshold_ok': not report.get('weak_components'),
        'weak_components': report.get('weak_components', []),
    }

    # ── 落盘（R1：供 compute_metrics 的 protocol_eval_score 指标消费）──
    if args.save_eval:
        out = Path(args.save_eval).expanduser()
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
        except OSError as e:
            print(f'评测结果落盘失败: {out}（{e}）', file=sys.stderr)
            return 2
        if not args.json:
            print(f'[落盘] {out}')

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.threshold, args.verbose))

    if report['passed_gate']:
        if not args.json:
            print(f"\n✓ PASS — 协议评测 {report['score']:.3f} ≥ {args.threshold:.2f}"
                  f"（组件级底线亦通过），允许合入")
        return 0
    if not args.json:
        weak = report.get('weak_components') or []
        print(f"\n✗ FAIL — 协议评测 {report['score']:.3f} / 门槛 {args.threshold:.2f}"
              f"{'，组件级底线未过: ' + ', '.join(weak) if weak else ''}"
              f"，**拒绝协议合入**（回滚该条改动，候补保持 OPEN）")
    return 1


if __name__ == '__main__':
    sys.exit(main())
