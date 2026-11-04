#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""metrics_baseline.py — 指标基线存储与对比（2026-11-04 B2 批次 · 补 Q3 闭环）

存在理由
--------
诊断报告 Q3：`compute_metrics.py` 已输出 30+ 指标，但**无历史基线存储、无
消费通路**，指标只用于单次 FAIL 判定，无法回答「这次比上次好吗」。
本脚本是「指标 → 学习 → 协议修订 → 评测回归 → 新基线」回路的第一环。

设计原则
--------
1. **append-only**：基线文件永不覆写、永不删行。协议升版后的「基线重置」
   通过追加一行 `type=reset` 分段标记实现，`compare` 只取最后一个 reset
   之后的行 ⇒ 历史全程可审计，且杜绝「静默重置基线」掩盖漂移。
2. **只比数值标量**：`compute_metrics.py` 的返回值里混有 dict / list / None，
   统一展平取数值标量，避免 delta 计算被结构化字段污染。
3. **读端纪律不变**：本脚本不修改 `compute_metrics.py` 的「退化区间排除」
   逻辑，也不改它的退出码语义；越界告警是**新增**的一层，不替代原门禁。
4. **显式优于隐式**：`reset` 必须同时给 `--reason` 与 `--confirm`；
   同 chapter 重复 record 默认拒绝（要覆盖须 `--force`）。

退出码
------
  0  OK（record/list 成功；compare 无越界）
  1  DRIFT（compare 发现偏离基线 > 阈值或破红线）
  2  INPUT_ERROR（参数缺失 / 路径不存在 / chapter 重复 / 格式错）
  3  BASELINE_CORRUPT（基线文件存在坏行，无法可靠比对）

用法
----
  python3 scripts/metrics_baseline.py record  --work-root X --chapter ch01 [--protocol-version 2.5.0]
  python3 scripts/metrics_baseline.py compare --work-root X [--window 5] [--threshold 0.20]
  python3 scripts/metrics_baseline.py list    --work-root X
  python3 scripts/metrics_baseline.py reset   --work-root X --reason "协议升版" --confirm
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 与 compute_metrics.py 同目录，直接 import（不复制指标计算逻辑）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute_metrics as cm  # noqa: E402

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_INPUT_ERROR = 2
EXIT_BASELINE_CORRUPT = 3

BASELINE_REL = Path('运行态') / 'metrics_baseline.jsonl'
CHAPTER_RE = re.compile(r'^ch\d{2}$|^self-evo$')

# 红线（与 compute_metrics.main() 的退出码判据逐项对齐，避免口径撕裂）
RED_LINES = {
    'dispatch_hit_rate': ('min', 0.80),
    'rework_rate': ('max', 0.30),
    'blocking_pct': ('max', 0.10),
    'avg_turns': ('max', 6.0),
}

# 越低越好的指标（用于给 delta 标注方向，不改变是否告警的判据）
LOWER_IS_BETTER = {'rework_rate', 'blocking_pct', 'avg_turns',
                   'timeout_rate', 'retry_rate', 'latency_ms', 'total_tokens'}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def baseline_path(work_root: Path) -> Path:
    return work_root / BASELINE_REL


