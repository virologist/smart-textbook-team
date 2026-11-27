#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_concurrency_regression.py — 并发安全原语的负向回归用例（闭环 D13）

背景（`.harness-kb/mode2-log.md` 2026-11-20 D13 信号，2026-11-27 累计第 8 次）
=========================================================================
`e3_window` / `metrics_baseline` / `budget_guard` 三个脚本承载**运行态状态写入**，
它们在 v2.19.0 复测中修过三类真实并发缺陷：

  · R-B1：`e3_window` 的「读-改-写」原先在锁外 ⇒ 并发 record 互相覆盖丢记录
  · R-B3：`metrics_baseline` 的「查重→追加」原先是锁外查/锁内写（TOCTOU）
           ⇒ 并发 record 同章全部通过查重，写出 N 条重复行污染 running mean
  · R-B2：`budget_guard` 的 trace 读端原先静默丢弃坏行 ⇒ 分母偏小且不可观测

但**修复本身零回归用例**：全仓 tests/ 下无任何并发用例 ⇒ 这三个原语一旦被
再次改坏（锁被摘除、语义被放宽），**没有任何门禁会红**。本文件补上该缺口。

设计要点（四条，均为实测得出，不是想当然）
=========================================
1. **每个用例都配负控制**。只有正向断言的用例证明不了门禁有牙齿——断言可能
   恒真。负控制必须让**同一段判据**在「机制被破坏」时明确失败。

2. **负控制用沙箱副本，绝不改生产代码**。改真实包 + try/finally 还原的坑：
   进程被 SIGTERM 杀死时 finally 不执行，破坏样本会永久留在生产资产里
   （本仓已实际发生过，见 mode2-log 的 D16 条目）。本文件一律把整个
   `scripts/` 复制到 /tmp 沙箱下再改，物理上不可能污染生产资产。

3. **并发必须确定性，不能靠运气**。并发用例最易 flaky——「跑得够多总能碰上
   竞态」是错误做法（实测：去 flock 后单轮约 40% 概率凑巧只写 1 行 ⇒ 负控制
   时红时绿）。本文件的做法：
     · 跨进程用**文件屏障**（每个 worker 写标记文件，等标记数 == N 才进临界区）
     · 进程内用 `threading.Barrier` 同步起跑
     · 需要时**人为放宽竞态窗口**，且**正例与负控制注入同一个放宽**
       ⇒ 被测变量恒为「有没有锁」这**一个**

4. **产物放 /tmp + PID 隔离，不进 repo**。repo 扫描类门禁
   （check_domain_neutral / check_doc_consistency / check_md_links）会扫包内
   文件，产物进 repo 会污染它们。⚠ 仓库既有测试文件（tests/test_core_scripts.py
   等 9 个）统一约定**不用 pytest 的 tmp_path**（OneDrive 沙箱下 basetemp
   创建会被宿主拦截），本文件沿用同一约定：改用自建 /tmp 目录 + 原子唯一命名
   （`tempfile.mkdtemp`）。**必须显式传 --basetemp**：
       python3 -m pytest tests/test_concurrency_regression.py -q \
           --basetemp=$(mktemp -d) -p no:cacheprovider

5. **负控制绝不能污染测试进程**（本文件最隐蔽的坑，已实际踩过一次）。
   沙箱副本的模块顶层有 `sys.path.insert(0, <自己所在目录>)`
   （`metrics_baseline.py:48` / `e3_window.py:70`）⇒ 载入副本会把**沙箱目录
   顶到父进程 sys.path[0]**。而沙箱里放着**被破坏的** `trace_schema.py`
   ⇒ 任何**延迟 import** trace_schema 的代码都会命中破坏副本
   ⇒ 坏行计数静默从 1 变 0 ⇒ C1/C2/C4/D3 四个用例同时全红且**原因完全
   看不出来**（实测复现：延迟 import 到的 `__file__` 指向沙箱而非生产目录）。
   ⇒ 本文件用三道防线堵死：
     ① 载入副本时 `_isolated_sys_path()` 精确还原 sys.path；
     ② C4 的破坏探针跑在**独立子进程** + 独立 PYTHONPATH；
     ③ autouse fixture `_no_sandbox_leak` 在**每个用例前后**断言生产模块
        没被顶替 ⇒ 污染一旦发生，在**下一个**用例的 setup 阶段就红，
        并直接说出「哪个模块被哪个路径顶替」。

运行
====
    python3 -m pytest tests/test_concurrency_regression.py -q \
        --basetemp=$(mktemp -d) -p no:cacheprovider

⚠ 本文件内的并发用例全部使用确定性同步原语，**可重复通过**（验收要求 3/3
  连跑全绿；实测 6/6 + 5/5 连跑全绿，跨进程用例 0 次 flake）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import budget_guard  # noqa: E402
import e3_window  # noqa: E402
import metrics_baseline  # noqa: E402
import trace_schema  # noqa: E402

# ── 并发规模：足以暴露竞态，又不至于让单测过慢 ──────────────────────────
N_PROCS = 6          # 跨进程并发数
N_THREADS = 6        # 进程内并发线程数

# ── 竞态窗口放宽的屏障超时（正例与负控制同注入）──────────────────────────
# 0.5s 足以让「无 flock 时 N 个线程全部到齐 ⇒ 同步放行」必然发生；
# 「有 flock 时只有 1 个线程能到 ⇒ 屏障超时破裂」也只需 0.5s。
RACE_WINDOW = 0.5

# ── 屏障超时：超时必须记为失败，绝不静默通过 ────────────────────────────
BARRIER_TIMEOUT = 30.0

# ── 临时产物根目录（放 /tmp，绝不放 repo 内）──────────────────────────────
# 沿用 tests/test_stt_cli.py 的约定：/tmp 下的产物不会被 repo 扫描类门禁扫到。
_BASE = Path('/tmp/stt_test_concurrency_regression')


def _scratch_dir(tag: str) -> Path:
    """PID 隔离的临时目录（用完即删）。

    ⚠ 目录名必须**唯一且不复用**：`tempfile.mkdtemp` 保证原子唯一（不会撞名）。
      早期版本用 `f'{tag}_{pid}_{len(os.listdir(_BASE))}'` 拼名字——删目录后
      序号会回退 ⇒ 后面的用例可能复用**前面用例刚删掉的路径**⇒ 跨用例污染
      （实测表现为 C 组 4 个用例突然同时全红）。
    """
    _BASE.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f'stt_conc_{tag}_', dir=str(_BASE)))


@pytest.fixture()
def scratch():
    """每个用例一个独立临时目录（用完即删）。"""
    d = _scratch_dir('case')
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_sandbox_leak():
    """**每个用例前后**都断言：生产模块没被沙箱副本顶替。

    这是本文件跨用例污染的**最后一道防线**。真实事故（已复现）：沙箱副本
    顶层 `sys.path.insert(0, 沙箱目录)` 把沙箱顶到父进程 sys.path[0] ⇒
    延迟 import 的 `trace_schema` 命中**破坏副本** ⇒ 坏行计数静默变 0 ⇒
    C1/C2/C4/D3 四个用例同时全红且**原因完全看不出来**。

    放在 autouse 里（而非只放在 C 组）⇒ 污染一旦发生，在**下一个**用例的
    setup 阶段就红，并直接说出「哪个模块被哪个路径顶替」。
    """
    with _assert_production_modules_intact():
        yield
    with _assert_production_modules_intact():
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 负控制基础设施：把 scripts/ 复制到 /tmp 沙箱副本，只破坏副本
# ═══════════════════════════════════════════════════════════════════════════

