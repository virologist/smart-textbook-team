#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_metrics_baseline.py — 指标基线存储与对比的回归测试（2026-11-04 B2 批次）

补 Q3「指标-改进闭环缺失」。验收重点：
  ① append-only 与幂等（重复 chapter 会污染 running mean ⇒ 必须拒绝）
  ② compare 的 delta / 越界告警 / 红线判定
  ③ reset 分段：旧行保留可审计但不参与基线（严禁静默重置）
  ④ 坏行不可静默（exit 3）
  ⑤ 退出码契约 0/1/2/3
  ⑥ 反向例：调高阈值后同一场景必须翻绿 ⇒ 证明告警不是恒真断言

运行：python3 -m pytest tests/test_metrics_baseline.py -q
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import metrics_baseline as mb  # noqa: E402


@pytest.fixture()
def work_root():
    """临时工作区（不用 pytest tmp_path：OneDrive 沙箱下 basetemp 创建会被拦截）"""
    d = tempfile.mkdtemp(prefix='stt_mb_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_cli(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / 'metrics_baseline.py'), *extra],
        capture_output=True, text=True)


def metrics_file(root: Path, name: str, values: dict) -> str:
    p = root / name
    p.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
    return str(p)


def record(root: Path, chapter: str, mj: str, *, force=False):
    cmd = ['record', '--work-root', str(root), '--chapter', chapter,
           '--metrics-json', mj, '--protocol-version', '2.5.0']
    if force:
        cmd.append('--force')
    return run_cli(*cmd)


BASE = {'dispatch_hit_rate': 1.0, 'rework_rate': 0.10,
        'blocking_pct': 0.02, 'avg_turns': 3.0,
        'product_quality': {'structure_rate': 1.0, 'label_rate': 1.0}}


# ── 1. record：append-only 与幂等 ───────────────────────────────────────

class TestRecord:
    def test_T1_first_record_writes_one_line(self, work_root):
        mj = metrics_file(work_root, 'm.json', BASE)
        r = record(work_root, 'ch01', mj)
        assert r.returncode == mb.EXIT_OK, r.stdout + r.stderr
        rows, bad = mb.load_rows(mb.baseline_path(work_root))
        assert bad == 0 and len(rows) == 1
        assert rows[0]['chapter'] == 'ch01'
        assert 'product_quality.structure_rate' in rows[0]['metrics_snapshot']

    def test_T2_append_only_two_chapters(self, work_root):
        mj = metrics_file(work_root, 'm.json', BASE)
        assert record(work_root, 'ch01', mj).returncode == 0
        assert record(work_root, 'ch02', mj).returncode == 0
        rows, _ = mb.load_rows(mb.baseline_path(work_root))
        assert [r['chapter'] for r in rows] == ['ch01', 'ch02']

    def test_T3_duplicate_chapter_is_rejected(self, work_root):
        """重复记录会让 running mean 被同一章重复计数 ⇒ 默认拒绝"""
        mj = metrics_file(work_root, 'm.json', BASE)
        record(work_root, 'ch01', mj)
        r = record(work_root, 'ch01', mj)
        assert r.returncode == mb.EXIT_INPUT_ERROR, r.stdout + r.stderr
        rows, _ = mb.load_rows(mb.baseline_path(work_root))
        assert len(rows) == 1, '拒绝重复时不得追加行'

    def test_T4_force_allows_duplicate_but_is_explicit(self, work_root):
        mj = metrics_file(work_root, 'm.json', BASE)
        record(work_root, 'ch01', mj)
        assert record(work_root, 'ch01', mj, force=True).returncode == 0
        rows, _ = mb.load_rows(mb.baseline_path(work_root))
        assert len(rows) == 2

    def test_T5_bad_chapter_format(self, work_root):
        mj = metrics_file(work_root, 'm.json', BASE)
        r = record(work_root, '第一章', mj)
        assert r.returncode == mb.EXIT_INPUT_ERROR

    def test_T6_missing_work_root(self, work_root):
        r = run_cli('record', '--work-root', str(work_root / 'nope'),
                    '--chapter', 'ch01', '--metrics-json', 'x')
        assert r.returncode == mb.EXIT_INPUT_ERROR


