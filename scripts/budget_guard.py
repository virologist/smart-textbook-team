#!/usr/bin/env python3
"""budget_guard.py — 相位级 token 预算守护（2026-11-04 诊断 H4 执行体）

问题背景
========
harness §2 定义三重预算阈值：

  ① phase 软上限  tokens_per_phase[phase]  —— 全 13 相位各有一个软上限
  ② 章节硬上限    tokens_limit = 150K
  ③ 累计已用      tokens_used

并规定「超软上限 → trace 记 WARN，继续运行」「累计达 80% → 触发
`--skip-skill-preload` 降级档」。

但在此版本之前，**全包 scripts/ 目录 0 个消费点**读 `tokens_per_phase`：

  · 软上限定义了但没有任何程序比较它 → 超支了也没人知道
  · 「按 phase 累加」无从实现，因为 trace 连 phase 字段都没有
  · 预算降级不可审计——触发与否全凭编排者自觉

本脚本做什么
============
从 trace.jsonl 按 phase 分桶累加 token，与软上限比对并给出处置建议。

它不自动削减预算（削减是破坏性且需人决策的），只做**判定与告警**：
  · 软上限超支 → 报 PHASE_OVER_BUDGET + 建议削减方向（harness §3.1 优先级）
  · 章节硬上限 80% → 报 DEGRADE_SUGGESTED（应触发 --skip-skill-preload）
  · 硬上限 100% → 报 HARD_LIMIT_REACHED（必须保存现场上报）

退出码
======
  exit 0  预算健康
  exit 1  超软上限或达降级阈值（需处置，但可继续）
  exit 2  已达章节硬上限（必须保存现场上报）

用法
====
  python3 scripts/budget_guard.py --work-root $WORK_ROOT
  python3 scripts/budget_guard.py --work-root $WORK_ROOT --phase PRODUCE-R2
  python3 scripts/budget_guard.py --work-root $WORK_ROOT --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# harness §2：章节 token 硬上限（150K）
DEFAULT_TOKENS_LIMIT = 150_000
# harness §3.1：达 80% 触发降级档
DEGRADE_THRESHOLD = 0.80

# harness §2：13 相位 token 软上限（缺省值；黑板若已声明则以黑板为准）
DEFAULT_TOKENS_PER_PHASE = {
    'BOOTSTRAP': 8000, 'INTAKE': 8000, 'CLARIFY': 10000, 'SPECIFY': 12000,
    'RETRIEVE': 40000, 'PRODUCE-R1': 30000, 'PRODUCE-R2': 30000,
    'PRODUCE-R3': 30000, 'VERIFY-R1': 12000, 'VERIFY-R2': 12000,
    'VERIFY-R3': 20000, 'PROOFREAD-R4': 15000, 'PROOFREAD-R5': 10000,
    'CONSOLIDATION': 12000, 'VISUALIZE': 20000, 'ASSEMBLE': 10000,
    'DELIVER': 8000, 'LEARN': 8000,
    # 全书域
    'BOOK_BOOTSTRAP': 10000, 'BOOK_SPEC': 20000, 'CHAPTER_SCHEDULE': 15000,
    'BOOK_CONSOLIDATION': 40000, 'BOOK_DELIVER': 20000,
}

# harness §3.1：预算吃紧时的削减优先级（禁止为保 P1/P3 而削减 P0）
CUT_PRIORITY = {
    'RETRIEVE': ('P0', '禁止削减——证据缺失会一路传导到审查打回'),
    'PRODUCE-R1': ('P1', '可砍低 Bloom 层级节，不砍核心节'),
    'PRODUCE-R2': ('P1', '同上'),
    'PRODUCE-R3': ('P1', '同上'),
    'VERIFY-R1': ('P2', 'R2 深度审查可降为抽样'),
    'VERIFY-R3': ('P2', '数据与引用核验是红线，不可砍'),
    'VISUALIZE': ('P3', '可整段推迟，走 W4 补图流程'),
    'PROOFREAD-R4': ('P4', '可降为只查 AI 腔与术语一致'),
}


def _load_traces(work_root: Path) -> list[dict]:
    f = work_root / '运行态' / 'trace.jsonl'
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _blackboard_budget(work_root: Path) -> dict:
    """读黑板 budget 段（若存在）。黑板声明优先于默认软上限。"""
    bb = work_root / '运行态' / 'workflow-state.yaml'
    if not bb.is_file():
        return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(bb.read_text(encoding='utf-8')) or {}
        return data.get('budget') or {}
    except Exception:
        return {}


def compute_budget(work_root: Path) -> dict:
    traces = _load_traces(work_root)
    bb = _blackboard_budget(work_root)

    per_phase: dict[str, int] = {}
    total = 0
    estimated = 0
    unknown_phase = 0
    for t in traces:
        tin = int(t.get('tokens_in') or 0)
        tout = int(t.get('tokens_out') or 0)
        v = tin + tout
        total += v
        if t.get('estimated'):
            estimated += v
        ph = (t.get('phase') or '').strip()
        if ph:
            per_phase[ph] = per_phase.get(ph, 0) + v
        else:
            unknown_phase += v

    limits = dict(DEFAULT_TOKENS_PER_PHASE)
    bb_per_phase = bb.get('tokens_per_phase') or {}
    if isinstance(bb_per_phase, dict):
        for k, v in bb_per_phase.items():
            try:
                limits[str(k)] = int(v)
            except (TypeError, ValueError):
                continue

    hard_limit = int(bb.get('tokens_limit') or DEFAULT_TOKENS_LIMIT)

    phase_rows = []
    for ph, used in sorted(per_phase.items()):
        cap = limits.get(ph)
        over = bool(cap and used > cap)
        pri, hint = CUT_PRIORITY.get(ph, ('—', '未定义削减策略'))
        phase_rows.append({
            'phase': ph, 'used': used, 'limit': cap,
            'over': over,
            'ratio': round(used / cap, 3) if cap else None,
            'cut_priority': pri, 'cut_hint': hint,
        })

    ratio = total / hard_limit if hard_limit else 0.0
    if ratio >= 1.0:
        status = 'HARD_LIMIT_REACHED'
    elif ratio >= DEGRADE_THRESHOLD:
        status = 'DEGRADE_SUGGESTED'
    else:
        status = 'OK'

    return {
        'total_tokens': total,
        'estimated_tokens': estimated,
        'unknown_phase_tokens': unknown_phase,
        'hard_limit': hard_limit,
        'ratio': round(ratio, 3),
        'status': status,
        'per_phase': phase_rows,
        'degrade_threshold': DEGRADE_THRESHOLD,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='budget_guard — 相位级 token 预算守护')
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--phase', default='', help='只看某个相位')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser().resolve()
    if not work_root.is_dir():
        print(f'WORK_ROOT 不存在: {work_root}', file=sys.stderr)
        return 3

    r = compute_budget(work_root)

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f'TOTAL_TOKENS={r["total_tokens"]}  HARD_LIMIT={r["hard_limit"]}  '
              f'RATIO={r["ratio"]}  STATUS={r["status"]}')
        if r['estimated_tokens']:
            print(f'[WARN] 其中 {r["estimated_tokens"]} tokens 来自 estimated 行（不可审计）',
                  file=sys.stderr)
        if r['unknown_phase_tokens']:
            print(f'[WARN] {r["unknown_phase_tokens"]} tokens 无 phase 归属'
                  f'（trace 缺 phase 字段的历史行）——未计入任何相位桶', file=sys.stderr)
        rows = r['per_phase']
        if args.phase:
            rows = [x for x in rows if x['phase'] == args.phase]
        if rows:
            print('--- 相位级 token ---')
            for x in rows:
                cap = x['limit'] if x['limit'] else '-'
                flag = ' ⚠超限' if x['over'] else ''
                print(f"  {x['phase']:18s} used={x['used']:>8d}  cap={cap:>8}  "
                      f"ratio={x['ratio']}  削减优先级={x['cut_priority']}{flag}")
                if x['over']:
                    print(f"      ↳ 处置: {x['cut_hint']}")
        else:
            print('（无相位级 token 数据——trace 缺 phase 字段的历史行不计入）')

        if r['status'] == 'DEGRADE_SUGGESTED':
            print(f"[预算预警] 已用 {r['ratio']:.0%} ≥ {DEGRADE_THRESHOLD:.0%} —— "
                  f"按 harness §3.1 应触发 --skip-skill-preload 降级档，"
                  f"并在黑板 budget.cuts 记削减内容", file=sys.stderr)
        elif r['status'] == 'HARD_LIMIT_REACHED':
            print(f"[预算耗尽] 已达章节硬上限 —— 按 harness §3「保存现场上报，"
                  f"不静默丢弃」，禁止继续派工", file=sys.stderr)

    if r['status'] == 'HARD_LIMIT_REACHED':
        return 2
    if r['status'] == 'DEGRADE_SUGGESTED' or any(x['over'] for x in r['per_phase']):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