def _sandbox_scripts(base: Path) -> Path:
    """把整个 scripts/ 复制到沙箱下，返回副本目录。

    ⚠ 必须**整目录**复制（而非只复制单个文件）：e3_window import progress、
    metrics_baseline import compute_metrics/_common——单文件副本会因兄弟模块
    解析不到而行为漂移。

    负控制必须在副本上改——改真实包再还原的「try/finally 还原法」在进程被杀时
    会留下永久污染（本仓历史教训，见 mode2-log 的 D16 条目）。
    """
    dst = base / 'sandbox' / 'scripts'
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SCRIPTS, dst, dirs_exist_ok=True)
    return dst


def _break_e3_window_lock(src: Path) -> None:
    """破坏 e3_window 副本的并发原语：拿掉 record/probe 的 `with _file_lock(...)`。

    精确复原 R-B1 修复前的状态（读-改-写无锁 ⇒ 并发丢记录）。

    ⚠ 两条纪律（均为实测踩过）：
      ① 必须**替换语句、保持缩进结构**——直接删掉两行会让函数体掏空 ⇒
         IndentationError。
      ② 改完必须校验「确实改动了」，否则负控制会静默空转（假负控制比没负控制
         更糟：它给人「已覆盖」的错觉）。
    """
    txt = src.read_text(encoding='utf-8')
    new = txt.replace(
        "    with _file_lock(_path(work_root)):\n"
        "        return _record_locked(work_root, correlation_id, outcome)",
        "    return _record_locked(work_root, correlation_id, outcome)")
    new = new.replace(
        "    with _file_lock(_path(work_root)):\n"
        "        return _probe_locked(work_root, correlation_id)",
        "    return _probe_locked(work_root, correlation_id)")
    assert new != txt, '负控制补丁未命中——e3_window 的 _file_lock 包裹段已变，需同步'
    src.write_text(new, encoding='utf-8')


def _break_metrics_baseline_flock(src: Path) -> None:
    """破坏 metrics_baseline 副本的并发原语：移除 fcntl.flock（查重+追加不互斥）。

    精确复原 R-B3 修复前的状态（查重 TOCTOU ⇒ 并发重复基线）。

    ⚠ 同样是「替换语句」而非删行，保持 try/finally 结构（删行会掏空块体）。
    """
    txt = src.read_text(encoding='utf-8')
    new = txt.replace("        fcntl.flock(f, fcntl.LOCK_EX)\n",
                      "        pass  # NEG: lock disabled\n")
    new = new.replace("            fcntl.flock(f, fcntl.LOCK_UN)\n",
                      "            pass  # NEG: lock disabled\n")
    assert new.count('NEG: lock disabled') == 2, '负控制补丁未命中两处 flock'
    src.write_text(new, encoding='utf-8')


def _break_trace_schema_bad_count(src: Path) -> None:
    """破坏 trace_schema 副本的坏行计数语义：坏行静默丢弃、不计数。

    精确复原 R-B2 修复前的状态（`except JSONDecodeError: continue`）。

    ⚠ 补丁必须**恰好命中一处** `bad += 1`（已核实全文件唯一）；命中多处说明
      源码形态变了 ⇒ 负控制失真，须报错而非放过。
    """
    txt = src.read_text(encoding='utf-8')
    assert txt.count('                bad += 1') == 1, \
        '负控制补丁未命中——trace_schema 的坏行计数形态已变（bad += 1 不再唯一）'
    src.write_text(txt.replace('                bad += 1',
                               '                pass  # NEG: bad count disabled'),
                   encoding='utf-8')


@contextlib.contextmanager
def _isolated_sys_path():
    """在上下文内隔离 `sys.path`，退出时**精确还原**。

    为什么必须有（实测踩过，症状是 C 组 4 个用例突然同时全红）：
      沙箱副本的模块顶层有 `sys.path.insert(0, <自己所在目录>)`
      （`metrics_baseline.py:48` / `e3_window.py:70`）⇒ 载入副本时会把
      **沙箱目录插到父进程 sys.path[0]**。而沙箱里放着**被破坏的**
      `trace_schema.py`（坏行计数已摘掉）⇒ 任何**延迟 import** trace_schema
      的代码都会加载到破坏副本 ⇒ 坏行计数变 0 ⇒ C1/C2/C4/D3 同时红。

    ⇒ 负控制载入副本期间必须把 `sys.path` 隔离，退出时还原。
    """
    saved = list(sys.path)
    try:
        yield
    finally:
        sys.path[:] = saved


@contextlib.contextmanager
def _assert_production_modules_intact():
    """上下文内断言：生产模块没被沙箱副本顶替。

    这是**第二道防线**：即使某条路径又把沙箱塞进了 sys.path，也要在**下一次
    断言之前**把「生产模块被顶替」这件事变成显式失败，而不是让坏行计数
    悄悄变成 0（那种失败极难定位——本仓已实际踩过一次）。
    """
    for name in ('trace_schema', 'e3_window', 'metrics_baseline', 'budget_guard'):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        origin = getattr(mod, '__file__', '') or ''
        if not origin.startswith(str(SCRIPTS)):
            raise AssertionError(
                f'生产模块 {name!r} 被沙箱副本顶替（__file__={origin!r}）'
                f'⇒ 负控制污染了测试进程（期望来源 {SCRIPTS}）')
    yield


@contextlib.contextmanager
def _widen_race_window(mod, n: int, timeout: float = RACE_WINDOW):
    """把 metrics_baseline 的「查重 → 追加」竞态窗口**人为放宽**。

    为什么需要（实测结论，非猜测）：
      cmd_record 的临界区结构是
          flock → load(查重) → current_metrics → append → unlock
      `current_metrics` 正好落在「查重已判完、尚未写入」之间 ⇒ 在此处卡住
      就能把「读到旧状态 → 写入」的错位窗口从微秒级放大到可控尺度。
      不放宽时，实测 6 线程去 flock 后**约 40% 的概率凑巧只写 1 行**
      ⇒ 负控制时红时绿 ⇒ flaky（这正是本仓上一版并发测试的真实翻车点）。

    实现：**超时受限的线程屏障**（不是 sleep）。
      · 无 flock 时：N 个线程全部到达屏障 ⇒ **同时**放行 ⇒ 读全部完成、
        写全部未发生 ⇒ 必然写出 N 行重复基线（确定性）。
      · 有 flock 时：临界区内只有 1 个线程能到达屏障 ⇒ 屏障超时破裂 ⇒
        该线程继续 ⇒ 语义不变（仍是「查重已判完、写入未开始」的时点）。
      用屏障而非 sleep，是因为 sleep 是**时间概率**（机器负载一变就翻车）；
      屏障是**状态同步**（负载再高也必然复现）。
      实测（15 次连跑）：有锁 15/15 得 (1 成功, 5 拒绝, 1 行)；
            无锁 15/15 得 (6 成功, 0 拒绝, 6 行) —— 两边都确定性。

    ⚠ 关键纪律：正例与负控制**注入同一个放宽** ⇒ 被测变量恒为
      「有没有 flock」这**一个**，放宽本身不改变判据语义。
    """
    original = mod.current_metrics
    barrier = threading.Barrier(n)

    def gated(*args, **kwargs):
        try:
            barrier.wait(timeout=timeout)
        except threading.BrokenBarrierError:
            # 有 flock 时只有 1 个线程能到达 ⇒ 超时破裂后放行（语义不变）
            pass
        return original(*args, **kwargs)

    mod.current_metrics = gated
    try:
        yield
    finally:
        mod.current_metrics = original