# ── 2. compare：delta / 越界 / 红线 ─────────────────────────────────────

class TestCompare:
    def test_T7_no_baseline_is_not_drift(self, work_root):
        mj = metrics_file(work_root, 'm.json', BASE)
        r = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj)
        assert r.returncode == mb.EXIT_OK, r.stdout + r.stderr
        assert '无基线记录' in r.stdout

    def test_T8_20pct_drop_triggers_drift(self, work_root):
        """基线 1.0 → 当前 0.70（-30%）应越界且 exit 1"""
        mj_base = metrics_file(work_root, 'base.json', BASE)
        assert record(work_root, 'ch01', mj_base).returncode == 0
        cur = dict(BASE, dispatch_hit_rate=0.70)
        mj_cur = metrics_file(work_root, 'cur.json', cur)
        r = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj_cur)
        assert r.returncode == mb.EXIT_DRIFT, r.stdout + r.stderr
        assert '偏离30%' in r.stdout or 'learn_v2' in r.stdout
        assert 'dispatch_hit_rate' in r.stdout

    def test_T9_small_change_passes(self, work_root):
        mj_base = metrics_file(work_root, 'base.json', BASE)
        record(work_root, 'ch01', mj_base)
        cur = dict(BASE, dispatch_hit_rate=0.95)   # -5%，带内
        mj_cur = metrics_file(work_root, 'cur.json', cur)
        r = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj_cur)
        assert r.returncode == mb.EXIT_OK, r.stdout + r.stderr
        assert '✓ 无越界' in r.stdout

    def test_T10_reverse_high_threshold_flips_to_green(self, work_root):
        """反向例：同一 +50% 场景把阈值调到 100% 必须翻绿 ⇒ 告警非恒真断言。

        用 rework_rate 0.10→0.15 而非 dispatch_hit_rate 掉到 0.70：
        后者同时破红线（min=0.80），调阈值也翻不绿 ⇒ 反向例会被红线污染。
        """
        mj_base = metrics_file(work_root, 'base.json', BASE)
        record(work_root, 'ch01', mj_base)
        cur = dict(BASE, rework_rate=0.15)
        mj_cur = metrics_file(work_root, 'cur.json', cur)
        low = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj_cur)
        assert low.returncode == mb.EXIT_DRIFT, low.stdout + low.stderr
        high = run_cli('compare', '--work-root', str(work_root),
                       '--metrics-json', mj_cur, '--threshold', '1.0')
        assert high.returncode == mb.EXIT_OK, high.stdout + high.stderr
        assert '✓ 无越界' in high.stdout

    def test_T11_red_line_breach_is_reported(self, work_root):
        """-5% 不越界但破 dispatch_hit_rate<0.80 红线 ⇒ 仍须告警"""
        mj_base = metrics_file(work_root, 'base.json', dict(BASE, dispatch_hit_rate=0.82))
        record(work_root, 'ch01', mj_base)
        cur = dict(BASE, dispatch_hit_rate=0.79)
        mj_cur = metrics_file(work_root, 'cur.json', cur)
        r = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj_cur)
        assert r.returncode == mb.EXIT_DRIFT, r.stdout + r.stderr
        assert '破红线' in r.stdout

    def test_T12_exclude_current_chapter_from_pool(self, work_root):
        """当前章已入基线时须排除自身，否则「自己跟自己比」恒不告警"""
        mj_base = metrics_file(work_root, 'base.json', BASE)
        record(work_root, 'ch01', mj_base)
        record(work_root, 'ch02', mj_base)
        cur = dict(BASE, dispatch_hit_rate=0.70)
        mj_cur = metrics_file(work_root, 'cur.json', cur)
        r = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj_cur,
                    '--chapter', 'ch02')
        assert r.returncode == mb.EXIT_DRIFT, r.stdout + r.stderr

    def test_T13_invalid_threshold(self, work_root):
        r = run_cli('compare', '--work-root', str(work_root), '--threshold', '1.5')
        assert r.returncode == mb.EXIT_INPUT_ERROR


