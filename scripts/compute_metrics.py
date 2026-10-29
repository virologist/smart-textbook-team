#!/usr/bin/env python3
"""compute_metrics.py — 过程指标(1-5) + 整章产物质量(6) 计算器

读取 {WORK_ROOT}/运行态/trace.jsonl + 工作区产物,计算:
  1. 分派命中率  (末态 outcome=OK 的任务数 / 派发任务总数——按 task_id 去重取末态,
                  E1 重试的 ERROR 被后续 RESULT 覆盖时不双扣; P2-6 口径修复)
  2. 返工率      (同 task_id 出现 ≥2 次 RESULT OK——同一任务重复成功交付才算返工;
                  ERROR→OK 的重试不算返工,单列 retry_rate; P2-6 口径修复:
                  旧口径按「R2 出现在任务名」计数,把流水线既定的第二轮审查
                  误判为返工,真实运行 2/2=1.000 恒 FAIL)
  2b. retry_rate (含 ERROR/BLOCK 行的任务占比——E1 重试强度,参考项不设门槛)
  3. blocking 占比 (blocking_open 非空任务 / 总任务)
  4. 平均轮次    (同 task_id 的 trace 行数中位数; 自报 turns 仅作参考列 — evo-16 口径修复)
  5. per-task token (in+out 累加,按 task_type; 行内 estimated:true 时报告标注)
  6. 整章产物质量 (C9, 2026-10-30 批次5)——过程指标只答「流程顺不顺」,
     本指标答「产物好不好」: ① 结构完整率(5 类必备段) ② 数据标签完整率
     (数值陈述带 [实]/[估]/[引]/[待核实]) ③ 引用核验通过率(R3 报告汇总)。
     数据源缺失 → 整体 N/A,不阻塞

输出: 文本报告 + 可选 JSON

用法:
  python3 scripts/compute_metrics.py --work-root /path/to/work [--json out.json]
"""
from __future__ import annotations
import argparse
import json
import re
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


def compute(traces: list[dict], work_root: Path | None = None) -> dict:
    if not traces:
        # 无 trace 不代表无产物：产物质量（[6]）仍应计算（C9）
        return {
            'total_traces': 0,
            'total_tasks': 0,
            'has_estimated_tokens': False,
            'spawn_total': 0,
            'spawn_ok': 0,
            'dispatch_hit_rate': None,
            'retry_tasks': 0,
            'retry_rate': None,
            'review_total': 0,
            'review_rework': 0,
            'rework_rate': None,
            'blocking_total': 0,
            'blocking_pct': None,
            'avg_turns': None,
            'self_reported_turns_median': None,
            'tokens_per_task': {},
            'by_task_type': {},
            'product_quality': _product_quality(work_root) if work_root else None,
        }

    # ── P2-6 口径修复(2026-10-15) ──────────────────────────────────
    # 按 task_id 去重取【末态】: E1 重试(ERROR→RESULT OK)不双扣分派命中率;
    # 返工改按「同 task_id ≥2 次 RESULT OK」判定(与文件名里的 R2 彻底解耦);
    # 重试强度单列 retry_rate(参考项,不设门槛)。
    by_task: dict[str, list[dict]] = defaultdict(list)
    for t in traces:
        tid = t.get('task_id') or ''
        by_task[tid].append(t)

    def _terminal(rows: list[dict]) -> dict:
        """末态行: 取该 task_id 最后一行(trace 为 append-only,文件序即时间序)。"""
        return rows[-1]

    dispatched = {tid: rows for tid, rows in by_task.items()
                  if any(r.get('type') in ('RESULT', 'BLOCK', 'ERROR') for r in rows)}
    spawn_total = len(dispatched)
    spawn_ok = sum(1 for rows in dispatched.values()
                   if _terminal(rows).get('type') == 'RESULT'
                   and _terminal(rows).get('outcome') == 'OK')
    dispatch_hit_rate = spawn_ok / spawn_total if spawn_total else None

    retry_tasks = {tid for tid, rows in by_task.items()
                   if any(r.get('type') in ('ERROR', 'BLOCK') for r in rows)}
    retry_rate = (len(retry_tasks) / spawn_total) if spawn_total else None

    # 返工: 同 task_id 出现 ≥2 次「RESULT outcome=OK」= 同一任务重复成功交付
    review_task_ids = {tid for tid, rows in by_task.items()
                       if any((r.get('task_type') or '').startswith('review-') for r in rows)}
    rework_task_ids = {tid for tid, rows in by_task.items()
                       if sum(1 for r in rows
                              if r.get('type') == 'RESULT' and r.get('outcome') == 'OK') >= 2}
    review_total = len(review_task_ids)
    review_rework = len(review_task_ids & rework_task_ids)
    rework_rate = review_rework / review_total if review_total else None

    blocking_total = sum(1 for t in traces if t.get('blocking_open'))
    blocking_pct = blocking_total / len(traces) if traces else None

    # 平均轮次（evo-16 口径修复）: 按文档语义 = 同 task_id 的 trace 行数中位数（接力轮次,可审计）;
    # 成员自报 turns 取中位数仅作参考列（自报值不可审计,与 §2 预算对账"防谎报"原则一致）
    lines_per_task = Counter(t.get('task_id') for t in traces)
    avg_turns = statistics.median(list(lines_per_task.values())) if lines_per_task else None

    self_reported = defaultdict(int)
    for t in traces:
        tid = t.get('task_id')
        if t.get('turns'):
            self_reported[tid] = max(self_reported[tid], t.get('turns', 0))
    self_reported_turns = statistics.median(list(self_reported.values())) if self_reported else None

    tokens_per_task: dict[str, int] = defaultdict(int)
    for t in traces:
        tid = t.get('task_id')
        tokens_per_task[tid] += (t.get('tokens_in', 0) + t.get('tokens_out', 0))

    by_task_type: dict[str, dict] = defaultdict(lambda: {'count': 0, 'tokens': 0})
    for t in traces:
        tt = t.get('task_type') or 'unknown'
        by_task_type[tt]['count'] += 1
        by_task_type[tt]['tokens'] += (t.get('tokens_in', 0) + t.get('tokens_out', 0))

    # ── [6] 整章产物质量（C9，2026-10-30 批次 5）─────────────────────────
    # 过程指标（[1]-[5]）只回答「流程跑得顺不顺」，不回答「产物好不好」。
    # 本指标从工作区产物直接计算三个结构化维度；数据源缺失时整体 N/A（不阻塞）。
    product = _product_quality(work_root)

    return {
        'total_traces': len(traces),
        'total_tasks': len(by_task),
        'has_estimated_tokens': any(t.get('estimated') for t in traces),
        'spawn_total': spawn_total,
        'spawn_ok': spawn_ok,
        'dispatch_hit_rate': dispatch_hit_rate,
        'retry_tasks': len(retry_tasks),
        'retry_rate': retry_rate,
        'review_total': review_total,
        'review_rework': review_rework,
        'rework_rate': rework_rate,
        'blocking_total': blocking_total,
        'blocking_pct': blocking_pct,
        'avg_turns': avg_turns,
        'self_reported_turns_median': self_reported_turns,
        'tokens_per_task': dict(tokens_per_task),
        'by_task_type': dict(by_task_type),
        'product_quality': product,
    }