@contextlib.contextmanager
def _widen_e3_race_window(mod, n: int, timeout: float = RACE_WINDOW):
    """把 e3_window 的「读-改-写」竞态窗口**人为放宽**（与 _widen_race_window 同构）。

    为什么需要（实测结论，非猜测）：
      `_record_locked` 的结构是
          _load(读) → 改内存 → _save(写)
      竞态窗口在「读已完成、写未发生」之间 ⇒ 在**写盘前**卡住就能把错位
      窗口从微秒级放大到可控尺度。
      不放宽时，实测**跨平台 flaky**：macOS 本地 8/8 绿，但 GitHub Actions
      的 2 vCPU Linux runner 上各进程错开执行 ⇒ 反而每个都完整写入 1 条
      ⇒ 落盘窗口 3 条 ⇒ 负控制立不了红（A2/A6/D1 三例全红）。

    ⚠⚠ 为什么放宽点必须落在**写盘前**（`_save`）而不是读后（`_load`）：
      无锁时最终落盘是**最后一个写入者**的内容。若在读后同步：N 个线程都
      读到同一份旧状态 → 各自算出 1 条 → 但「谁最后写谁赢」⇒ 落盘条数取
      决于写入顺序，可能是 1 条也可能是 3 条 ⇒ 负控制 flaky。
      若在**写前**同步：N 个线程全部完成「读-改」后一起等 → 全部放行 → 全部
      写同一份「1 条」的内容 ⇒ 落盘**必然**是 1 条 ⇒ 负控制**必然**立红。

    实现：**超时受限的线程屏障**（不是 sleep）。
      · 无锁时：N 个线程全部到达屏障 ⇒ **同时**放行 ⇒ 必然互相覆盖（确定性）。
      · 有锁时：临界区内只有 1 个线程能到达屏障 ⇒ 屏障超时破裂 ⇒ 该线程继续
        ⇒ 语义不变（仍是「读已完成、写未发生」的时点）。

    ⚠ 关键纪律：正例与负控制**注入同一个放宽** ⇒ 被测变量恒为
      「有没有 _file_lock」这**一个**，放宽本身不改变判据语义。
    """
    original = mod._save
    barrier = threading.Barrier(n)

    def gated(*args, **kwargs):
        try:
            barrier.wait(timeout=timeout)
        except threading.BrokenBarrierError:
            # 有锁时只有 1 个线程能到达 ⇒ 超时破裂后放行（语义不变）
            pass
        return original(*args, **kwargs)

    mod._save = gated
    try:
        yield
    finally:
        mod._save = original


# ═══════════════════════════════════════════════════════════════════════════
# 跨进程并发装置：文件屏障 + 子进程 worker
# ═══════════════════════════════════════════════════════════════════════════

def _wait_barrier(bar_dir: Path, idx: int, n: int) -> bool:
    """等待 n 个进程就位。返回 False = 超时（调用方须记为失败而非静默通过）。

    跨进程屏障用「目录内标记文件数」实现：每个 worker 写一个自己的标记文件，
    等标记数 == N 才继续 ⇒ N 个进程**同时**进入临界区，不依赖 sleep 时序。
    """
    bar_dir.mkdir(parents=True, exist_ok=True)
    (bar_dir / str(idx)).write_text('1', encoding='utf-8')
    deadline = time.time() + BARRIER_TIMEOUT
    while len(list(bar_dir.iterdir())) < n:
        if time.time() > deadline:
            return False
        time.sleep(0.002)
    return True


_E3_WORKER = r'''
import os, sys, time, contextlib
from pathlib import Path
sys.path.insert(0, os.environ["STT_MODDIR"])
import e3_window as e3

if os.environ.get("STT_BREAK_LOCK") == "1":
    @contextlib.contextmanager
    def _nolock(path):
        yield
    e3._file_lock = _nolock

work_root = Path(sys.argv[1])
idx = int(sys.argv[2])
corr = sys.argv[3]
outcome = sys.argv[4]

bar = work_root / "barrier"
bar.mkdir(parents=True, exist_ok=True)
(bar / str(idx)).write_text("1", encoding="utf-8")
n = int(os.environ["STT_N"])
deadline = time.time() + 30
while len(list(bar.iterdir())) < n:
    if time.time() > deadline:
        sys.exit(9)          # 屏障超时 = 失败，绝不静默通过
    time.sleep(0.002)

# ★竞态窗口放宽（与 metrics_baseline 的 _widen_race_window 同构）：
#   e3_window 的「读-改-写」窗口在 `_load` 之后、`_save` 之前 ⇒ 把 **`_save`**
#   包一层**跨进程文件屏障**即可把「读已完成、写未发生」的错位窗口放大到
#   可控尺度。
#   ⚠⚠ 为什么放宽点必须落在**写盘前**（`_save`）而不是读后（`_load`）：
#     无锁时各进程「读-改-写」交错，最终落盘是**最后一个写入者**的内容。
#     若在读后同步：N 个进程都读到同一份旧状态 → 各自算出 1 条 → 但**谁最后写**
#     谁赢 ⇒ 落盘窗口条数取决于写入顺序，可能是 1 条（覆盖）也可能是 3 条
#     （若三者写入内容恰好相同）。实测：错开 200ms 时读后同步仍会假绿。
#     若在**写前**同步：N 个进程全部完成「读-改」后一起等 → 全部放行 → 全部
#     写同一份「1 条」的内容 ⇒ 落盘**必然**是 1 条（不是 3）⇒ 确定性覆盖，
#     负控制**必然**立红。
#   无锁时 N 个进程全部到达 ⇒ 同步放行 ⇒ 必然互相覆盖（确定性）；
#   有锁时只有 1 个进程能进临界区 ⇒ 其余进程在锁上排队 ⇒ 屏障超时后放行
#   （语义不变：仍是「读已完成、写未发生」的时点）。
#   ⚠ 没有这一步，负控制是**跨平台 flaky**：起跑屏障只保证「同时开始」，
#   不保证「同时到达读-改-写窗口」⇒ 在 CI 的 2 vCPU Linux runner 上各进程
#   错开执行，反而每个都完整写入了 1 条 ⇒ 落盘窗口有 3 条 ⇒ 负控制立不了红
#   （实测：macOS 本地 8/8 绿，GitHub Actions Linux 上 A2/A6/D1 三例全红）。
if os.environ.get("STT_RACE_WINDOW") == "1":
    _orig_save = e3._save
    def _gated_save(*a, **k):
        gate = work_root / "race_gate"
        gate.mkdir(parents=True, exist_ok=True)
        flag = gate / "timeout.flag"
        (gate / str(idx)).write_text("1", encoding="utf-8")
        deadline2 = time.time() + float(os.environ.get("STT_RACE_TMO", "2.0"))
        while not flag.exists() and len(list(gate.iterdir())) < n:
            if time.time() > deadline2:
                # 宣告「锁在起作用」⇒ 其余进程立即放行（不等满超时）
                flag.write_text("1", encoding="utf-8")
                break
            time.sleep(0.002)
        return _orig_save(*a, **k)
    e3._save = _gated_save

sys.exit(e3.record(work_root, corr, outcome))
'''