# ── 3. corrupt / reset ──────────────────────────────────────────────────

class TestCorruptAndReset:
    def test_T14_corrupt_line_is_exit_3(self, work_root):
        p = mb.baseline_path(work_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{broken json\n', encoding='utf-8')
        assert run_cli('list', '--work-root', str(work_root)).returncode == mb.EXIT_BASELINE_CORRUPT
        assert run_cli('compare', '--work-root', str(work_root)).returncode == mb.EXIT_BASELINE_CORRUPT
        mj = metrics_file(work_root, 'm.json', BASE)
        assert record(work_root, 'ch01', mj).returncode == mb.EXIT_BASELINE_CORRUPT

    def test_T15_reset_requires_reason_and_confirm(self, work_root):
        # 只有 reason、缺 confirm ⇒ 拒绝
        assert run_cli('reset', '--work-root', str(work_root),
                       '--reason', 'x').returncode == mb.EXIT_INPUT_ERROR
        # 只有 confirm、缺 reason ⇒ 也拒绝（双保险，防静默重置）
        r = run_cli('reset', '--work-root', str(work_root), '--confirm')
        assert r.returncode == mb.EXIT_INPUT_ERROR, r.stdout + r.stderr
        rows, _ = mb.load_rows(mb.baseline_path(work_root))
        assert rows == [], '被拒绝的 reset 不得写文件'

    def test_T16_reset_keeps_history_but_excludes_it(self, work_root):
        """reset 不删行；之后 compare 只取 reset 之后的新记录。

        构造：旧基线 rework_rate=0.10，新分段基线 0.30，当前 0.30。
        若旧行仍参与 → running mean=0.20 → delta=+50% 告警；
        正确排除 → delta=0 且 0.30 未破 max=0.30 红线 ⇒ 翻绿。
        """
        mj_old = metrics_file(work_root, 'old.json', dict(BASE, rework_rate=0.10))
        record(work_root, 'ch01', mj_old)
        r = run_cli('reset', '--work-root', str(work_root),
                    '--reason', '协议升版 v2.6.0', '--confirm')
        assert r.returncode == mb.EXIT_OK, r.stdout + r.stderr
        rows, _ = mb.load_rows(mb.baseline_path(work_root))
        assert len(rows) == 2, '旧 record 必须保留（可审计）'
        assert rows[-1]['type'] == 'reset'
        mj_new = metrics_file(work_root, 'new.json', dict(BASE, rework_rate=0.30))
        assert record(work_root, 'ch02', mj_new).returncode == 0
        r2 = run_cli('compare', '--work-root', str(work_root), '--metrics-json', mj_new)
        assert r2.returncode == mb.EXIT_OK, r2.stdout + r2.stderr
        assert '✓ 无越界' in r2.stdout

    def test_T17_list_shows_reset_marker(self, work_root):
        mj = metrics_file(work_root, 'm.json', BASE)
        record(work_root, 'ch01', mj)
        run_cli('reset', '--work-root', str(work_root), '--reason', '升版', '--confirm')
        r = run_cli('list', '--work-root', str(work_root))
        assert r.returncode == mb.EXIT_OK
        assert 'RESET' in r.stdout and '升版' in r.stdout


# ── 4. 纯函数 ───────────────────────────────────────────────────────────

class TestFlatten:
    def test_T18_flatten_skips_string_and_bool(self):
        got = mb.flatten_numbers({'a': 1, 'b': 'x', 'c': True,
                                  'd': None, 'n': {'e': 2.5, 'f': [1, 2]}})
        assert got == {'a': 1.0, 'n.e': 2.5}

    def test_T19_flatten_empty_dict(self):
        assert mb.flatten_numbers({}) == {}
