#!/usr/bin/env python3
"""progress.py — 长任务续跑 checkpoint 写入与读取

工件路径:{WORK_ROOT}/运行态/progress.md
用途:章节跑完后被中断,重启时读此文件恢复 phase + 续 task_id。

状态机:章节生命周期由 13 态管线驱动,本工具记录已完成/待续/阻塞。
写入语义:按 phase 行 upsert(同 phase 更新状态/摘要/时间,不新增行);真正的 append-only 审计流是 trace.jsonl。init 幂等:文件已存在且章节一致时直接返回(不覆盖);章节不一致则 exit 2 硬失败(防止多章串档)。

状态取值:DONE / IN_PROGRESS / BLOCKED / BLOCKED_RESOLVED / SKIPPED。
  BLOCKED_RESOLVED = 该 phase 曾阻塞、现已解除,阶段可继续推进;
  它只改阶段行状态,不自动清"## 阻塞清单"(清哪一条由人判定)。
  (2026-10-29 修复:此前 CLI choices 未收录该值 → 该分支是死代码,阻塞登记后无法标解除)

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
    'PRODUCE-R3', 'VERIFY-R3', 'VERIFY-R4', 'VERIFY-R5',
    'PROOFREAD', 'CONSOLIDATION', 'VISUALIZE', 'ASSEMBLE',
    'DELIVER', 'LEARN',
]

# ── D-6 修复（2026-10-30 批次 B）─────────────────────────────────────────
# pipeline skill §门禁3 明确要求「门禁 3 结论记入 运行态/progress.md 的
# **PRODUCE 行**摘要」，但 PHASE_ORDER 只有细粒度的 PRODUCE-R1/R2/R3，
# 实跑 `update --phase PRODUCE` → `ValueError: 未知 phase`
# → **门禁 3 的结论在协议层面无处可写**（结论落不了盘 = 门禁不可审计）。
#
# 现补粗粒度别名：PRODUCE/VERIFY 视为「该阶段当前轮次」的别名，
# 映射到该阶段**最后一个**轮次（PRODUCE → PRODUCE-R3，VERIFY → VERIFY-R5），
# 使「记入 PRODUCE 行」的协议语义可执行。
# VERIFY-R5（2026-10-31 E1 补）：R5 质量评分轮此前无态——examiner 收尾
# update --phase VERIFY-R5 直接报错，R5 结论无处落盘；VERIFY 别名同步改指 R5。
PHASE_ALIAS = {
    'PRODUCE': 'PRODUCE-R3',
    'VERIFY': 'VERIFY-R5',
}


def progress_file(work_root: Path) -> Path:
    d = work_root / '运行态'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'progress.md'


def init_progress(work_root: Path, chapter: str, textbook: str, audience: str) -> Path:
    p = progress_file(work_root)
    if p.exists():
        existing = p.read_text(encoding="utf-8")
        if f"Progress · {chapter}" not in existing:
            # P17 修复(2026-10-29):原实现只 WARN 后 return,调用方误以为 init 成功,
            # 随后 show 仍返回旧章 → 同一 WORK_ROOT 跑多章必然串档。改为硬失败。
            m = re.search(r'^# Progress · (\S+)', existing, re.M)
            cur = m.group(1) if m else '(未知)'
            print(
                f"ERROR  progress.md 已存在且章节不符:现有={cur} 请求={chapter}。"
                f"同一 WORK_ROOT 只服务一章;换章请另建 WORK_ROOT 或先归档旧文件。",
                file=sys.stderr)
            sys.exit(2)
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
    # D-6：粗粒度别名（PRODUCE/VERIFY）先解析为该阶段当前轮次
    phase = PHASE_ALIAS.get(phase, phase)
    if phase not in PHASE_ORDER:
        raise ValueError(f'未知 phase: {phase}; 合法值: {PHASE_ORDER}'
                         f'（别名: {sorted(PHASE_ALIAS)}）')
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

    # 阻塞清单:由调用方用 `block` 子命令 / 手工维护"## 阻塞清单"段,此处不自动增删。
    # BLOCKED_RESOLVED(2026-10-29 可达性修复)= 该 phase 曾阻塞、现已解除:
    # 语义是"阶段状态可恢复推进",不自动改阻塞清单(解除哪一条由人判定,避免误清)。
    if status in ('BLOCKED', 'BLOCKED_RESOLVED'):
        pass

    p.write_text(text, encoding='utf-8')
    print(f'OK  progress[{phase} → {status}]')
    return p


def add_blocking(work_root: Path, item: str, source: str) -> Path:
    """H15 缺口登记"""
    return _mutate_blocking(work_root, item, source, resolve=False)


def resolve_blocking(work_root: Path, item: str, note: str = '') -> Path:
    """H15 缺口解除（G4 修复 2026-10-31：此前只有 block 无 resolve——
    回填复核后阻塞无法机械清零，progress 残留清单致续跑编排者反复补检索，螺旋只进不出）。

    匹配规则：item 与已有条目**精确子串匹配**（按登记时间倒序取最新一条命中项），
    就地改写为 RESOLVED 行（保留审计痕迹，不物理删除）。
    """
    return _mutate_blocking(work_root, item, note, resolve=True)


def _mutate_blocking(work_root: Path, item: str, source: str, resolve: bool) -> Path:
    p = progress_file(work_root)
    text = p.read_text(encoding='utf-8')
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    if not resolve:
        line = f'- [{ts}] {item} (来源: {source})'
        m = re.search(r'## 阻塞清单 \(H15 缺口\)\n\n（暂无）', text)
        if m:
            text = text.replace('（暂无）', line, 1)
        else:
            m = re.search(r'(## 阻塞清单 \(H15 缺口\)\n)', text)
            if m:
                insert_at = m.end()
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

    # resolve 分支：找含 item 子串的最新未解除行，追加 RESOLVED 标记
    lines = text.splitlines(keepends=True)
    hit_idx = None
    for i in range(len(lines) - 1, -1, -1):
        l = lines[i]
        if l.strip().startswith('- [') and item in l and 'RESOLVED' not in l:
            hit_idx = i
            break
    if hit_idx is None:
        print(f'ERROR  未找到可解除的阻塞项（item 子串不匹配或已 RESOLVED）: {item}',
              file=sys.stderr)
        sys.exit(2)
    lines[hit_idx] = lines[hit_idx].rstrip('\n') + f' → RESOLVED [{ts}] {source}\n'
    p.write_text(''.join(lines), encoding='utf-8')
    print(f'OK  blocking 解除: {item}')
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
    p_up.add_argument('--status', required=True, choices=[
        'DONE', 'IN_PROGRESS', 'BLOCKED', 'BLOCKED_RESOLVED', 'SKIPPED'])
    p_up.add_argument('--summary', required=True)

    p_blk = sub.add_parser('block', help='登记 H15 缺口')
    p_blk.add_argument('--item', required=True)
    p_blk.add_argument('--source', required=True)

    p_res = sub.add_parser('resolve', help='解除 H15 缺口（G4：回填复核后机械清零，防螺旋死锁）')
    p_res.add_argument('--item', required=True, help='登记时的 item 子串')
    p_res.add_argument('--note', default='回填复核通过', help='解除依据（如：检索已回填并复核）')

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
    elif args.cmd == 'resolve':
        resolve_blocking(wr, args.item, args.note)
    elif args.cmd == 'show':
        return show(wr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