_MB_WORKER = r'''
import os, sys, time, argparse, fcntl
from pathlib import Path
sys.path.insert(0, os.environ["STT_MODDIR"])

if os.environ.get("STT_BREAK_FLOCK") == "1":
    fcntl.flock = lambda *a, **k: None      # NEG: 查重+追加不再互斥

import metrics_baseline as mb

work_root = Path(sys.argv[1])
idx = int(sys.argv[2])
chapter = sys.argv[3]
metrics_json = sys.argv[4]

bar = work_root / "barrier"
bar.mkdir(parents=True, exist_ok=True)
(bar / str(idx)).write_text("1", encoding="utf-8")
n = int(os.environ["STT_N"])
deadline = time.time() + 30
while len(list(bar.iterdir())) < n:
    if time.time() > deadline:
        sys.exit(9)
    time.sleep(0.002)

# 与进程内用例注入**同一个**竞态窗口放宽（见 _widen_race_window 文档）：
# 跨进程不能共享线程屏障 ⇒ 用**跨进程文件屏障**实现同一语义：
#   无 flock 时 N 个进程全部到达 ⇒ 同步放行（读全完成、写全未发生）；
#   有 flock 时只有 1 个进程能到 ⇒ 超时后放行（语义不变）。
_orig_current_metrics = mb.current_metrics
def _gated_current_metrics(*a, **k):
    gate = work_root / "race_gate"
    gate.mkdir(parents=True, exist_ok=True)
    (gate / str(idx)).write_text("1", encoding="utf-8")
    deadline2 = time.time() + 0.5
    while len(list(gate.iterdir())) < n:
        if time.time() > deadline2:
            break
        time.sleep(0.002)
    return _orig_current_metrics(*a, **k)
mb.current_metrics = _gated_current_metrics

args = argparse.Namespace(work_root=str(work_root), chapter=chapter,
                          metrics_json=metrics_json, protocol_version="2.5.0",
                          force=False)
sys.exit(mb.cmd_record(args))
'''


def _spawn(script: str, mod_dir: Path, work_root: Path, args: list[list[str]],
           env_extra: dict) -> list[int]:
    """并发拉起 N 个子进程执行 script，等全部结束后返回各自的退出码。"""
    env = dict(os.environ)
    env['STT_MODDIR'] = str(mod_dir)
    env['STT_N'] = str(len(args))
    env.update(env_extra)
    procs = [subprocess.Popen([sys.executable, '-c', script, str(work_root), *a],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for a in args]
    for p in procs:
        p.communicate()
    return [p.returncode for p in procs]


# ═══════════════════════════════════════════════════════════════════════════
# A. e3_window —— 并发 record 不丢记录（R-B1 的负向回归）
# ═══════════════════════════════════════════════════════════════════════════

def _e3_work_root(base: Path, name: str = 'wr') -> Path:
    root = base / name
    (root / '运行态').mkdir(parents=True, exist_ok=True)
    return root


def _e3_cids(root: Path) -> list:
    """读出 e3 窗口里实际落盘的 correlation_id（不含下划线开头的内部键）。"""
    p = root / '运行态' / 'e3-window.json'
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding='utf-8'))
    return sorted(k for k in data if not k.startswith('_'))


def _e3_snapshot(root: Path, corr: str = 'ch01') -> tuple[int, int, str | None]:
    """读回窗口与状态：返回 (窗口条数, E3 条数, 状态)。

    读不到（文件损坏/缺失）⇒ 返回 (-1, -1, None)——调用方据此判 FAIL，
    绝不把「读不出来」当成「没问题」放过。
    """
    win_file = root / '运行态' / 'e3-window.json'
    state_file = root / '运行态' / 'e3-state.json'
    try:
        data = json.loads(win_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return -1, -1, None
    win = data.get(corr, [])
    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))[corr]['state']
    except (OSError, ValueError, KeyError):
        state = None
    return len(win), sum(1 for w in win if w.get('e3')), state


def _e3_thread_record(root: Path, n: int, outcome: str = 'ERROR',
                      module=None) -> list[int]:
    """n 线程并发 record（同一 correlation_id）⇒ 返回各线程的调用结果。

    用 threading.Barrier 同步起跑：所有线程同时进入临界区 ⇒ 读-改-写必然交错
    （去锁时），因此负控制是**确定性**失败而非靠运气。
    """
    mod = module or e3_window
    barrier = threading.Barrier(n)
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=BARRIER_TIMEOUT)
            rc = mod.record(root, 'ch01', outcome)
        except BaseException:                       # noqa: BLE001 — 异常即失败信号
            rc = -1
        with lock:
            results.append(rc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=BARRIER_TIMEOUT + 30)
    return results


