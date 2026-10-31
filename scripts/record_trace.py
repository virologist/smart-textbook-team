#!/usr/bin/env python3
"""record_trace.py — 智能体团队 trace 写入器

每个成员完成 dispatch 后调用,append 一行 JSON 到 {WORK_ROOT}/运行态/trace.jsonl
schema 与 harness §6 对齐。

用法:
  python3 scripts/record_trace.py \\
    --work-root /path/to/work \\
    --task-id ch06-PRODUCE-R2 \\
    --from subject-writer \\
    --to smart-textbook-team-team-lead \\
    --type RESULT \\
    --outcome OK \\
    --duration-ms 128000 \\
    --tokens-in 8000 --tokens-out 12000 \\
    --artifacts "章节/ch06/draft.md"
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description='trace.jsonl 写入器 + tokens 对账器')
    sub = ap.add_subparsers(dest='cmd')

    # G6: tokens 对账子命令（确定性累加，替代手工 patch）
    p_tok = sub.add_parser('tokens', help='从 trace.jsonl 累加 tokens（编排者每 gate 后执行，patch 黑板 budget.tokens_used）')
    p_tok.add_argument('--work-root', required=True)

    ap.add_argument('--work-root', required=False, help='WORK_ROOT 根目录')
    ap.add_argument('--task-id', required=False)
    ap.add_argument('--correlation-id', default='', help='缺省取 task_id 前缀(ch##)')
    ap.add_argument('--from', dest='src', required=False, help='from 成员 ID')
    ap.add_argument('--to', dest='dst', required=False, help='to 成员/编排 ID')
    ap.add_argument('--type', required=False, choices=['RESULT', 'BLOCK', 'ERROR', 'STATUS', 'NEED_INPUT'])
    ap.add_argument('--msg-id', default='', help='缺省自动生成')
    ap.add_argument('--outcome', default='', help='OK / ERROR / BLOCKED / TIMEOUT')
    ap.add_argument('--duration-ms', type=int, default=0)
    ap.add_argument('--tokens-in', type=int, default=0)
    ap.add_argument('--tokens-out', type=int, default=0)
    ap.add_argument('--turns', type=int, default=0)
    ap.add_argument('--artifacts', default='', help='逗号分隔的产物路径')
    ap.add_argument('--blocking-open', default='', help='逗号分隔的 blocking 列表')
    ap.add_argument('--task-type', default='', help='router 标注的 task_type')
    ap.add_argument('--routing-conf', type=float, default=None, help='routing_confidence')
    ap.add_argument('--notes', default='', help='自由备注')
    ap.add_argument('--estimated', action='store_true',
                    help='tokens 为估算值(字符数÷3 口径)——平台未暴露真实用量时必须打此标,'
                         'compute_metrics 报告将标注「不可审计」(P2-6/LE-20261015-04)')
    ap.add_argument('--from-envelope', default=None,
                    help='成员回传信封 JSON 文件路径——传入后 from/to/task_id/type 以信封为准'
                         '(C14, 2026-10-30): CLI 自填值与信封不一致时以信封为准并 WARN,'
                         '消除「trace 与信封两张皮」;信封缺 from/to 时拒收(exit 2)')
    args = ap.parse_args()

    # ── G6: tokens 对账分支 ──
    if args.cmd == 'tokens':
        return tokens_summary(Path(args.work_root).expanduser())

    # 写入模式：必填项校验（原 required=True 语义保留）
    missing = [f for f, v in (('--work-root', args.work_root), ('--task-id', args.task_id),
                              ('--from', args.src), ('--to', args.dst), ('--type', args.type))
               if not v]
    if missing:
        ap.error(f'写入模式必填: {missing}（或使用 tokens 子命令: record_trace.py tokens --work-root …）')
        return 2

    # ── C14: 信封优先解析（2026-10-30）──────────────────────────────────
    env = None
    if args.from_envelope:
        env_path = Path(args.from_envelope).expanduser()
        if not env_path.is_file():
            print(f"[ERROR] 信封文件不存在: {env_path}", file=sys.stderr)
            return 2
        try:
            env = json.loads(env_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            print(f"[ERROR] 信封不是合法 JSON: {e}", file=sys.stderr)
            return 2
        missing = [k for k in ('from', 'to') if not env.get(k)]
        if missing:
            print(f"[ERROR] 信封缺必填字段 {missing} ——来源不可验证,按不可信回传拒收"
                  f"(harness §安全对账)", file=sys.stderr)
            return 2

    # correlation_id 推断
    corr = args.correlation_id or args.task_id.split('-')[0]
    msg_id = args.msg_id or f"{args.task_id}-{args.src}-{int(datetime.now(timezone.utc).timestamp())}"

    # 信封字段覆盖（C14: trace 与信封同源；不一致以信封为准并 WARN）
    if env:
        overrides = {}
        if env.get('from') and env['from'] != args.src:
            overrides['from'] = f"{args.src} → {env['from']}"
        if env.get('to') and env['to'] != args.dst:
            overrides['to'] = f"{args.dst} → {env['to']}"
        if env.get('task_id') and env['task_id'] != args.task_id:
            overrides['task_id'] = f"{args.task_id} → {env['task_id']}"
        if env.get('type') and env['type'] != args.type:
            overrides['type'] = f"{args.type} → {env['type']}"
        for k, v in overrides.items():
            print(f"[WARN] 信封与 CLI 自填不一致（{k}: {v}）——以信封为准", file=sys.stderr)
        args.src = env['from']
        args.dst = env['to']
        args.task_id = env.get('task_id') or args.task_id
        if env.get('type') in ('RESULT', 'BLOCK', 'ERROR', 'STATUS', 'NEED_INPUT'):
            args.type = env['type']
        corr = env.get('correlation_id') or corr

    rec = {
        'msg_id': msg_id,
        'task_id': args.task_id,
        'correlation_id': corr,
        'from': args.src,
        'to': args.dst,
        'type': args.type,
        'outcome': args.outcome,
        'duration_ms': args.duration_ms,
        'tokens_in': args.tokens_in,
        'tokens_out': args.tokens_out,
        'turns': args.turns,
        'artifacts': [a.strip() for a in args.artifacts.split(',') if a.strip()],
        'blocking_open': [b.strip() for b in args.blocking_open.split(',') if b.strip()],
        'task_type': args.task_type,
        'routing_confidence': args.routing_conf,
        'notes': args.notes,
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    if args.estimated:
        rec['estimated'] = True

    # 路径
    trace_dir = Path(args.work_root) / '运行态'
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_file = trace_dir / 'trace.jsonl'

    # 原子写入（fcntl flock）
    try:
        import fcntl
    except ImportError:
        fcntl = None

    line = json.dumps(rec, ensure_ascii=False) + '\n'

    with open(trace_file, 'a', encoding='utf-8') as f:
        if fcntl:
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
            except (OSError, AttributeError):
                pass
        f.write(line)
        f.flush()
        if fcntl:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except (OSError, AttributeError):
                pass

    print(f'OK  trace[{args.task_id}] → {trace_file}')
    return 0


def tokens_summary(work_root: Path) -> int:
    """G6（2026-10-31）：tokens_used 脚本化对账——从 trace.jsonl 确定性累加。

    此前 harness §2 要求编排者「每 gate 后按 trace 累加 patch budget.tokens_used」，
    纯靠手工执行 → evo-16 实证 tokens_used 全章停留初值（死字段），80K 硬上限永不触发。
    现提供确定性子命令：编排者每 gate 后执行
      `python3 scripts/record_trace.py tokens --work-root $WORK_ROOT`
    将输出值 patch 进黑板 budget.tokens_used（或直接比对告警）。
    estimated 行（成员自报、不可审计）单列统计，供报告标注。
    """
    trace_file = work_root / '运行态' / 'trace.jsonl'
    if not trace_file.is_file():
        print(f'WARN  trace.jsonl 不存在: {trace_file}（0 任务记录——先跑任务再对账）',
              file=sys.stderr)
        print('TOKENS_USED=0')
        print('TOKENS_ESTIMATED=0')
        return 0
    total = estimated = 0
    with open(trace_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # 坏行跳过（原子写入下不应出现，防御）
            tin = int(rec.get('tokens_in') or 0)
            tout = int(rec.get('tokens_out') or 0)
            total += tin + tout
            if rec.get('estimated'):
                estimated += tin + tout
    print(f'TOKENS_USED={total}')
    print(f'TOKENS_ESTIMATED={estimated}')
    if estimated:
        print(f'WARN  其中 {estimated} tokens 来自 estimated 行（成员自报，不可审计）',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