def flatten_numbers(metrics: dict, prefix: str = '') -> dict[str, float]:
    """把 compute_metrics 的返回值展平为「路径 → 数值标量」。

    只取 int/float（bool 排除），跳过 None / str / 嵌套容器里的非数值项；
    嵌套 dict 用 `.` 连接路径（如 `product_quality.structure_rate`）。
    """
    out: dict[str, float] = {}
    for k, v in metrics.items():
        key = f'{prefix}.{k}' if prefix else str(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[key] = float(v)
        elif isinstance(v, dict):
            out.update(flatten_numbers(v, key))
    return out


def current_metrics(work_root: Path, metrics_json: str | None = None) -> dict:
    """取当前指标：优先读 --metrics-json，否则现场调 compute_metrics.compute()。"""
    if metrics_json:
        p = Path(metrics_json)
        if not p.is_file():
            raise ValueError(f'--metrics-json 指定的文件不存在：{p}')
        return json.loads(p.read_text(encoding='utf-8'))
    traces, bad = cm.load_traces(work_root)
    return cm.compute(traces, work_root=work_root, bad_lines=bad)


def load_rows(path: Path) -> tuple[list[dict], int]:
    """读 JSONL；坏行单独计数返回，不静默吞掉。"""
    rows, bad = [], 0
    if not path.is_file():
        return rows, bad
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError('顶层不是对象')
            rows.append(obj)
        except (json.JSONDecodeError, ValueError):
            bad += 1
    return rows, bad


def active_rows(rows: list[dict]) -> list[dict]:
    """只保留最后一个 reset 标记之后的 record 行（分段基线）。"""
    last_reset = -1
    for i, r in enumerate(rows):
        if r.get('type') == 'reset':
            last_reset = i
    return [r for r in rows[last_reset + 1:]
            if r.get('type', 'record') == 'record' and isinstance(r.get('metrics_snapshot'), dict)]


def cmd_record(args) -> int:
    root = Path(args.work_root)
    if not root.is_dir():
        print(f'✗ work-root 不存在：{root}', file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not CHAPTER_RE.match(args.chapter or ''):
        print(f"✗ chapter 格式须为 ch## 或 self-evo，实际 {args.chapter!r}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    p = baseline_path(root)
    rows, bad = load_rows(p)
    if bad:
        print(f'✗ 基线文件有 {bad} 条坏行，拒绝追加（先修复或显式 reset 分段）', file=sys.stderr)
        return EXIT_BASELINE_CORRUPT
    if any(r.get('chapter') == args.chapter for r in active_rows(rows)) and not args.force:
        print(f'✗ chapter {args.chapter} 在当前基线分段中已存在；'
              f'重复记录会污染 running mean，确需覆盖请加 --force', file=sys.stderr)
        return EXIT_INPUT_ERROR

    try:
        metrics = current_metrics(root, args.metrics_json)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f'✗ 读取当前指标失败：{e}', file=sys.stderr)
        return EXIT_INPUT_ERROR

    row = {
        'type': 'record',
        'chapter': args.chapter,
        'ts': _now(),
        'protocol_version': args.protocol_version or '',
        'metrics_snapshot': flatten_numbers(metrics),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    print(f'✓ 已追加基线：{args.chapter}  ({len(row["metrics_snapshot"])} 个数值指标)')
    print(f'  {p}')
    return EXIT_OK


def cmd_compare(args) -> int:
    root = Path(args.work_root)
    if not root.is_dir():
        print(f'✗ work-root 不存在：{root}', file=sys.stderr)
        return EXIT_INPUT_ERROR
    if args.window < 1:
        print('✗ --window 须 ≥ 1', file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not (0 < args.threshold <= 1):
        print('✗ --threshold 须落在 (0, 1]', file=sys.stderr)
        return EXIT_INPUT_ERROR

    p = baseline_path(root)
    rows, bad = load_rows(p)
    if bad:
        print(f'✗ 基线文件有 {bad} 条坏行，无法可靠比对', file=sys.stderr)
        return EXIT_BASELINE_CORRUPT
    hist = active_rows(rows)
    if not hist:
        print('ℹ 当前分段无基线记录 ⇒ 无法对比（先 record 至少一章）。'
              '不视为越界，退出码 0。')
        return EXIT_OK

    # 当前章若已入基线则排除自身，避免「自己跟自己比」恒不告警
    pool = [r for r in hist if not (args.chapter and r.get('chapter') == args.chapter)]
    pool = pool[-args.window:]
    if not pool:
        print('ℹ 排除当前章后无可用基线 ⇒ 无法对比，退出码 0。')
        return EXIT_OK

    try:
        cur = flatten_numbers(current_metrics(root, args.metrics_json))
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f'✗ 读取当前指标失败：{e}', file=sys.stderr)
        return EXIT_INPUT_ERROR

    # running mean：只对两边都有的指标求均值
    keys = sorted(set(cur) & set().union(*(set(r['metrics_snapshot']) for r in pool)))
    base = {k: sum(r['metrics_snapshot'][k] for r in pool
                   if k in r['metrics_snapshot']) /
               sum(1 for r in pool if k in r['metrics_snapshot'])
            for k in keys}

    print(f'基线对比：{len(pool)} 章 running mean（window={args.window}）'
          f' | 阈值 {args.threshold:.0%} | 可比指标 {len(keys)} 个')
    print(f'{"指标":<44} {"基线":>10} {"当前":>10} {"delta":>9}  判定')
    print('-' * 86)

    alerts: list[str] = []
    for k in keys:
        b, c = base[k], cur[k]
        denom = abs(b) if abs(b) > 1e-9 else 1.0
        delta = (c - b) / denom
        flags = []
        if abs(delta) > args.threshold:
            direction = '↑' if delta > 0 else '↓'
            worse = (direction == '↑') if k.split('.')[-1] in LOWER_IS_BETTER else (direction == '↓')
            flags.append(f"偏离{abs(delta):.0%}{direction}" + ('·恶化' if worse else '·改善'))
        leaf = k.split('.')[-1]
        if leaf in RED_LINES:
            mode, limit = RED_LINES[leaf]
            if (mode == 'min' and c < limit) or (mode == 'max' and c > limit):
                flags.append(f'破红线({mode}={limit})')
        tag = '  '.join(flags) if flags else 'OK'
        if flags:
            alerts.append(f'{k}: {b:.3f} → {c:.3f} ({delta:+.1%}) {tag}')
        print(f'{k:<44} {b:>10.3f} {c:>10.3f} {delta:>+9.1%}  {tag}')

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({'baseline_chapters': [r['chapter'] for r in pool],
                                   'base': base, 'current': cur, 'alerts': alerts},
                                  ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'JSON: {out}')

    if alerts:
        print(f'\n⚠ 越界 {len(alerts)} 项 ⇒ learn_v2 机械触发条件成立：'
              f'须生成候补池条目（signal_type=metric_breach）并附指标证据')
        for a in alerts:
            print(f'  · {a}')
        return EXIT_DRIFT
    print('\n✓ 无越界，指标在基线波动带内')
    return EXIT_OK


def cmd_list(args) -> int:
    root = Path(args.work_root)
    p = baseline_path(root)
    rows, bad = load_rows(p)
    if bad:
        print(f'✗ 基线文件有 {bad} 条坏行', file=sys.stderr)
        return EXIT_BASELINE_CORRUPT
    active = active_rows(rows)
    print(f'基线文件：{p}')
    print(f'总行数 {len(rows)} | 当前分段 record {len(active)} 行 | '
          f'reset 标记 {sum(1 for r in rows if r.get("type") == "reset")} 个')
    for r in rows:
        if r.get('type') == 'reset':
            print(f'  ── RESET {r.get("ts", "")}  {r.get("reason", "")}')
        else:
            n = len(r.get('metrics_snapshot') or {})
            print(f'  {r.get("chapter", "?"):<10} {r.get("ts", ""):<26} '
                  f'v{r.get("protocol_version") or "-":<10} {n} 指标')
    return EXIT_OK


def cmd_reset(args) -> int:
    root = Path(args.work_root)
    if not root.is_dir():
        print(f'✗ work-root 不存在：{root}', file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not args.confirm or not (args.reason or '').strip():
        print('✗ 基线重置必须同时给 --reason 与 --confirm（防静默重置掩盖漂移）',
              file=sys.stderr)
        return EXIT_INPUT_ERROR
    p = baseline_path(root)
    rows, bad = load_rows(p)
    if bad:
        print(f'✗ 基线文件有 {bad} 条坏行，拒绝在损坏状态上重置', file=sys.stderr)
        return EXIT_BASELINE_CORRUPT
    row = {'type': 'reset', 'ts': _now(), 'reason': args.reason.strip(),
           'protocol_version': args.protocol_version or '',
           'prior_records': len(active_rows(rows))}
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    print(f'✓ 已追加 reset 分段标记（旧 {row["prior_records"]} 行保留可审计，不再参与基线）')
    print(f'  理由：{row["reason"]}')
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description='指标基线存储与对比（append-only）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--work-root', required=True, help='WORK_ROOT 根目录')
    common.add_argument('--metrics-json', default=None,
                        help='复用已算好的 metrics JSON；不给则现场调 compute_metrics')

    p_rec = sub.add_parser('record', parents=[common], help='追加一章基线快照')
    p_rec.add_argument('--chapter', required=True, help='ch## 或 self-evo')
    p_rec.add_argument('--protocol-version', default='')
    p_rec.add_argument('--force', action='store_true', help='允许同 chapter 重复记录')

    p_cmp = sub.add_parser('compare', parents=[common], help='与 running mean 基线对比')
    p_cmp.add_argument('--window', type=int, default=5, help='取最近 N 章（默认 5）')
    p_cmp.add_argument('--threshold', type=float, default=0.20,
                       help='偏离告警阈值，默认 0.20（对应设计文档 >20%）')
    p_cmp.add_argument('--chapter', default='', help='当前章（从基线池中排除自身）')
    p_cmp.add_argument('--json', default=None, help='输出对比结果 JSON')

    p_lst = sub.add_parser('list', parents=[common], help='列出全部基线与 reset 分段')

    p_rst = sub.add_parser('reset', parents=[common], help='追加 reset 分段（不删历史）')
    p_rst.add_argument('--reason', required=True)
    p_rst.add_argument('--protocol-version', default='')
    p_rst.add_argument('--confirm', action='store_true')

    args = ap.parse_args()
    return {'record': cmd_record, 'compare': cmd_compare,
            'list': cmd_list, 'reset': cmd_reset}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