class TestE3WindowConcurrency:
    """A 组：e3_window 滑动窗口在并发下不得丢记录（R-B1 的负向回归）。"""

    def test_A1_multiprocess_same_cid_keeps_window_records(self, scratch):
        """A1（正例·进程·同 cid）：N 子进程并发 record ⇒ 窗口保留 WINDOW_SIZE 条。

        不变量：WINDOW_SIZE=3、E3_THRESHOLD=2 ⇒ N=6 次 E3 记录后，窗口内应
        保留 3 条、其中 3 条是 E3、状态应为 OPEN（连续 E3 达阈值）。
        """
        root = _e3_work_root(scratch)
        rcs = _spawn(_E3_WORKER, SCRIPTS, root,
                     [[str(i), 'ch01', 'ERROR'] for i in range(N_PROCS)],
                     {'STT_BREAK_LOCK': '0', 'STT_RACE_WINDOW': '1'})
        assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

        win_len, e3_count, state = _e3_snapshot(root)
        assert win_len == e3_window.WINDOW_SIZE, (
            f'跨进程并发 record 丢记录：窗口条数 {win_len} != 期望 '
            f'{e3_window.WINDOW_SIZE}（{N_PROCS} 次调用）')
        assert e3_count == e3_window.WINDOW_SIZE, (
            f'窗口内 E3 条数 {e3_count} != {e3_window.WINDOW_SIZE}（记录被覆盖而非追加）')
        assert state == 'OPEN', (
            f'状态 {state!r} != OPEN——{N_PROCS} 次并发 E3 记录后熔断器未触发'
            f'（并发丢记录会让熔断在最需要的场景静默失效）')

    def test_A2_multiprocess_same_cid_negative_control_breaks_lock(self, scratch):
        """A2（负控制·进程·同 cid）：**破坏副本的锁** ⇒ 同一条不变量必须 FAIL。

        这是本组的核心证据：证明 A1 不是「跑通就算过」的空转用例。
        负控制在**沙箱副本**上做（/tmp 下的 scripts/ 副本），生产代码零改动。
        """
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_e3_window_lock(sandbox / 'e3_window.py')

            root = _e3_work_root(scratch)
            rcs = _spawn(_E3_WORKER, sandbox, root,
                         [[str(i), 'ch01', 'ERROR'] for i in range(N_PROCS)],
                         {'STT_BREAK_LOCK': '1', 'STT_RACE_WINDOW': '1'})
            assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

            win_len, e3_count, state = _e3_snapshot(root)
            # 去锁 ⇒ 读-改-写交错 ⇒ 窗口必然少于 WINDOW_SIZE 条
            assert win_len < e3_window.WINDOW_SIZE, (
                f'负控制失效：去掉 _file_lock 后窗口仍有 {win_len} 条'
                f'（期望 < {e3_window.WINDOW_SIZE}）⇒ A1 的并发没真正发生'
                f'或锁本就没起作用')
            assert e3_count < e3_window.WINDOW_SIZE, (
                f'负控制失效：去锁后 E3 条数 {e3_count} 仍达阈值')
            assert state != 'OPEN', (
                f'负控制失效：去锁后熔断状态仍为 OPEN（{state!r}）'
                f'——并发丢记录会让熔断器静默失效，正是 R-B1 的病灶')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_A3_multiprocess_distinct_cids_all_persist(self, scratch):
        """A3（正例·进程·不同 cid）：N 子进程并发 record **不同 cid** ⇒
        落盘窗口里 N 个 cid 必须**全部存在**。

        与 A1 互补：A1 用**同一 cid** 验证「窗口不丢记录」（窗口容量 3，满了就
        截断）；本例用**不同 cid** 验证「不同键都不丢」——无锁时「读-改-写」
        会整体覆盖（丢 50–75% 的 cid），这是「键被覆盖」而非「窗口被截断」，
        两种观测点互补。
        """
        root = _e3_work_root(scratch, name='wr_distinct')
        rcs = _spawn(_E3_WORKER, SCRIPTS, root,
                     [[str(i), f'cid{i}', 'OK'] for i in range(N_PROCS)],
                     {'STT_BREAK_LOCK': '0'})
        assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

        got = _e3_cids(root)
        missing = [f'cid{i}' for i in range(N_PROCS) if f'cid{i}' not in got]
        assert not missing, (
            f'并发 record 丢失 {len(missing)}/{N_PROCS} 个 cid：{missing}'
            '（读-改-写被并发覆盖 ⇒ R-B1 病灶）')

    def test_A4_multiprocess_distinct_cids_negative_control_breaks_lock(self, scratch):
        """A4（负控制·进程·不同 cid）：副本去锁 ⇒ 必须丢 cid（不变量被破坏）。"""
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_e3_window_lock(sandbox / 'e3_window.py')

            root = _e3_work_root(scratch, name='wr_distinct_neg')
            rcs = _spawn(_E3_WORKER, sandbox, root,
                         [[str(i), f'cid{i}', 'OK'] for i in range(N_PROCS)],
                         {'STT_BREAK_LOCK': '1'})
            assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

            got = _e3_cids(root)
            missing = [f'cid{i}' for i in range(N_PROCS) if f'cid{i}' not in got]
            assert missing, (
                '负控制失效：去掉 _file_lock 后所有 cid 仍然存在'
                '⇒ A3 的并发没真正制造竞态，正向用例的「全部存在」是假绿')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_A5_threaded_same_cid_keeps_window_records(self, scratch):
        """A5（正例·线程·同 cid）：同进程内多线程并发 record ⇒ 窗口不丢记录。

        跨进程（A1）验证 flock 的跨进程语义；本例验证同进程内的互斥
        （`_file_lock` 用 fcntl.flock，同进程不同 fd 之间同样互斥——已实测）。
        """
        root = _e3_work_root(scratch, name='wr_thread')
        # ★注入竞态窗口放宽（与 A1 的跨进程版同构）：
        #   正例与负控制注入**同一个**放宽 ⇒ 被测变量恒为「有没有 _file_lock」
        with _widen_e3_race_window(e3_window, N_THREADS):
            results = _e3_thread_record(root, N_THREADS, 'ERROR')

        assert not any(rc == -1 for rc in results), (
            f'并发 record 抛异常（疑似状态文件写坏了）: {results}')
        win_len, e3_count, state = _e3_snapshot(root)
        assert win_len == e3_window.WINDOW_SIZE, (
            f'线程并发 record 丢记录：窗口条数 {win_len} != 期望 {e3_window.WINDOW_SIZE}')
        assert e3_count == e3_window.WINDOW_SIZE, (
            f'线程并发窗口内 E3 条数 {e3_count} != {e3_window.WINDOW_SIZE}')
        assert state == 'OPEN', f'线程并发后状态 {state!r} != OPEN'

    def test_A6_threaded_same_cid_negative_control_breaks_lock(self, scratch):
        """A6（负控制·线程·同 cid）：副本去锁 ⇒ 线程并发必须丢记录。

        ⚠ 线程维度的负控制会额外暴露一个**潜在**缺陷：`progress.py:187` 的
          `_atomic_write` 临时文件名只含 `os.getpid()`、**不含线程 id** ⇒
          同进程多线程并发写同一目标时撞同一个 tmp 名（实测抛
          `OSError: [Errno 5]`）。该缺陷**生产路径不可达**（`_atomic_write` 的
          5 个调用点全部在 `_file_lock` 内、锁内单线程），故本用例只断言
          「窗口记录没保住」这个不变量，不绑定具体异常形态。
        """
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_e3_window_lock(sandbox / 'e3_window.py')

            root = _e3_work_root(scratch, name='wr_thread_neg')
            broken = _broken_e3(sandbox)
            # ★与 A5 注入**同一个**竞态窗口放宽（见 _widen_e3_race_window 文档）
            with _widen_e3_race_window(broken, N_THREADS):
                _e3_thread_record(root, N_THREADS, 'ERROR', module=broken)

            win_len, e3_count, state = _e3_snapshot(root)
            assert win_len < e3_window.WINDOW_SIZE, (
                f'负控制失效：去锁后窗口仍有 {win_len} 条'
                f'（期望 < {e3_window.WINDOW_SIZE}）')
            assert state != 'OPEN', (
                f'负控制失效：去锁后熔断状态仍为 OPEN（{state!r}）')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_A7_negative_control_does_not_touch_production_code(self, scratch):
        """A7：负控制跑完后，生产代码**逐字节未变**（自证「只破坏副本」）。

        这是负控制的合法性前提：负控制若污染了生产代码，测试就成了自毁行为。
        """
        target = SCRIPTS / 'e3_window.py'
        before = target.read_bytes()
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_e3_window_lock(sandbox / 'e3_window.py')
            root = _e3_work_root(scratch, name='wr_selfcheck')
            with contextlib.suppress(Exception):
                _broken_e3(sandbox).record(root, 'ch01', 'ERROR')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        assert target.read_bytes() == before, '负控制污染了生产代码 scripts/e3_window.py！'


