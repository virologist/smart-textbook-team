#!/usr/bin/env python3
"""progress.py — 长任务续跑 checkpoint 写入与读取

工件路径:{WORK_ROOT}/运行态/progress.md
用途:章节跑完后被中断,重启时读此文件恢复 phase + 续 task_id。

状态机:章节生命周期由 13 态管线驱动,本工具记录已完成/待续/阻塞。
写入语义:append 模式(append-only),不覆盖历史(便于审计与回滚)。

用法:
  # 写入/更新一个 phase 完成状态
  python3 scripts/progress.py --work-root /path/to/work update \\
      --phase SPECIFY --status DONE \\
      --summary "design-bloom 已完成,Bloom 分层 + 块级 DAG 已写入 chapter_design.md"

  # 读取当前状态
  python3 scripts/progress.py --work-root /path/to/work show
"""
from __future__ import annotations
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PHASE_ORDER = [
    'BOOTSTRAP', 'INTAKE', 'CLARIFY', 'SPECIFY', 'RETRIEVE',
    'PRODUCE-R1', 'VERIFY-R1', 'PRODUCE-R2', 'VERIFY-R2',
    'PRODUCE-R3', 'VERIFY-R3', 'VERIFY-R4',
    'PROOFREAD', 'CONSOLIDATION', 'VISUALIZE', 'ASSEMBLE',
    'DELIVER', 'LEARN',
]


def progress_file(work_root: Path) -> Path:
    d = work_root / '运行态'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'progress.md'


def init_progress(work_root: Path, chapter: str, textbook: str, audience: str) -> Path:
    p = progress_file(work_root)
    if p.exists():
        return p
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    body = f"""# Progress · {chapter}

> 章节: {chapter} ｜ 教材: {textbook} ｜ 受众: {audience} ｜ 初始化: {ts}
> 续跑方式:重启后 `python3 scripts/progress.py --work-root $WORK_ROOT show` 查看当前 phase,
> 再 `team-lead: spawn 成员 -task_id={chapter}-<NEXT_PHASE>-state=resume`

## 阶段进度

| Phase | 状态 | 摘要 | 时间 |
|-------|------|------|------|
| BOOTSTRAP | DONE | 工作目录初始化 | {ts} |

## 阻塞清单 (H15 缺口)

（暂无）

## 下次恢复

```
spawn smart-textbook-team-team-lead
  → Phase A 续读此 progress.md
  → 进入下一个 phase
```
"""
    p.write_text(body, encoding='utf-8')
    return p


def update_phase(work_root: Path, phase: str, status: str, summary: str) -> Path:
    if phase not in PHASE_ORDER:
        raise ValueError(f'未知 phase: {phase}; 合法值: {PHASE_ORDER}')
    p = progress_file(work_root)
    if not p.exists():
        raise FileNotFoundError(f'progress.md 不存在: {p}; 请先 init')

    text = p.read_text(encoding='utf-8')
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    # 替换或追加该 phase 行
    pattern = re.compile(
        rf'^\| {re.escape(phase)} \| .*? \|.*? \|.*? \|$',
        re.MULTILINE,
    )
    new_row = f'| {phase} | {status} | {summary} | {ts} |'
    if pattern.search(text):
        text = pattern.sub(new_row, text)
    else:
        # 找到阶段表最后一行后插入
        m = re.search(r'(\n## 阻塞清单)', text)
        if m:
            text = text[:m.start()] + '\n' + new_row + text[m.start():]
        else:
            text += '\n' + new_row + '\n'

    # 阻塞清单追加
    if status in ('BLOCKED', 'BLOCKED_RESOLVED'):
        # 由调用方手动管理"## 阻塞清单"段
        pass

    p.write_text(text, encoding='utf-8')
    print(f'OK  progress[{phase} → {status}]')
    return p


def add_blocking(work_root: Path, item: str, source: str) -> Path:
    """H15 缺口登记"""
    p = progress_file(work_root)
    text = p.read_text(encoding='utf-8')
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    line = f'- [{ts}] {item} (来源: {source})'

    m = re.search(r'## 阻塞清单 \(H15 缺口\)\n\n（暂无）', text)
    if m:
        text = text.replace('（暂无）', line, 1)
    else:
        # 追加到阻塞清单末
        m = re.search(r'(## 阻塞清单 \(H15 缺口\)\n)', text)
        if m:
            insert_at = m.end()
            # 跳过现有项
            tail = text[insert_at:]
            end_match = re.search(r'\n## ', tail)
            if end_match:
                pos = insert_at + end_match.start()
                text = text[:pos] + line + '\n' + text[pos:]
            else:
                text += '\n' + line + '\n'

    p.write_text(text, encoding='utf-8')
    print(f'OK  blocking 登记: {item}')
    return p


def show(work_root: Path) -> int:
    p = progress_file(work_root)
    if not p.exists():
        print('(progress.md 不存在 — 章节未初始化)')
        return 1
    print(p.read_text(encoding='utf-8'))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-root', required=True)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_init = sub.add_parser('init', help='初始化 progress.md')
    p_init.add_argument('--chapter', required=True, help='如 ch06')
    p_init.add_argument('--textbook', required=True)
    p_init.add_argument('--audience', required=True)

    p_up = sub.add_parser('update', help='更新某 phase 状态')
    p_up.add_argument('--phase', required=True)
    p_up.add_argument('--status', required=True, choices=['DONE', 'IN_PROGRESS', 'BLOCKED', 'SKIPPED'])
    p_up.add_argument('--summary', required=True)

    p_blk = sub.add_parser('block', help='登记 H15 缺口')
    p_blk.add_argument('--item', required=True)
    p_blk.add_argument('--source', required=True)

    sub.add_parser('show', help='读取并打印 progress.md')

    args = ap.parse_args()
    wr = Path(args.work_root)

    if args.cmd == 'init':
        init_progress(wr, args.chapter, args.textbook, args.audience)
        print('OK  progress.md initialized')
    elif args.cmd == 'update':
        update_phase(wr, args.phase, args.status, args.summary)
    elif args.cmd == 'block':
        add_blocking(wr, args.item, args.source)
    elif args.cmd == 'show':
        return show(wr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
