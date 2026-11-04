#!/usr/bin/env python3
"""watchdog.py — 成员存活检测（E2 超时的执行体，2026-11-04 诊断 C1）

问题背景
========
harness §3 定义了错误分级 E1-E5 与升级链：

    E1 工具失败 → E2 可恢复（60 秒无进展）→ E3 门禁失败（终止待裁决）

E2 是这条链的枢纽——它决定「工具连续失败后是继续重试、换策略，
还是直接升级到 E3 交给人裁决」。但在此版本之前：

  · 全仓（scripts/）0 个 watchdog / heartbeat / 轮询 / alive 检测点
  · harness §7 自己也承认「三通道全盲只能靠 mtime 判死活」
  · record_trace.py 支持 `--outcome TIMEOUT`，但无任何程序写入该值

结果：E2 是一条**纯纸面阈值**。E1 失败后无法自动升级，
编排者只能靠人盯，或直接跳到 E3。异常处理链在中间环节断开。

本脚本做什么
============
为「某个 task_id 的成员是否还活着」提供一个**可机械判定**的答案。
两个独立通道，任一有进展即判定存活：

  通道 A（产物 mtime）：成员产出目录中任一文件的 mtime 变化
  通道 B（心跳文件）：成员主动写 运行态/.heartbeat/<task_id>.hb

通道 B 需要成员配合更新心跳；通道 A 是无侵入的兜底。
两者都不可用时，返回 UNKNOWN 而非误判 DEAD（宁可放过，不可误杀）。

输出（退出码即判定）
====================
  exit 0  ALIVE     有进展，成员正常推进
  exit 1  DEAD      超过阈值无进展 → 编排者应升级 E3
  exit 2  UNKNOWN   无法判定（无监控对象/通道全不可用）→ 需人工看
  exit 3  参数/环境错误

用法
====
  # 检查某任务是否还活着（默认阈值 60s，与 harness §3 一致）
  python3 scripts/watchdog.py --work-root $WORK_ROOT --task-id ch03-PRODUCE-R2

  # 只看心跳通道（成员没产出但可能还在思考）
  python3 scripts/watchdog.py --work-root $WORK_ROOT --task-id ch03-PRODUCE-R2 \
      --channel heartbeat

  # 注册一个受监控任务（记录 pid 与启动时刻，供后续判定）
  python3 scripts/watchdog.py --work-root $WORK_ROOT --task-id ch03-PRODUCE-R2 \
      --register --pid 12345

  # 心跳刷新（成员每轮调用）
  python3 scripts/watchdog.py --work-root $WORK_ROOT --task-id ch03-PRODUCE-R2 --heartbeat

  # 列出所有受监控任务及其状态
  python3 scripts/watchdog.py --work-root $WORK_ROOT --list
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

# 与 harness §3「E2 超时 = 60 秒无进展」一致
DEFAULT_TIMEOUT_S = 60
HEARTBEAT_DIR = '.heartbeat'
HANDLES_FILE = 'task-handles.json'


def _now() -> float:
    return time.time()


def _resolve_work_root(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def _heartbeat_path(work_root: Path, task_id: str) -> Path:
    return work_root / '运行态' / HEARTBEAT_DIR / f'{task_id}.hb'


def _handles_path(work_root: Path) -> Path:
    return work_root / '运行态' / HANDLES_FILE


def _load_handles(work_root: Path) -> dict:
    p = _handles_path(work_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_handles(work_root: Path, data: dict) -> None:
    p = _handles_path(work_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def register_task(work_root: Path, task_id: str, pid: int | None,
                  timeout_s: int) -> int:
    """登记受监控任务（pid + 启动时刻 + 阈值）"""
    handles = _load_handles(work_root)
    handles[task_id] = {
        'pid': pid,
        'started_at': _now(),
        'started_at_iso': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'timeout_s': timeout_s,
        'last_heartbeat': _now(),
        'state': 'RUNNING',
    }
    _save_handles(work_root, handles)
    # 登记即刷新一次心跳——避免刚 spawn 就被判 DEAD
    heartbeat(work_root, task_id)
    print(f'REGISTERED={task_id} pid={pid} timeout_s={timeout_s}')
    return 0


def heartbeat(work_root: Path, task_id: str) -> int:
    """刷新心跳（成员每轮调用）"""
    hb = _heartbeat_path(work_root, task_id)
    hb.parent.mkdir(parents=True, exist_ok=True)
    hb.write_text(time.strftime('%Y-%m-%dT%H:%M:%S%z'), encoding='utf-8')
    handles = _load_handles(work_root)
    if task_id in handles:
        handles[task_id]['last_heartbeat'] = _now()
        _save_handles(work_root, handles)
    print(f'HEARTBEAT={task_id} at={hb}')
    return 0


def _pid_alive(pid: int | None) -> bool | None:
    """检查进程是否存活。None = 未登记 pid（无法判定）。"""
    if not pid:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权限探针
    except OSError:
        return None


def _artifact_mtime(work_root: Path, task_id: str) -> float:
    """通道 A：受监控产物目录中最新 mtime。

    范围：工作区内除 运行态/ 之外的全部文件（成员产物落盘处）。
    粗粒度但零侵入——只要有产物更新即视为有进展。
    """
    latest = 0.0
    for root, dirs, files in os.walk(work_root):
        # 跳过运行态自身（trace 写入不算成员产出进展）
        dirs[:] = [d for d in dirs if d not in ('运行态', '.git', '__pycache__')]
        for fn in files:
            try:
                mt = os.path.getmtime(os.path.join(root, fn))
            except OSError:
                continue
            if mt > latest:
                latest = mt
    return latest


def check_task(work_root: Path, task_id: str, timeout_s: int,
               channel: str) -> int:
    """判定任务存活状态。退出码：0 ALIVE / 1 DEAD / 2 UNKNOWN"""
    handles = _load_handles(work_root)
    h = handles.get(task_id, {})
    task_timeout = int(h.get('timeout_s') or timeout_s)

    hb_path = _heartbeat_path(work_root, task_id)
    hb_mtime = hb_path.stat().st_mtime if hb_path.is_file() else 0.0
    art_mtime = _artifact_mtime(work_root, task_id) if channel in ('all', 'artifact') else 0.0

    now = _now()
    signals: list[dict] = []

    # 通道 B：心跳
    if hb_mtime:
        age = now - hb_mtime
        signals.append({'channel': 'heartbeat', 'age_s': round(age, 1),
                        'alive': age <= task_timeout})
    else:
        signals.append({'channel': 'heartbeat', 'age_s': None, 'alive': None,
                        'note': '无心跳文件（成员未调用 --heartbeat）'})

    # 通道 A：产物
    if channel in ('all', 'artifact'):
        if art_mtime:
            age = now - art_mtime
            signals.append({'channel': 'artifact', 'age_s': round(age, 1),
                            'alive': age <= task_timeout})
        else:
            signals.append({'channel': 'artifact', 'age_s': None, 'alive': None,
                            'note': '工作区无产物文件'})

    # 通道 C：进程（若登记了 pid）——最强信号
    pid = h.get('pid')
    pid_state = _pid_alive(pid)
    if pid_state is not None:
        signals.append({'channel': 'pid', 'pid': pid, 'alive': pid_state})

    judged = [s for s in signals if s.get('alive') is not None]
    if not judged:
        verdict = 'UNKNOWN'
        code = 2
    elif any(s['alive'] for s in judged):
        verdict = 'ALIVE'
        code = 0
    else:
        verdict = 'DEAD'
        code = 1

    # DEAD 时给出可执行的处置建议（不自动 kill——杀进程是破坏性操作，
    # 由编排者显式调用 --kill 决定）
    action = ''
    if verdict == 'DEAD':
        action = (f'按 harness §3「E2 超时 → 自动升级 E3」处置：'
                  f'记录 outcome=TIMEOUT 并升级 E3；'
                  f'若已重试 ≥3 次，按介入协议根因 C 拆步骤或 D 停机报用户')

    print(f'TASK_ID={task_id}')
    print(f'VERDICT={verdict}')
    print(f'TIMEOUT_S={task_timeout}')
    for s in signals:
        extra = f" pid={s['pid']}" if 'pid' in s else ''
        note = f" ({s['note']})" if s.get('note') else ''
        age = s.get('age_s')
        age_s = f"{age}s" if age is not None else '-'
        print(f"  channel={s['channel']}{extra} age={age_s} alive={s['alive']}{note}")
    if action:
        print(f'ACTION={action}')
    return code


def kill_task(work_root: Path, task_id: str) -> int:
    """显式终止僵死成员进程（破坏性操作，必须显式调用）"""
    handles = _load_handles(work_root)
    h = handles.get(task_id)
    if not h or not h.get('pid'):
        print(f'NO_PID={task_id} — 未登记 pid，无法终止（请人工处理）')
        return 2
    pid = int(h['pid'])
    try:
        os.kill(pid, signal.SIGTERM)
        print(f'TERMINATED={task_id} pid={pid} signal=SIGTERM')
        h['state'] = 'TERMINATED'
        _save_handles(work_root, handles)
        return 0
    except ProcessLookupError:
        print(f'ALREADY_GONE={task_id} pid={pid}')
        h['state'] = 'GONE'
        _save_handles(work_root, handles)
        return 0
    except OSError as e:
        print(f'KILL_FAILED={task_id} pid={pid} err={e}')
        return 3


def list_tasks(work_root: Path) -> int:
    handles = _load_handles(work_root)
    if not handles:
        print('NO_TASKS')
        return 0
    now = _now()
    for tid, h in sorted(handles.items()):
        age = now - float(h.get('last_heartbeat') or h.get('started_at') or now)
        alive = _pid_alive(h.get('pid'))
        print(f"{tid}  state={h.get('state')}  heartbeat_age={age:.0f}s  "
              f"pid={h.get('pid')}  pid_alive={alive}  timeout_s={h.get('timeout_s')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='watchdog — 成员存活检测（E2 超时执行体）')
    ap.add_argument('--work-root', required=True)
    ap.add_argument('--task-id', default='')
    ap.add_argument('--timeout-s', type=int, default=DEFAULT_TIMEOUT_S,
                    help=f'无进展阈值秒数（默认 {DEFAULT_TIMEOUT_S}，对齐 harness §3）')
    ap.add_argument('--channel', choices=['all', 'heartbeat', 'artifact'],
                    default='all', help='判定通道（默认 all）')
    ap.add_argument('--register', action='store_true', help='登记受监控任务')
    ap.add_argument('--pid', type=int, default=None)
    ap.add_argument('--heartbeat', action='store_true', help='刷新心跳（成员每轮调用）')
    ap.add_argument('--kill', action='store_true', help='终止僵死进程（破坏性，显式调用）')
    ap.add_argument('--list', action='store_true', help='列出所有受监控任务')
    args = ap.parse_args()

    work_root = _resolve_work_root(args.work_root)
    if not work_root.is_dir():
        print(f'WORK_ROOT 不存在: {work_root}', file=sys.stderr)
        return 3

    if args.list:
        return list_tasks(work_root)
    if not args.task_id:
        print('必须给 --task-id（或用 --list）', file=sys.stderr)
        return 3
    if args.register:
        return register_task(work_root, args.task_id, args.pid, args.timeout_s)
    if args.heartbeat:
        return heartbeat(work_root, args.task_id)
    if args.kill:
        return kill_task(work_root, args.task_id)
    return check_task(work_root, args.task_id, args.timeout_s, args.channel)


if __name__ == '__main__':
    sys.exit(main())