def _broken_e3(sandbox: Path):
    """从沙箱副本载入被破坏的 e3_window（独立 alias，避免污染真实模块缓存）。"""
    import importlib.util
    src = sandbox / 'e3_window.py'
    spec = importlib.util.spec_from_file_location('e3_window_broken', src)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules['e3_window_broken'] = mod
    # 副本顶层会 sys.path.insert(0, 沙箱目录) ⇒ 必须隔离，否则沙箱里的
    # 破坏版 trace_schema 会污染父进程的延迟 import（见 _isolated_sys_path）。
    with _isolated_sys_path():
        spec.loader.exec_module(mod)
    return mod


def _broken_mb(sandbox: Path):
    """从沙箱副本载入被破坏的 metrics_baseline（独立 alias）。"""
    import importlib.util
    src = sandbox / 'metrics_baseline.py'
    spec = importlib.util.spec_from_file_location('metrics_baseline_broken', src)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules['metrics_baseline_broken'] = mod
    # 副本顶层会 sys.path.insert(0, 沙箱目录) ⇒ 必须隔离（见 _isolated_sys_path）
    with _isolated_sys_path():
        spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# B. metrics_baseline —— 并发 record 不产生重复基线（R-B3 的负向回归）
# ═══════════════════════════════════════════════════════════════════════════

_BASE_METRICS = {'dispatch_hit_rate': 1.0, 'rework_rate': 0.10, 'avg_turns': 3.0}


def _mb_work_root(base: Path, name: str = 'wr') -> tuple[Path, str]:
    """建工作区 + metrics JSON 文件，返回 (work_root, metrics_json 路径)。"""
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    mj = root / 'metrics.json'
    mj.write_text(json.dumps(_BASE_METRICS, ensure_ascii=False), encoding='utf-8')
    return root, str(mj)


def _mb_rows(root: Path) -> list:
    """读出基线文件里的 record 行。"""
    p = root / '运行态' / 'metrics_baseline.jsonl'
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _mb_thread_record(root: Path, metrics_json: str, n: int,
                      chapter: str = 'ch01', module=None) -> list[int]:
    """n 线程并发 cmd_record（同一 chapter）⇒ 返回各线程退出码。"""
    mod = module or metrics_baseline
    barrier = threading.Barrier(n)
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        args = argparse.Namespace(work_root=str(root), chapter=chapter,
                                  metrics_json=metrics_json, protocol_version='2.5.0',
                                  force=False)
        try:
            barrier.wait(timeout=BARRIER_TIMEOUT)
            rc = mod.cmd_record(args)
        except BaseException:                       # noqa: BLE001
            rc = -1
        with lock:
            results.append(rc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=BARRIER_TIMEOUT + 30)
    return results


class TestMetricsBaselineConcurrency:
    """B 组：metrics_baseline 并发 record 不得写出重复基线（R-B3 的负向回归）。"""

    def test_B1_threaded_same_chapter_no_duplicate_rows(self, scratch):
        """B1（正例·线程·同章）：N 线程并发 record **同一 chapter** ⇒ 基线只有 1 行。

        不变量：cmd_record 在 flock 内做「load → 查重 → append」，因此同章并发
        只有 1 次成功（exit 0），其余 N-1 次被查重拒绝（exit 2 = INPUT_ERROR）。
        基线文件行数 == 1 ⇒ running mean 不会被同一章重复计数污染。
        """
        root, mj = _mb_work_root(scratch)
        # 正例与负控制注入**同一个**竞态窗口放宽（见 _widen_race_window 文档）
        with _widen_race_window(metrics_baseline, N_THREADS):
            results = _mb_thread_record(root, mj, N_THREADS, 'ch01')

        assert not any(rc == -1 for rc in results), f'并发 record 抛异常: {results}'
        assert results.count(metrics_baseline.EXIT_OK) == 1, (
            f'期望恰好 1 次成功写入，实际 {results.count(metrics_baseline.EXIT_OK)} 次'
            f'（退出码分布 {sorted(results)}）⇒ 并发写出了重复基线')
        assert results.count(metrics_baseline.EXIT_INPUT_ERROR) == N_THREADS - 1, (
            f'期望其余 {N_THREADS - 1} 次被查重拒绝，实际 {sorted(results)}')

        rows = _mb_rows(root)
        assert len(rows) == 1, (
            f'基线文件有 {len(rows)} 行，期望 1 行（重复基线会污染 running mean）')
        assert rows[0]['chapter'] == 'ch01'

    def test_B2_threaded_same_chapter_negative_control_breaks_flock(self, scratch):
        """B2（负控制·线程·同章）：副本去掉 fcntl.flock ⇒ 必须写出多行重复基线。

        这是 B1 的核心证据。R-B3 的病灶正是「查重在锁外 / 无锁 ⇒ TOCTOU」，
        去锁后 N 次并发全部通过查重 ⇒ N 行重复基线。
        """
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_metrics_baseline_flock(sandbox / 'metrics_baseline.py')
            broken = _broken_mb(sandbox)

            root, mj = _mb_work_root(scratch, name='wr_neg')
            # 与正例 B1 注入**同一个**竞态窗口放宽 ⇒ 被测变量只有「有没有 flock」
            with _widen_race_window(broken, N_THREADS):
                results = _mb_thread_record(root, mj, N_THREADS, 'ch01',
                                            module=broken)

            rows = _mb_rows(root)
            assert len(rows) > 1, (
                f'负控制失效：去掉 fcntl.flock 后基线仍只有 {len(rows)} 行'
                f'（退出码分布 {sorted(results)}）⇒ B1 的并发没真正发生')
            assert results.count(broken.EXIT_OK) == N_THREADS, (
                f'负控制失效：去锁后 {N_THREADS} 次并发全部通过查重'
                f'（成功 {results.count(broken.EXIT_OK)} 次）'
                f'——正是 R-B3 的 TOCTOU 重复基线缺陷')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_B3_multiprocess_same_chapter_no_duplicate_rows(self, scratch):
        """B3（正例·进程·同章）：N 子进程并发 record 同章 ⇒ 基线仍只有 1 行。"""
        root, mj = _mb_work_root(scratch, name='wr_mp')
        rcs = _spawn(_MB_WORKER, SCRIPTS, root,
                     [[str(i), 'ch01', mj] for i in range(N_PROCS)],
                     {'STT_BREAK_FLOCK': '0'})
        assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

        rows = _mb_rows(root)
        assert len(rows) == 1, (
            f'跨进程并发 record 写出 {len(rows)} 行基线，期望 1 行'
            f'（退出码分布 {sorted(rcs)}）')
        assert rows[0]['chapter'] == 'ch01'

    def test_B4_multiprocess_negative_control_breaks_flock(self, scratch):
        """B4（负控制·进程·同章）：副本去 flock ⇒ 跨进程并发写出多行重复基线。"""
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_metrics_baseline_flock(sandbox / 'metrics_baseline.py')

            root, mj = _mb_work_root(scratch, name='wr_mp_neg')
            rcs = _spawn(_MB_WORKER, sandbox, root,
                         [[str(i), 'ch01', mj] for i in range(N_PROCS)],
                         {'STT_BREAK_FLOCK': '1'})
            assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

            rows = _mb_rows(root)
            assert len(rows) > 1, (
                f'负控制失效：跨进程去 flock 后基线仍只有 {len(rows)} 行'
                f'（退出码分布 {sorted(rcs)}）')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_B5_threaded_distinct_chapters_all_persist(self, scratch):
        """B5（正例·线程·不同章）：并发记录**不同 chapter** ⇒ 一行都不能丢。

        这是 metrics_baseline 并发写入的另一条不变量：不同章各自 append，
        并发下必须全部落盘（无锁时会出现「互相覆盖 ⇒ 丢行」的同类缺陷）。
        """
        root, mj = _mb_work_root(scratch, name='wr_distinct')
        barrier = threading.Barrier(N_THREADS)
        results: list[int] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            args = argparse.Namespace(work_root=str(root), chapter=f'ch{i:02d}',
                                      metrics_json=mj, protocol_version='2.5.0',
                                      force=False)
            try:
                barrier.wait(timeout=BARRIER_TIMEOUT)
                rc = metrics_baseline.cmd_record(args)
            except BaseException:                   # noqa: BLE001
                rc = -1
            with lock:
                results.append(rc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=BARRIER_TIMEOUT + 30)

        assert not any(rc == -1 for rc in results), f'并发 record 抛异常: {results}'
        rows = _mb_rows(root)
        assert len(rows) == N_THREADS, (
            f'并发记录 {N_THREADS} 个不同 chapter，基线只剩 {len(rows)} 行'
            f'（退出码分布 {sorted(results)}）⇒ 并发写丢行')
        assert sorted(r['chapter'] for r in rows) == sorted(
            f'ch{i:02d}' for i in range(N_THREADS))


