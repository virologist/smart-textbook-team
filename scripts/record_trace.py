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
    ap = argparse.ArgumentParser(description='trace.jsonl 写入器')
    ap.add_argument('--work-root', required=True, help='WORK_ROOT 根目录')
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--correlation-id', default='', help='缺省取 task_id 前缀(ch##)')
    ap.add_argument('--from', dest='src', required=True, help='from 成员 ID')
    ap.add_argument('--to', dest='dst', required=True, help='to 成员/编排 ID')
    ap.add_argument('--type', required=True, choices=['RESULT', 'BLOCK', 'ERROR', 'STATUS', 'NEED_INPUT'])
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
    args = ap.parse_args()

    # correlation_id 推断
    corr = args.correlation_id or args.task_id.split('-')[0]
    msg_id = args.msg_id or f"{args.task_id}-{args.src}-{int(datetime.now(timezone.utc).timestamp())}"

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


if __name__ == '__main__':
    sys.exit(main())
