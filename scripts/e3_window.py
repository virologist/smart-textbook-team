#!/usr/bin/env python3
"""e3_window.py — 熔断 E3 滑动窗口计数器（2026-11-04 诊断 M5 执行体）

问题背景
========
harness §4 定义熔断 Circuit Breaker：

    CLOSED ──E5/连续E3──▶ OPEN ──用户处置后──▶ HALF_OPEN ──探测成功──▶ CLOSED

「连续 E3」的判定规则（harness §4 evo-7 补）：

    同一 correlation_id 下，滑动窗口 = 最近 3 次成员任务中
    E3 出现 ≥2 次 → 判「连续 E3」触发 OPEN

但原文明确写着「计数器持久化在黑板 retries 字段旁（e3_window），
**由编排者维护**」——即靠人/模型手工记数。在长任务里：

  · 编排者可能忘记更新窗口
  · 窗口滑出逻辑靠人工判断，不精确
  · 熔断是最后一道安全闸，不能建立在「记得数」上

本脚本把窗口计数从「编排者记」变成「脚本记」。

用法
====
  # 记一次 E3（成员返回 E3 时调用）
  python3 scripts/e3_window.py --work-root $WORK_ROOT --correlation-id ch03 --record

  # 记一次非 E3（成功/正常推进时调用，用于滑动窗口）
  python3 scripts/e3_window.py --work-root $WORK_ROOT --correlation-id ch03 --record --outcome OK

  # 用户处置后进入 HALF_OPEN（放行 1 个探测任务）
  python3 scripts/e3_window.py --work-root $WORK_ROOT --correlation-id ch03 --probe

  # 只查状态（不记）
  python3 scripts/e3_window.py --work-root $WORK_ROOT --correlation-id ch03 --status

  # 列出所有章节的窗口状态
  python3 scripts/e3_window.py --work-root $WORK_ROOT --list

状态机（R1 2026-11-05 补齐三态，此前只实现两态）
==================================================
  CLOSED ──连续E3(窗口内≥2)──▶ OPEN ──用户处置(--probe)──▶ HALF_OPEN
                                  ▲                              │
                                  └──────探测失败───────────────┘
                                  HALF_OPEN ──探测成功──▶ CLOSED

  OPEN 期间禁止一切成员调度；HALF_OPEN 只放行 1 个探测任务。
  「用户处置」必须显式 `--probe`——编排者不得自行把 OPEN 降级，
  否则熔断就成了可绕过的软闸。

退出码
======
  exit 0  CLOSED      正常调度
  exit 1  OPEN        触发熔断 → 停止一切成员调度，保存现场，通知用户
  exit 2  HALF_OPEN   半开 → 只放 1 个探测任务
  exit 3  参数/环境错误
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# harness §4：滑动窗口 = 最近 3 次成员任务
WINDOW_SIZE = 3
# harness §4：E3 出现 ≥2 次 → 连续 E3 → OPEN
E3_THRESHOLD = 2

E3_WINDOW_FILE = 'e3-window.json'


def _path(work_root: Path) -> Path:
    return work_root / '运行态' / E3_WINDOW_FILE


def _load(work_root: Path) -> dict:
    p = _path(work_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(work_root: Path, data: dict) -> None:
    p = _path(work_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _is_e3(outcome: str) -> bool:
    """判定一次交付是否为 E3（门禁失败）。

    E3 的语义 = 门禁不通过，需人裁决。在 trace 的 outcome 取值里，
    对应 ERROR（执行失败）/ BLOCKED（被阻塞）/ PARTIAL（部分完成）。
    """
    o = str(outcome or '').strip().upper()
    return o in ('ERROR', 'BLOCKED', 'PARTIAL', 'E3')


def record(work_root: Path, correlation_id: str, outcome: str) -> int:
    """记录一次任务结果到 E3 滑动窗口，并判定熔断状态。

    R1（2026-11-05）修复真实缺陷：此前本函数只实现 CLOSED/OPEN **两态**，
    而 harness §4 的协议是三态：

        CLOSED ──E5/连续E3──▶ OPEN ──用户处置后──▶ HALF_OPEN ──探测成功──▶ CLOSED
                            │                        │
                            └──禁止一切调度────────探测失败──▶ OPEN

    原实现中 `HALF_OPEN` 与 `exit 2` 只写在 docstring 里、**从未实现** ⇒
    协议声明的三态与执行体行为不一致（属 check_declaration 模式 A 同类缺陷）。
    现补齐三态迁移：

      · 处于 OPEN 时收到「用户处置」标记（--probe）⇒ 进入 HALF_OPEN（exit 2）
      · HALF_OPEN 下探测任务成功（outcome 非 E3）⇒ 回 CLOSED（exit 0）
      · HALF_OPEN 下探测任务失败（outcome 为 E3）⇒ 回 OPEN（exit 1）
      · HALF_OPEN 只放行 1 个探测任务（超过 1 个仍按 OPEN 拒绝）

    「用户处置」用显式 `--probe` 标记——编排者不能在未经用户处置的情况下
    自行把 OPEN 降级为 HALF_OPEN，否则熔断就成了可绕过的软闸。
    """
    data = _load(work_root)
    win = data.get(correlation_id, [])
    is_e3 = _is_e3(outcome)

    # 探测任务：HALF_OPEN 只放行 1 个；超过 1 个按 OPEN 处理（不放行）
    probes = data.get('_probes', {}) if isinstance(data.get('_probes'), dict) else {}
    used_probes = int(probes.get(correlation_id, 0))

    prev_state = _load_state(work_root).get(correlation_id, {}).get('state', 'CLOSED')

    # ── HALF_OPEN 下记录结果 ⇒ 决定回退目标 ──
    if prev_state == 'HALF_OPEN':
        if is_e3:
            state = 'OPEN'          # 探测失败 → 回 OPEN
            probes[correlation_id] = used_probes + 1
        else:
            state = 'CLOSED'         # 探测成功 → 回 CLOSED（熔断恢复）
            probes[correlation_id] = 0
        win.append({'outcome': outcome or '', 'e3': is_e3, 'probe': True})
        win = win[-WINDOW_SIZE:]
        data[correlation_id] = win
        data['_probes'] = probes
        e3_count = sum(1 for w in win if w.get('e3'))
        _save(work_root, data)
        _save_state(work_root, data, correlation_id, state, e3_count)
        print(f'CORRELATION_ID={correlation_id}')
        print(f'WINDOW_SIZE={len(win)}  E3_COUNT={e3_count}  THRESHOLD={E3_THRESHOLD}')
        print(f'STATE={state}')
        if state == 'CLOSED':
            print(f'[熔断恢复] 探测任务成功 ⇒ {correlation_id} 回 CLOSED，恢复正常调度')
            return 0
        print(f'[熔断持续] 探测任务失败 ⇒ {correlation_id} 回 OPEN，继续禁止调度',
              file=sys.stderr)
        return 1

    win.append({'outcome': outcome or '', 'e3': is_e3})
    # 滑动窗口：只保留最近 WINDOW_SIZE 次
    win = win[-WINDOW_SIZE:]
    data[correlation_id] = win

    e3_count = sum(1 for w in win if w.get('e3'))
    triggered = e3_count >= E3_THRESHOLD

    state = 'OPEN' if triggered else 'CLOSED'
    data[correlation_id] = win
    # 状态另存一份，便于编排者直接读
    _save(work_root, data)
    _save_state(work_root, data, correlation_id, state, e3_count)

    print(f'CORRELATION_ID={correlation_id}')
    print(f'WINDOW_SIZE={len(win)}  E3_COUNT={e3_count}  THRESHOLD={E3_THRESHOLD}')
    print(f'STATE={state}')
    if triggered:
        print(f'CIRCUIT_OPEN=1')
        print(f'[熔断触发] {correlation_id} 最近 {len(win)} 次任务中 E3 出现 {e3_count} 次'
              f'（≥{E3_THRESHOLD}）——按 harness §4：停止一切成员调度，保存现场，'
              f'通知用户处置；处置后进入 HALF_OPEN 放 1 个探测任务', file=sys.stderr)
        return 1
    return 0


def probe(work_root: Path, correlation_id: str) -> int:
    """标记「用户已处置」⇒ OPEN → HALF_OPEN（只放 1 个探测任务）。

    必须显式调用（编排者不可自行降级熔断，否则熔断成为可绕过的软闸）。
    """
    data = _load(work_root)
    st = _load_state(work_root).get(correlation_id, {})
    state = st.get('state', 'CLOSED')
    if state != 'OPEN':
        print(f'当前状态 {state}，非 OPEN，无需进入 HALF_OPEN', file=sys.stderr)
        return 3
    probes = data.get('_probes', {}) if isinstance(data.get('_probes'), dict) else {}
    probes[correlation_id] = 0
    data['_probes'] = probes
    _save(work_root, data)
    win = data.get(correlation_id, [])
    e3_count = sum(1 for w in win if w.get('e3'))
    _save_state(work_root, data, correlation_id, 'HALF_OPEN', e3_count)
    print(f'CORRELATION_ID={correlation_id}')
    print(f'STATE=HALF_OPEN')
    print(f'[半开] 用户已处置 ⇒ 放行 1 个探测任务（探测成功回 CLOSED，失败回 OPEN）')
    return 2


def _state_path(work_root: Path) -> Path:
    return work_root / '运行态' / 'e3-state.json'


def _save_state(work_root: Path, data: dict, corr: str, state: str,
                e3_count: int) -> None:
    st = _load_state(work_root)
    st[corr] = {'state': state, 'e3_count': e3_count,
                'window': data.get(corr, [])}
    p = _state_path(work_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _load_state(work_root: Path) -> dict:
    p = _state_path(work_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def status(work_root: Path, correlation_id: str) -> int:
    data = _load(work_root)
    win = data.get(correlation_id, [])
    e3_count = sum(1 for w in win if w.get('e3'))
    st = _load_state(work_root).get(correlation_id, {})
    state = st.get('state') or ('OPEN' if e3_count >= E3_THRESHOLD else 'CLOSED')
    print(f'CORRELATION_ID={correlation_id}')
    print(f'WINDOW_SIZE={len(win)}  E3_COUNT={e3_count}  THRESHOLD={E3_THRESHOLD}')
    print(f'STATE={state}')
    for w in win:
        print(f"  outcome={w.get('outcome')!r} e3={w.get('e3')}"
              + ("  [probe]" if w.get('probe') else ''))
    if state == 'OPEN':
        return 1
    if state == 'HALF_OPEN':
        return 2
    return 0


def list_all(work_root: Path) -> int:
    data = _load(work_root)
    if not data:
        print('NO_WINDOWS')
        return 0
    states = _load_state(work_root)
    for corr in sorted(data):
        if corr.startswith('_'):
            continue
        win = data[corr]
        e3_count = sum(1 for w in win if w.get('e3'))
        state = states.get(corr, {}).get('state') or (
            'OPEN' if e3_count >= E3_THRESHOLD else 'CLOSED')
        print(f'{corr}  state={state}  e3={e3_count}/{len(win)}  '
              f'outcomes={[w.get("outcome") for w in win]}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='e3_window — 熔断 E3 滑动窗口计数')
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--correlation-id', default='')
    ap.add_argument('--record', action='store_true', help='记录一次任务结果')
    ap.add_argument('--outcome', default='', help='本次任务 outcome（决定是否算 E3）')
    ap.add_argument('--status', action='store_true', help='只查状态不记录')
    ap.add_argument('--probe', action='store_true',
                    help='标记「用户已处置」：OPEN → HALF_OPEN（放行 1 个探测任务）')
    ap.add_argument('--list', action='store_true', help='列出所有窗口')
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser().resolve()
    if not work_root.is_dir():
        print(f'WORK_ROOT 不存在: {work_root}', file=sys.stderr)
        return 3

    if args.list:
        return list_all(work_root)
    if not args.correlation_id:
        print('必须给 --correlation-id（或用 --list）', file=sys.stderr)
        return 3
    if args.probe:
        return probe(work_root, args.correlation_id)
    if args.record:
        return record(work_root, args.correlation_id, args.outcome)
    return status(work_root, args.correlation_id)


if __name__ == '__main__':
    sys.exit(main())