# ═══════════════════════════════════════════════════════════════════════════
# C. budget_guard —— trace 坏行不被静默吞掉（R-B2 的负向回归）
# ═══════════════════════════════════════════════════════════════════════════

def _write_trace(root: Path, lines: list) -> Path:
    (root / '运行态').mkdir(parents=True, exist_ok=True)
    p = root / '运行态' / 'trace.jsonl'
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return p


_GOOD_TRACE = json.dumps({'task_id': 't1', 'phase': 'PRODUCE-R1',
                           'tokens_in': 1000, 'tokens_out': 500,
                           'outcome': 'OK'}, ensure_ascii=False)
_BAD_TRACE = '{ this is not valid json'


class TestBudgetGuardBadLines:
    """C 组：trace 坏行必须显式计数，不得静默吞掉（R-B2 的负向回归）。"""

    def test_C1_bad_lines_counted_and_good_lines_kept(self, scratch):
        """C1（正例）：坏行必须被**显式计数**，且好行仍被计入。

        ⇒ 是「计数」不是「整份丢弃」——这是 R-B2 修复的准确语义。

        原缺陷（R-B2）：坏行静默丢弃 ⇒ 预算分母偏小且审计者无从察觉。
        """
        with _assert_production_modules_intact():
            root = scratch / 'work'
            good1 = json.dumps({'phase': 'PRODUCE', 'tokens_in': 100, 'tokens_out': 50})
            good2 = json.dumps({'phase': 'VERIFY', 'tokens_in': 200, 'tokens_out': 20})
            _write_trace(root, [good1, '{坏行截断', good2])

            result = budget_guard.compute_budget(root)
            assert result.get('bad_trace_lines') == 1, (
                f"坏行未被显式计数：bad_trace_lines={result.get('bad_trace_lines')}")
            assert result.get('total_tokens') == 370, (
                f"好行未被正确计入：total_tokens={result.get('total_tokens')}"
                f"（期望 150+220=370）")

    def test_C2_bad_lines_make_cli_exit_nonzero(self, scratch):
        """C2（正例）：坏行 ⇒ CLI 退出码抬一级（OK→1），「数据不完整」可感知。

        R-B2 的语义：坏行**不**直接判超限（那会把「日志坏了」误当「预算爆了」），
        但也不许静默——原本 OK 的结论抬到「需处置」退出码 1。
        """
        root = scratch / 'work'
        _write_trace(root, [_GOOD_TRACE, _BAD_TRACE])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / 'budget_guard.py'),
             '--work-root', str(root)], capture_output=True, text=True)
        assert r.returncode == 1, (
            f'坏行时退出码 {r.returncode} != 1（0 = 静默通过 = 预算结论失真而无人知晓）'
            f'\nstdout={r.stdout}\nstderr={r.stderr}')
        assert '坏行' in r.stderr, f'stderr 未提示坏行: {r.stderr}'

    def test_C3_clean_trace_exits_zero(self, scratch):
        """C3（反向例·对照）：**无坏行**时退出码必须是 0。

        没有这条对照，C2 的「退出码 != 0」就可能是恒真断言（空转用例）。
        """
        root = scratch / 'work'
        _write_trace(root, [_GOOD_TRACE, _GOOD_TRACE])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / 'budget_guard.py'),
             '--work-root', str(root)], capture_output=True, text=True)
        assert r.returncode == 0, (
            f'无坏行时退出码 {r.returncode} != 0\nstdout={r.stdout}\nstderr={r.stderr}')
        assert '坏行' not in r.stderr, f'无坏行却报坏行: {r.stderr}'

    def test_C4_negative_control_old_reader_swallows_bad_lines(self, scratch):
        """C4（负控制）：共享读端换成「旧语义：静默吞掉坏行」⇒ 坏行计数必须变 0。

        这是 C1 的核心证据：证明 C1 的坏行计数**来自** read_trace_lines 的计数
        语义，而不是碰巧数对了。

        ⚠ patch 点核实：budget_guard._load_traces 是**函数内 import** trace_schema，
        所以补丁必须打在**沙箱副本的 trace_schema.py** 上（打真实模块的属性
        不生效——函数内 import 会重新绑定；此处用副本 + 独立子进程解决）。
        """
        root = scratch / 'work_neg'
        good1 = json.dumps({'phase': 'PRODUCE', 'tokens_in': 100, 'tokens_out': 50})
        _write_trace(root, [good1, '{坏行截断'])

        # 用沙箱副本摘掉坏行统计：read_trace_lines 的 bad 累加改为不计数
        sandbox = _sandbox_scripts(scratch)
        _break_trace_schema_bad_count(sandbox / 'trace_schema.py')

        # 把沙箱注入 sys.path 首位，使 budget_guard 加载被改的 trace_schema
        # ⚠ 必须用**独立子进程 + 独立 PYTHONPATH**，不能在本进程里改 sys.path：
        #   本进程改 sys.path 会让沙箱里的破坏版 trace_schema 污染后续用例。
        probe = scratch / 'neg_probe.py'
        probe.write_text(
            'import sys, json\n'
            f'sys.path.insert(0, {str(sandbox)!r})\n'
            'from pathlib import Path\n'
            'import budget_guard\n'
            f'result = budget_guard.compute_budget(Path({str(root)!r}))\n'
            'print(json.dumps({"bad": result.get("bad_trace_lines"),\n'
            '                  "total": result.get("total_tokens")},'
            ' ensure_ascii=False))\n',
            encoding='utf-8')
        proc = subprocess.run([sys.executable, str(probe)],
                              capture_output=True, text=True, timeout=120,
                              env={**os.environ,
                                   'PYTHONPATH': f'{sandbox}{os.pathsep}'
                                                f'{os.environ.get("PYTHONPATH", "")}'})
        assert proc.returncode == 0, f"负控制子进程失败：{proc.stderr[-500:]}"
        payload = json.loads(proc.stdout.strip().splitlines()[-1])

        assert payload['bad'] == 0, (
            f"坏行计数未被摘掉（bad={payload['bad']}）⇒ 负控制无效")
        assert payload['total'] == 150, (
            f"好行仍应被计入（total={payload['total']}，期望 150）")

        # 对照：真实生产模块仍报坏行 ⇒ 证明补丁只落在副本上，未污染生产代码
        with _assert_production_modules_intact():
            _, restored_bad = budget_guard._load_traces(root)
        assert restored_bad == 1, f'还原后坏行计数 {restored_bad} != 1（补丁污染了生产代码）'

    def test_C5_concurrent_trace_appends_keep_every_line_intact(self, scratch):
        """C5（并发·trace 追加）：并发追加的 trace 行**不得半行/丢行**。

        record_trace.py 写 trace.jsonl 用「flock + append」；读端
        trace_schema.read_trace_lines 必须能读出全部行且无坏行。
        本例用**真实写端**（record_trace.py CLI）并发写入 N 条，再断言：
          · 行数 == N（一条不丢）
          · 坏行 == 0（没有半写行——半写行会被读端计成坏行）
          · 每行 task_id 齐全
          · 预算口径：token 完整计入（不因并发而少算）
        """
        root = scratch / 'wr'
        (root / '运行态').mkdir(parents=True, exist_ok=True)
        barrier = threading.Barrier(N_THREADS)
        errors: list[str] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            cmd = [sys.executable, str(SCRIPTS / 'record_trace.py'),
                   '--work-root', str(root), '--task-id', f't{i:02d}',
                   '--from', 'member', '--to', 'lead', '--type', 'RESULT',
                   '--outcome', 'OK', '--phase', 'PRODUCE-R1',
                   '--tokens-in', '1000', '--tokens-out', '500',
                   '--duration-ms', '10', '--start', '2026-11-27T00:00:00+00:00']
            try:
                barrier.wait(timeout=BARRIER_TIMEOUT)
                r = subprocess.run(cmd, capture_output=True, text=True)
            except BaseException as ex:              # noqa: BLE001
                with lock:
                    errors.append(f't{i:02d} 异常: {ex!r}')
                return
            if r.returncode != 0:
                with lock:
                    errors.append(f't{i:02d} rc={r.returncode} {r.stdout}{r.stderr}')

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=BARRIER_TIMEOUT + 30)

        assert not errors, f'并发写 trace 失败: {errors}'
        records, bad = trace_schema.read_trace_lines(root / '运行态' / 'trace.jsonl')
        assert bad == 0, f'并发写 trace 产生 {bad} 条半写行（读端计为坏行）'
        assert len(records) == N_THREADS, (
            f'并发写 trace 共 {N_THREADS} 条，读回只有 {len(records)} 条（丢行）')
        task_ids = {r.get('task_id') for r in records}
        assert task_ids == {f't{i:02d}' for i in range(N_THREADS)}, f'task_id 不齐: {task_ids}'

        r = budget_guard.compute_budget(root)
        assert r['total_tokens'] == N_THREADS * 1500, (
            f'总 token {r["total_tokens"]} != {N_THREADS * 1500}（并发写导致用量统计失真）')
        assert r['bad_trace_lines'] == 0, f'并发写后竟有 {r["bad_trace_lines"]} 条坏行'


