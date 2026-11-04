#!/usr/bin/env python3
"""test_core_scripts.py — 核心脚本回归测试（2026-11-04 诊断 P0 批次引入）

背景：2026-11-04 的系统性诊断发现，外部包 19 个脚本中，
record_trace.py / compute_metrics.py / progress.py 这三个最核心的
**此前没有任何自动化测试覆盖**（tests/ 下只有 manifest 同步 / router
评估 / vendor 完整性三个独立脚本，且都覆盖不到这三个）。

后果是真实运行时才暴露的口径撕裂无人拦截：
  · 写端写 outcome=SUCCESS，读端硬比较 'OK' → 分派命中率被算成 0.000
    （真实 4 个任务全部成功，却被判为 0% 命中）
  · 坏行静默丢弃 → 指标分母偏小且不可观测
  · blocking 占比实现口径（trace 行）与文档口径（总任务）不一致

本文件把这些口径固化为可执行断言。任何回归都会在 CI 阶段红灯，
而不是等到下一次真实运行。

运行：python3 -m pytest tests/test_core_scripts.py -v
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

import compute_metrics  # noqa: E402
import record_trace  # noqa: E402
import trace_schema  # noqa: E402


# ── 工具 ────────────────────────────────────────────────────────────────

@pytest.fixture()
def work_root():
    """临时工作区。

    不用 pytest 内置 tmp_path —— 本包运行在 OneDrive 沙箱环境下，
    pytest 的 basetemp 创建会被宿主拦截（FileExistsError），
    而 tempfile.mkdtemp 走同一挂载点却正常。已实测。
    """
    d = tempfile.mkdtemp(prefix='stt_core_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run_trace_cli(work_root: Path, *extra: str) -> subprocess.CompletedProcess:
    """裸跑 record_trace.py（不经 shell，便于断言退出码）"""
    cmd = [sys.executable, str(SCRIPTS / 'record_trace.py'),
           '--work-root', str(work_root)]
    return subprocess.run(cmd + list(extra), capture_output=True, text=True)


def _read_trace(work_root: Path) -> list[dict]:
    f = work_root / '运行态' / 'trace.jsonl'
    if not f.is_file():
        return []
    return [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]


# ══════════════════════════════════════════════════════════════════════
# 1. outcome 归一化（P0-1：真实样本暴露的 SUCCESS/OK 撕裂）
# ══════════════════════════════════════════════════════════════════════

class TestOutcomeNormalize:
    """写端归一 + 读端兼容 —— 两侧必须共用同一张别名表"""

    @pytest.mark.parametrize('raw,expected', [
        ('SUCCESS', 'OK'), ('success', 'OK'), ('SUCCEED', 'OK'),
        ('PASS', 'OK'), ('DONE', 'OK'), ('OK', 'OK'),
        ('FAILED', 'ERROR'), ('FAIL', 'ERROR'), ('ERROR', 'ERROR'),
        ('BLOCK', 'BLOCKED'), ('BLOCKED', 'BLOCKED'),
        ('PARTIAL', 'PARTIAL'), ('TIMEOUT', 'TIMEOUT'),
    ])
    def test_alias_table(self, raw, expected):
        assert trace_schema.normalize_outcome(raw) == expected

    def test_unknown_value_preserved_not_dropped(self):
        """未知值必须原样保留（不丢信息），而不是静默变空"""
        assert trace_schema.normalize_outcome('WAT') == 'WAT'
        assert trace_schema.normalize_outcome('') == ''
        assert trace_schema.normalize_outcome(None) == ''

    def test_is_success_covers_aliases(self):
        """读端成功判据必须认 SUCCESS —— 这正是原 bug 的根因"""
        assert trace_schema.is_success('SUCCESS')
        assert trace_schema.is_success('OK')
        assert trace_schema.is_success('ok')
        assert not trace_schema.is_success('ERROR')
        assert not trace_schema.is_success('PARTIAL')
        assert not trace_schema.is_success('')

    def test_write_side_normalizes(self):
        """写端：SUCCESS 落盘后必须是 OK"""
        norm, warn = record_trace.normalize_outcome('SUCCESS')
        assert norm == 'OK'
        assert warn and '归一' in warn

    def test_write_side_warns_unknown(self):
        """写端：未知值必须告警（下游按枚举比较，不告警会被静默漏计）"""
        norm, warn = record_trace.normalize_outcome('WAT')
        assert norm == 'WAT'
        assert warn and '未知' in warn

    def test_cli_normalizes_outcome(self, work_root):
        """端到端：CLI 传 --outcome SUCCESS，落盘应为 OK"""
        r = _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                           '--type', 'RESULT', '--outcome', 'SUCCESS')
        assert r.returncode == 0, r.stderr
        rec = _read_trace(work_root)[0]
        assert rec['outcome'] == 'OK'
        assert '归一' in r.stderr


# ══════════════════════════════════════════════════════════════════════
# 2. trace schema：C2 新增字段
# ══════════════════════════════════════════════════════════════════════

class TestTraceSchema:
    """C2：phase / start / 毫秒 ts —— 相位级时延可计算的前提"""

    def test_cli_writes_phase_and_start(self, work_root):
        r = _run_trace_cli(work_root, '--task-id', 'ch01-PRODUCE-R2', '--from', 'a', '--to', 'b',
                           '--type', 'RESULT', '--outcome', 'OK',
                           '--phase', 'PRODUCE-R2', '--duration-ms', '1234')
        assert r.returncode == 0, r.stderr
        rec = _read_trace(work_root)[0]
        assert rec['phase'] == 'PRODUCE-R2'
        assert rec['start'], 'start 字段必须存在'
        assert rec['ts'], 'ts 字段必须存在'

    def test_ts_has_millisecond_precision(self, work_root):
        """秒级精度会让同秒内的相位无法排序 —— 必须毫秒"""
        _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK')
        ts = _read_trace(work_root)[0]['ts']
        # ISO8601 毫秒：2026-11-04T07:00:00.123+00:00
        assert '.' in ts.split('+')[0], f'时间戳缺毫秒小数部分: {ts}'

    def test_unknown_phase_warns_but_not_blocking(self, work_root):
        """未知相位应告警但不阻断写入（诊断相位名拼写错误不该让任务失败）"""
        r = _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                           '--type', 'RESULT', '--outcome', 'OK', '--phase', 'BOGUS-PHASE')
        assert r.returncode == 0, r.stderr
        assert '未知相位' in r.stderr
        rec = _read_trace(work_root)[0]
        assert rec['phase'] == 'BOGUS-PHASE', '原值必须保留，不能被静默丢弃'

    def test_known_phase_no_warning(self, work_root):
        r = _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                           '--type', 'RESULT', '--outcome', 'OK', '--phase', 'PRODUCE-R2')
        assert r.returncode == 0
        assert '未知相位' not in r.stderr

    def test_trace_fields_ssot_contains_new_fields(self):
        """SSOT 必须包含 C2 三字段"""
        for f in ('phase', 'start', 'ts'):
            assert f in trace_schema.TRACE_FIELDS


# ══════════════════════════════════════════════════════════════════════
# 3. 指标口径（H1 返工率 / H2 blocking / H3 坏行）
# ══════════════════════════════════════════════════════════════════════

class TestMetricsSemantics:
    """口径回归 —— 每条对应一个真实诊断发现"""

    def test_dispatch_hit_rate_accepts_success_alias(self, work_root):
        """回归：SUCCESS 写法的任务必须被计入命中（原 bug：0/4）"""
        _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'SUCCESS')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        assert m['dispatch_hit_rate'] == 1.0, \
            f"SUCCESS 未被计入成功: spawn_ok={m['spawn_ok']}/{m['spawn_total']}"

    def test_blocking_pct_uses_task_denominator(self, work_root):
        """H2：blocking 占比分母必须是任务数，不是 trace 行数"""
        # 任务 A：2 行（1 STATUS + 1 RESULT），带 blocking
        _run_trace_cli(work_root, '--task-id', 'ch01-A', '--from', 'a', '--to', 'b',
                       '--type', 'STATUS', '--outcome', '', '--blocking-open', 'X1')
        _run_trace_cli(work_root, '--task-id', 'ch01-A', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK', '--blocking-open', 'X1')
        # 任务 B：1 行，无 blocking
        _run_trace_cli(work_root, '--task-id', 'ch01-B', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        # 任务口径：1/2 = 0.5（任务A 有 blocking，任务B 没有）
        assert m['blocking_total'] == 1
        assert abs(m['blocking_pct'] - 0.5) < 1e-9, \
            f"blocking 口径错误: {m['blocking_pct']}（任务口径应为 0.5）"
        # 行口径参考：任务A 的 2 行都带 blocking → 2/3
        assert m['blocking_row_total'] == 2
        assert abs(m['blocking_row_pct'] - (2 / 3)) < 1e-9, '行口径参考值应保留'

    def test_rework_rate_warns_when_uncomputable(self, work_root):
        """H1：返工率不可计算时必须有告警，禁止静默消失"""
        _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        assert m['rework_rate'] is None
        assert m.get('rework_warn'), '返工率不可计算时必须产生告警文本'

    def test_rework_rate_computable_with_review_type(self, work_root):
        """对照：标了 review-* 的任务 → 返工率可算，无告警"""
        _run_trace_cli(work_root, '--task-id', 'ch01-REV', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK', '--task-type', 'review-structure')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        assert m['rework_rate'] is not None
        assert not m.get('rework_warn')

    def test_rework_detected_on_repeat_success(self, work_root):
        """同 task_id 两次成功交付 = 返工"""
        for _ in range(2):
            _run_trace_cli(work_root, '--task-id', 'ch01-REV', '--from', 'a', '--to', 'b',
                           '--type', 'RESULT', '--outcome', 'OK', '--task-type', 'review-depth')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        assert m['rework_rate'] == 1.0

    def test_bad_lines_counted_not_silent(self, work_root):
        """H3：坏行必须计数并可观测，不能静默丢弃"""
        trace_dir = work_root / '运行态'
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / 'trace.jsonl').write_text(
            '{"task_id":"ch01-A","type":"RESULT","outcome":"OK"}\n'
            'THIS IS NOT JSON\n'
            '{"task_id":"ch01-B","type":"RESULT","outcome":"OK"}\n',
            encoding='utf-8')
        traces, bad = compute_metrics.load_traces(work_root)
        assert len(traces) == 2
        assert bad == 1, f'坏行数应为 1，实际 {bad}'

    def test_empty_traces_returns_base_with_zeroed_fields(self, work_root):
        """无 trace 时不得 KeyError，且必须带新字段"""
        m = compute_metrics.compute([], work_root=work_root)
        assert m['total_traces'] == 0
        for k in ('rework_warn', 'bad_lines', 'latency_by_phase',
                  'blocking_row_pct', 'blocking_row_total'):
            assert k in m, f'缺字段 {k}'


# ══════════════════════════════════════════════════════════════════════
# 4. 时延指标（C2）
# ══════════════════════════════════════════════════════════════════════

class TestLatency:
    def test_delta_ms_basic(self):
        assert compute_metrics._delta_ms(
            '2026-11-04T07:00:00+00:00', '2026-11-04T07:00:30+00:00') == 30000

    def test_delta_ms_tolerates_naive_and_millis(self):
        assert compute_metrics._delta_ms(
            '2026-11-04T07:00:00', '2026-11-04T07:00:10') == 10000
        assert compute_metrics._delta_ms(
            '2026-11-04T07:00:00.500+00:00', '2026-11-04T07:00:01.500+00:00') == 1000

    def test_delta_ms_never_raises(self):
        """脏数据不得让指标计算崩溃"""
        assert compute_metrics._delta_ms('garbage', 'also-garbage') == 0
        assert compute_metrics._delta_ms(None, None) == 0
        assert compute_metrics._delta_ms('', '2026-11-04T07:00:00') == 0

    def test_latency_by_phase(self, work_root):
        _run_trace_cli(work_root, '--task-id', 'ch01-P1', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK',
                       '--phase', 'PRODUCE-R1', '--duration-ms', '5000')
        _run_trace_cli(work_root, '--task-id', 'ch01-P2', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK',
                       '--phase', 'PRODUCE-R2', '--duration-ms', '9000')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        lat = m['latency_by_phase']
        assert lat.get('PRODUCE-R1') == [5000]
        assert lat.get('PRODUCE-R2') == [9000]
        assert m['latency_tasks']['ch01-P2'] == 9000

    def test_legacy_trace_without_phase_not_counted(self, work_root):
        """历史 trace（无 phase）不得被误算成 0ms —— 会污染时延分桶"""
        trace_dir = work_root / '运行态'
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / 'trace.jsonl').write_text(
            json.dumps({'task_id': 'ch01-A', 'type': 'RESULT', 'outcome': 'OK',
                        'duration_ms': 0, 'ts': '2026-11-04T07:00:00+00:00'}) + '\n',
            encoding='utf-8')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        assert not m['latency_by_phase'], '无 phase 的行不应进入相位桶'


# ══════════════════════════════════════════════════════════════════════
# 5. 渲染层不崩 + 告警可见
# ══════════════════════════════════════════════════════════════════════

class TestRender:
    def test_render_contains_rework_warning(self, work_root):
        _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'OK')
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        out = compute_metrics.render(m)
        assert '不可计算' in out, '返工率不可计算的告警必须出现在报告正文'
        assert 'review' in out

    def test_render_contains_latency_section(self, work_root):
        traces, _ = compute_metrics.load_traces(work_root)
        m = compute_metrics.compute(traces, work_root=work_root)
        out = compute_metrics.render(m)
        assert '相位级时延' in out

    def test_cli_end_to_end_exit_zero(self, work_root):
        """CLI 全链路：写 trace → 算指标 → 出报告，退出码 0"""
        _run_trace_cli(work_root, '--task-id', 'ch01-T1', '--from', 'a', '--to', 'b',
                       '--type', 'RESULT', '--outcome', 'SUCCESS',
                       '--phase', 'PRODUCE-R1', '--duration-ms', '1000')
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / 'compute_metrics.py'),
             '--work-root', str(work_root), '--report-only'],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert '分派命中率' in r.stdout
        assert '1/1 = 1.000' in r.stdout, 'SUCCESS 写法必须算作命中'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