def _product_quality(work_root: Path) -> dict | None:
    """整章产物质量三维度（C9）。数据不全 → 返回 None（N/A，不阻塞）。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from count_net_words import count_net_words
    except ImportError:
        return None

    chapters = sorted((work_root / '章节').glob('ch*')) if (work_root / '章节').is_dir() else []
    if not chapters:
        return None

    chapters_out = []
    n_struct_total = n_struct_ok = 0
    n_label_total = n_label_ok = 0

    for ch in chapters:
        draft = ch / 'draft.md'
        if not draft.is_file():
            continue
        text = draft.read_text(encoding='utf-8')
        entry: dict = {'chapter': ch.name}

        # ① 结构完整率：5 类必备段各自存在即 +1
        #    （章标题 / ≥1 节标题 / 图表位或图表 / 习题位 / 参考文献）
        required = {
            '章标题': re.search(r'^#\s+', text, re.M),
            '节标题': re.search(r'^##\s+', text, re.M),
            '图表': re.search(r'\[图\s*\d+-\d+|^\s*图\s*\d+-\d+', text, re.M),
            '习题位': re.search(r'\[习题\s*\d+-\d+', text),
            '参考文献': re.search(r'^##\s*参考文献', text, re.M),
        }
        ok = sum(1 for v in required.values() if v)
        n_struct_total += len(required)
        n_struct_ok += ok
        entry['structure'] = f'{ok}/{len(required)}'

        # ② 数据标签完整率：数值触发词陈述句带 [实]/[估]/[引]/[待核实] 的比例
        trigger = re.compile(
            r'[^。！？\n]*(?:发病率|病死率|死亡率|阳性率|检出率|有效|剂量|浓度|'
            r'效价|比例|[%％]|\d+(\.\d+)?\s*(?:%|％|倍|次|天|日|周|年|mg|ml|ug))[^。！？\n]*[。！？]', re.I)
        label = re.compile(r'\[(?:实|估|引|待核实)[^\]]*\]')
        sents = [s for s in trigger.findall(text + '。') if s]
        # findall 返回 tuple（含捕获组），回原文找
        sents = trigger.findall(text)
        n_trig = 0
        n_lab = 0
        for mt in trigger.finditer(text):
            n_trig += 1
            if label.search(mt.group(0)):
                n_lab += 1
        n_label_total += n_trig
        n_label_ok += n_lab
        entry['labels'] = f'{n_lab}/{n_trig}' if n_trig else 'N/A(无数值陈述)'

        # ③ 引用核验通过率：从 R3 审查报告抓核验汇总（无报告 → N/A）
        pass_rate = None
        for rep in sorted((ch / 'review').glob('round*_report.md')) if (ch / 'review').is_dir() else []:
            rt = rep.read_text(encoding='utf-8')
            m = re.search(r'核验\s*(\d+)\s*条\s*\|?\s*通过\s*(\d+)', rt)
            if m and int(m.group(1)) > 0:
                pass_rate = int(m.group(2)) / int(m.group(1))
        if pass_rate is not None:
            entry['citation_pass'] = f'{pass_rate:.2f}'
        else:
            entry['citation_pass'] = 'N/A(无审查报告)'
        chapters_out.append(entry)

    if not chapters_out:
        return None
    struct_rate = n_struct_ok / n_struct_total if n_struct_total else None
    label_rate = n_label_ok / n_label_total if n_label_total else None
    rates = [float(c['citation_pass']) for c in chapters_out
             if not str(c['citation_pass']).startswith('N/A')]
    citation = sum(rates) / len(rates) if rates else None
    return {
        'chapters': chapters_out,
        'structure_rate': struct_rate,
        'label_rate': label_rate,
        'citation_pass_rate': citation,
        'thresholds': {'structure_rate': 1.00, 'label_rate': 0.95, 'citation_pass_rate': 0.95},
    }


def render(m: dict) -> str:
    lines = ['=' * 60, '智能体团队 5 项关键指标', '=' * 60]
    lines.append(f'总 trace 数: {m["total_traces"]}  |  任务数(按 task_id 去重): {m["total_tasks"]}')
    lines.append('')
    lines.append('[1] 分派命中率 (末态 OK 任务 / 派发任务——按 task_id 去重,重试不双扣)')
    if m['dispatch_hit_rate'] is not None:
        lines.append(f'    {m["spawn_ok"]}/{m["spawn_total"]} = {m["dispatch_hit_rate"]:.3f}')
        rr = m.get('retry_rate')
        if rr is not None:
            lines.append(f'    (参考) retry_rate = {m["retry_tasks"]}/{m["spawn_total"]} = {rr:.2f}'
                         '  (E1 重试强度,不设门槛)')
        lines.append(f'    门槛 ≥ 0.80  {"✓ PASS" if m["dispatch_hit_rate"] >= 0.80 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[2] 返工率 (同 task_id ≥2 次成功交付的 review 任务 / review 任务数)')
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
    lines.append('[4] 平均轮次 (同 task_id 的 trace 行数中位数 — 接力轮次,可审计)')
    if m['avg_turns'] is not None:
        lines.append(f'    median = {m["avg_turns"]}')
        sr = m.get('self_reported_turns_median')
        if sr is not None:
            lines.append(f'    (参考) 成员自报 turns 中位数 = {sr} (不可审计,不进门禁)')
        lines.append(f'    门槛 ≤ 6  {"✓ PASS" if m["avg_turns"] <= 6 else "✗ FAIL"}')
    else:
        lines.append('    暂无数据')

    lines.append('')
    lines.append('[5] per-task token (按 task_type 累加)')
    if m['by_task_type']:
        for tt, info in sorted(m['by_task_type'].items(), key=lambda x: -x[1]['tokens']):
            lines.append(f'    {tt:24s}  {info["count"]:3d} spawn  {info["tokens"]:>8d} tokens')
        if m.get('has_estimated_tokens'):
            lines.append('    ⚠ 含估算值(estimated:true)——平台未暴露真实用量,按字符数÷3 估,不可审计')
    else:
        lines.append('    暂无数据')

    lines.append('')
    pq = m.get('product_quality')
    lines.append('[6] 整章产物质量 (C9: 结构完整率 / 数据标签完整率 / 引用核验通过率)')
    if pq:
        sr, lr, cr = pq['structure_rate'], pq['label_rate'], pq['citation_pass_rate']
        th = pq['thresholds']
        lines.append(f'    ① 结构完整率   : '
                     + (f'{sr:.3f}  门槛 ≥{th["structure_rate"]:.2f}  '
                        f'{"✓ PASS" if sr >= th["structure_rate"] else "✗ FAIL"}' if sr is not None else 'N/A'))
        lines.append(f'    ② 标签完整率   : '
                     + (f'{lr:.3f}  门槛 ≥{th["label_rate"]:.2f}  '
                        f'{"✓ PASS" if lr >= th["label_rate"] else "✗ FAIL"}' if lr is not None else 'N/A(无数值陈述)'))
        lines.append(f'    ③ 引用核验通过 : '
                     + (f'{cr:.3f}  门槛 ≥{th["citation_pass_rate"]:.2f}  '
                        f'{"✓ PASS" if cr >= th["citation_pass_rate"] else "✗ FAIL"}' if cr is not None else 'N/A(无审查报告)'))
        for c in pq['chapters']:
            lines.append(f'      - {c["chapter"]}: 结构 {c["structure"]} | 标签 {c["labels"]} | 核验 {c["citation_pass"]}')
    else:
        lines.append('    N/A（工作区无 章节/ 产物，不阻塞）')

    lines.append('=' * 60)
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--json', help='输出 JSON 路径')
    args = ap.parse_args()

    traces = load_traces(Path(args.work_root))
    m = compute(traces, work_root=Path(args.work_root))
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