# ═══════════════════════════════════════════════════════════════════════════
# D. 组装自证：负控制确实「立红」（否则上面各负控制可能整体空转）
# ═══════════════════════════════════════════════════════════════════════════

class TestNegativeControlIsNotVacuous:
    """D 组：把负控制本身当作被测对象。

    若负控制注入后正例仍然通过，说明**负控制是空的**（用例根本没在测并发），
    这比没有负控制更糟——它给人「已覆盖」的错觉。本组让这种情况显式失败。
    """

    def test_D1_e3_window_negative_control_assertion_actually_fails(self, scratch):
        """D1：去锁副本上，正例 A1 的那条不变量断言**必须** FAIL。

        直接跑 A1 的断言逻辑（断言 win_len == WINDOW_SIZE）在去锁副本上，
        必须抛 AssertionError；若不抛 ⇒ 负控制空转。
        """
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_e3_window_lock(sandbox / 'e3_window.py')
            broken = _broken_e3(sandbox)

            root = _e3_work_root(scratch, name='wr_d1')
            rcs = _spawn(_E3_WORKER, sandbox, root,
                         [[str(i), 'ch01', 'ERROR'] for i in range(N_PROCS)],
                         {'STT_BREAK_LOCK': '1', 'STT_RACE_WINDOW': '1'})
            assert not any(rc == 9 for rc in rcs), f'跨进程屏障超时: {rcs}'

            win_len, _, _ = _e3_snapshot(root)
            with pytest.raises(AssertionError):
                assert win_len == broken.WINDOW_SIZE, (
                    f'并发 record 丢记录：窗口条数 {win_len} != 期望 {broken.WINDOW_SIZE}')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_D2_metrics_baseline_negative_control_assertion_actually_fails(self, scratch):
        """D2：去 flock 副本上，正例 B1 的那条不变量断言**必须** FAIL。"""
        sandbox = _sandbox_scripts(scratch)
        try:
            _break_metrics_baseline_flock(sandbox / 'metrics_baseline.py')
            broken = _broken_mb(sandbox)

            root, mj = _mb_work_root(scratch, name='wr_d2')
            with _widen_race_window(broken, N_THREADS):
                _mb_thread_record(root, mj, N_THREADS, 'ch01', module=broken)

            rows = _mb_rows(root)
            with pytest.raises(AssertionError):
                assert len(rows) == 1, (
                    f'基线文件有 {len(rows)} 行，期望 1 行（重复基线会污染 running mean）')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_D3_read_trace_lines_reports_bad_count(self, scratch):
        """D3：坏行计数是 read_trace_lines 的**契约**（返回 (records, bad)）。"""
        with _assert_production_modules_intact():
            p = scratch / 'trace.jsonl'
            p.write_text('{"a":1}\n坏行\n{"b":2}\n', encoding='utf-8')

            records, bad = trace_schema.read_trace_lines(p)
        assert bad == 1, f"坏行计数应为 1，实际 {bad}"
        assert len(records) == 2, f"好行应被保留 2 条，实际 {len(records)}"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
