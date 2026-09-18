#!/usr/bin/env python3
"""compute_metrics.py — 5 指标计算器

读取 {WORK_ROOT}/运行态/trace.jsonl,计算:
  1. 分派命中率  (spawn RESULT OK 数 / spawn 总数)
  2. 返工率      (同 task_id R2+ 计数 / 审查类总数)
  3. blocking 占比 (blocking_open 非空任务 / 总任务)
  4. 平均轮次    (同 task_id 的 trace 行数中位数)
  5. per-task token (in+out 累加,按 task_id)

输出: 文本报告 + 可选 JSON

用法:
  python3 scripts/compute_metrics.py --work-root /path/to/work [--json out.json]
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_traces(work_root: Path) -> list[dict]:
    trace_file = work_root / '运行态' / 'trace.jsonl'
    if not trace_file.exists():
        return []
    out = []
    with open(trace_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def compute(traces: list[dict]) -> dict:
    if not traces:
        return {
            'total_traces': 0,
            'spawn_total': 0,
            'spawn_ok': 0,
            'dispatch_hit_rate': None,
            'review_total': 0,
            'review_rework': 0,
            'rework_rate': None,
            'blocking_total': 0,
            'blocking_pct': None,
            'avg_turns': None,
            'tokens_per_task': {},
            'by_task_type': {},
        }

    spawn_total = sum(1 for t in traces if t.get('type') in ('RESULT', 'BLOCK', 'ERROR'))
    spawn_ok = sum(1 for t in traces if t.get('type') == 'RESULT' and t.get('outcome') == 'OK')
    dispatch_hit_rate = spawn_ok / spawn_total if spawn_total else None

    review_tasks = [t for t in traces if (t.get('task_type') or '').startswith('review-')]
    review_total = len(review_tasks)
    # 返工 = 同一 task_id 出现 R2/R3/...
    task_ids = Counter(t.get('task_id') for t in traces)
    rework_task_ids = {tid for tid, cnt in task_ids.items() if cnt >= 2}
    review_rework = sum(1 for t in review_tasks if t.get('task_id') in rework_task_ids)
    rework_rate = review_rework / review_total if review_total else None

    blocking_total = sum(1 for t in traces if t.get('blocking_open'))
    blocking_pct = blocking_total / len(traces) if traces else None

    turns_per_task = defaultdict(int)
    for t in traces:
        tid = t.get('task_id')
        if t.get('turns'):
            turns_per_task[tid] = max(turns_per_task[tid], t.get('turns', 0))
    turns_count = list(turns_per_task.values())
    avg_turns = statistics.median(turns_count) if turns_count else None

    tokens_per_task: dict[str, int] = defaultdict(int)
    for t in traces:
        tid = t.get('task_id')
        tokens_per_task[tid] += (t.get('tokens_in', 0) + t.get('tokens_out', 0))

    by_task_type: dict[str, dict] = defaultdict(lambda: {'count': 0, 'tokens': 0})
    for t in traces:
        tt = t.get('task_type') or 'unknown'
        by_task_type[tt]['count'] += 1
        by_task_type[tt]['tokens'] += (t.get('tokens_in', 0) + t.get('tokens_out', 0))

    return {
        'total_traces': len(traces),
        'spawn_total': spawn_total,
        'spawn_ok': spawn_ok,
        'dispatch_hit_rate': dispatch_hit_rate,
        'review_total': review_total,
        'review_rework': review_rework,
        'rework_rate': rework_rate,
        'blocking_total': blocking_total,
        'blocking_pct': blocking_pct,
        'avg_turns': avg_turns,
        'tokens_per_task': dict(tokens_per_task),
        'by_task_type': dict(by_task_type),
    }


def render(m: dict) -> str:
    lines = ['=' * 60, '智能体团队 5 项关键指标', '=' * 60]
    lines.append(f'总 trace 数: {m["total_traces"]}')
    lines.append('')
    lines.append('[1] 分派命中率 (spawn RESULT OK / spawn 总数)')
    if m['dispatch_hit_rate'] is not None:
        lines.append(f'    {m["spawn_ok"]}/{m["spawn_total"]} = {m["dispatch_hit_rate"]:.3f}')
        lines.append(f'    门槛 ≥ 0.80  {"✓ PASS" if m["dispatch_hit_rate"] >= 0.80 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[2] 返工率 (review 任务 R2+ / review 总数)')
    if m['rework_rate'] is not None:
        lines.append(f'    {m["review_rework"]}/{m["review_total"]} = {m["rework_rate"]:.3f}')
        lines.append(f'    门槛 ≤ 0.30  {"✓ PASS" if m["rework_rate"] <= 0.30 else "✗ FAIL"}')
    else:
        lines.append('    暂无 review 数据')

    lines.append('')
    lines.append('[3] blocking 占比 (blocking_open 非空 / 总 trace)')
    if m['blocking_pct'] is not None:
        lines.append(f'    {m["blocking_total"]}/{m["total_traces"]} = {m["blocking_pct"]:.3f}')
        lines.append(f'    门槛 ≤ 0.10  {"✓ PASS" if m["blocking_pct"] <= 0.10 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[4] 平均轮次 (同 task_id 的 trace 行数中位数)')
    if m['avg_turns'] is not None:
        lines.append(f'    median = {m["avg_turns"]}')
        lines.append(f'    门槛 ≤ 6  {"✓ PASS" if m["avg_turns"] <= 6 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[5] per-task token (按 task_type 累加)')
    if m['by_task_type']:
        for tt, info in sorted(m['by_task_type'].items(), key=lambda x: -x[1]['tokens']):
            lines.append(f'    {tt:24s}  {info["count"]:3d} spawn  {info["tokens"]:>8d} tokens')
    else:
        lines.append('    暂无数据')

    lines.append('=' * 60)
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--json', help='输出 JSON 路径')
    args = ap.parse_args()

    traces = load_traces(Path(args.work_root))
    m = compute(traces)
    print(render(m))

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'JSON: {args.json}')

    # 退出码:任一指标 fail 则 1
    bad = []
    if m['dispatch_hit_rate'] is not None and m['dispatch_hit_rate'] < 0.80:
        bad.append('dispatch_hit_rate')
    if m['rework_rate'] is not None and m['rework_rate'] > 0.30:
        bad.append('rework_rate')
    if m['blocking_pct'] is not None and m['blocking_pct'] > 0.10:
        bad.append('blocking_pct')
    if m['avg_turns'] is not None and m['avg_turns'] > 6:
        bad.append('avg_turns')

    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
