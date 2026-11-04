#!/usr/bin/env python3
"""test_exec_agents.py — P0 执行体脚本回归测试（2026-11-04 诊断批次）

覆盖 4 个新执行体（把 harness 的纸面条款变成可执行判据）：
  · watchdog.py        E2 存活检测（harness §3「60 秒无进展」）
  · validate_envelope.py  信封 6 必填强校验（harness §1）
  · e3_window.py       熔断 E3 滑动窗口计数（harness §4）
  · budget_guard.py    相位级 token 预算守护（harness §2/§3.1）

运行：python3 -m pytest tests/test_exec_agents.py -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture()
def work_root():
    d = tempfile.mkdtemp(prefix='stt_exec_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPTS / script)] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_trace(work_root: Path, rows: list[dict]) -> None:
    d = work_root / '运行态'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'trace.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
        encoding='utf-8')


# ══════════════════════════════════════════════════════════════════════
# watchdog.py —— E2 存活检测
# ══════════════════════════════════════════════════════════════════════

class TestWatchdog:
    def test_register_creates_handles_and_heartbeat(self, work_root):
        r = _run('watchdog.py', '--work-root', str(work_root),
                 '--task-id', 'ch01-T1', '--register', '--pid', '99999')
        assert r.returncode == 0, r.stderr
        assert 'REGISTERED=ch01-T1' in r.stdout
        assert (work_root / '运行态' / 'task-handles.json').is_file()
        assert (work_root / '运行态' / '.heartbeat' / 'ch01-T1.hb').is_file()

    def test_fresh_heartbeat_is_alive(self, work_root):
        _run('watchdog.py', '--work-root', str(work_root),
             '--task-id', 'ch01-T1', '--register', '--pid', '99999')
        r = _run('watchdog.py', '--work-root', str(work_root),
                 '--task-id', 'ch01-T1')
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'VERDICT=ALIVE' in r.stdout

    def test_stale_heartbeat_is_dead_with_action(self, work_root):
        """心跳过期 + 进程已死 → 必须判 DEAD 且给出可执行处置"""
        _run('watchdog.py', '--work-root', str(work_root),
             '--task-id', 'ch01-T1', '--register', '--pid', '99999')
        hb = work_root / '运行态' / '.heartbeat' / 'ch01-T1.hb'
        old = time.time() - 300
        import os
        os.utime(hb, (old, old))
        r = _run('watchdog.py', '--work-root', str(work_root),
                 '--task-id', 'ch01-T1')
        assert r.returncode == 1, r.stdout
        assert 'VERDICT=DEAD' in r.stdout
        assert 'ACTION=' in r.stdout
        assert 'E3' in r.stdout, 'DEAD 必须指向 E3 升级路径'

    def test_unknown_when_no_signals(self, work_root):
        """无心跳、无产物、无 pid → UNKNOWN（不可误杀），exit 2"""
        r = _run('watchdog.py', '--work-root', str(work_root),
                 '--task-id', 'ch01-NONE', '--channel', 'heartbeat')
        assert r.returncode == 2, r.stdout
        assert 'VERDICT=UNKNOWN' in r.stdout

    def test_heartbeat_refresh_revives(self, work_root):
        _run('watchdog.py', '--work-root', str(work_root),
             '--task-id', 'ch01-T1', '--register', '--pid', '99999')
        hb = work_root / '运行态' / '.heartbeat' / 'ch01-T1.hb'
        old = time.time() - 300
        import os
        os.utime(hb, (old, old))
        assert _run('watchdog.py', '--work-root', str(work_root),
                    '--task-id', 'ch01-T1').returncode == 1
        _run('watchdog.py', '--work-root', str(work_root),
             '--task-id', 'ch01-T1', '--heartbeat')
        assert _run('watchdog.py', '--work-root', str(work_root),
                    '--task-id', 'ch01-T1').returncode == 0

    def test_missing_work_root_errors(self, work_root):
        r = _run('watchdog.py', '--work-root', str(work_root / 'nope'),
                 '--task-id', 'ch01-T1')
        assert r.returncode == 3

    def test_task_id_required(self, work_root):
        r = _run('watchdog.py', '--work-root', str(work_root))
        assert r.returncode == 3

    def test_list_shows_registered(self, work_root):
        _run('watchdog.py', '--work-root', str(work_root),
             '--task-id', 'ch01-T1', '--register', '--pid', '99999')
        r = _run('watchdog.py', '--work-root', str(work_root), '--list')
        assert r.returncode == 0
        assert 'ch01-T1' in r.stdout


# ══════════════════════════════════════════════════════════════════════
# validate_envelope.py —— 信封 6 必填强校验
# ══════════════════════════════════════════════════════════════════════

class TestValidateEnvelope:
    def _write(self, work_root: Path, env: dict) -> Path:
        p = work_root / 'env.json'
        p.write_text(json.dumps(env, ensure_ascii=False), encoding='utf-8')
        return p

    def test_complete_envelope_passes(self, work_root):
        env = {
            'from': 'team-lead', 'to': 'subject-writer', 'task_id': 'ch01-T1',
            'type': 'RESULT', 'correlation_id': 'ch01', 'status': 'success',
            'agent_id': 'subject-writer', 'confidence': 92,
            'deliverable_summary': '章节/ch01/draft.md', 'msg_id': 'm1',
        }
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 0, r.stderr
        assert 'ENVELOPE_VALID=1' in r.stdout
        assert 'OUTCOME=OK' in r.stdout

    def test_missing_required_rejected(self, work_root):
        """缺必填 → exit 2 拒收（这是原 M3 缺陷的执行体）"""
        env = {'to': 'subject-writer', 'type': 'RESULT', 'status': 'success'}
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 2
        assert 'ENVELOPE_VALID=0' in r.stdout
        assert 'from' in r.stderr and 'task_id' in r.stderr

    def test_each_required_field_individually_blocks(self, work_root):
        """逐个必填字段缺失都必须拦下"""
        base = {
            'from': 'a', 'to': 'b', 'task_id': 't',
            'type': 'RESULT', 'correlation_id': 'c', 'status': 'success',
        }
        for k in base:
            env = dict(base)
            del env[k]
            p = self._write(work_root, env)
            r = _run('validate_envelope.py', '--envelope', str(p))
            assert r.returncode == 2, f'缺 {k} 未被拦下'
            assert k in r.stderr

    def test_missing_extended_only_warns(self, work_root):
        env = {
            'from': 'a', 'to': 'b', 'task_id': 't', 'type': 'RESULT',
            'correlation_id': 'c', 'status': 'success',
        }
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 0, '扩展字段缺失只告警不阻断'
        assert '[WARN]' in r.stderr

    def test_strict_mode_fails_on_extended_missing(self, work_root):
        env = {
            'from': 'a', 'to': 'b', 'task_id': 't', 'type': 'RESULT',
            'correlation_id': 'c', 'status': 'success',
        }
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p), '--strict')
        assert r.returncode == 2

    def test_illegal_type_rejected(self, work_root):
        env = {
            'from': 'a', 'to': 'b', 'task_id': 't', 'type': 'BOGUS',
            'correlation_id': 'c', 'status': 'success',
        }
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 2
        assert 'type' in r.stderr

    def test_illegal_status_rejected(self, work_root):
        env = {
            'from': 'a', 'to': 'b', 'task_id': 't', 'type': 'RESULT',
            'correlation_id': 'c', 'status': 'weird',
        }
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 2

    def test_confidence_out_of_range_rejected(self, work_root):
        env = {
            'from': 'a', 'to': 'b', 'task_id': 't', 'type': 'RESULT',
            'correlation_id': 'c', 'status': 'success', 'confidence': 150,
        }
        p = self._write(work_root, env)
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 2
        assert 'confidence' in r.stderr

    def test_bad_json_exit_3(self, work_root):
        p = work_root / 'bad.json'
        p.write_text('{not json', encoding='utf-8')
        r = _run('validate_envelope.py', '--envelope', str(p))
        assert r.returncode == 3


# ══════════════════════════════════════════════════════════════════════
# e3_window.py —— 熔断滑动窗口
# ══════════════════════════════════════════════════════════════════════

class TestE3Window:
    def test_single_e3_stays_closed(self, work_root):
        r = _run('e3_window.py', '--work-root', str(work_root),
                 '--correlation-id', 'ch03', '--record', '--outcome', 'ERROR')
        assert r.returncode == 0
        assert 'STATE=CLOSED' in r.stdout

    def test_two_e3_triggers_open(self, work_root):
        """连续 E3 达 2 次 → 熔断 OPEN（exit 1）"""
        for _ in range(2):
            r = _run('e3_window.py', '--work-root', str(work_root),
                     '--correlation-id', 'ch03', '--record', '--outcome', 'ERROR')
        assert r.returncode == 1
        assert 'STATE=OPEN' in r.stdout
        assert 'CIRCUIT_OPEN=1' in r.stdout

    def test_window_slides_out_old_entries(self, work_root):
        """滑动窗口 = 最近 3 次：旧的 E3 应被挤出窗口"""
        for _ in range(2):
            _run('e3_window.py', '--work-root', str(work_root),
                 '--correlation-id', 'ch03', '--record', '--outcome', 'ERROR')
        assert _run('e3_window.py', '--work-root', str(work_root),
                    '--correlation-id', 'ch03').returncode == 1
        # 一次成功推进后，窗口内 E3 数降为 2（3 条里 2 条 E3）仍 OPEN
        _run('e3_window.py', '--work-root', str(work_root),
             '--correlation-id', 'ch03', '--record', '--outcome', 'OK')
        r = _run('e3_window.py', '--work-root', str(work_root),
                 '--correlation-id', 'ch03')
        assert 'WINDOW_SIZE=3' in r.stdout
        # 再一次成功 → 窗口内只剩 1 个 E3 → 恢复 CLOSED
        _run('e3_window.py', '--work-root', str(work_root),
             '--correlation-id', 'ch03', '--record', '--outcome', 'OK')
        r2 = _run('e3_window.py', '--work-root', str(work_root),
                  '--correlation-id', 'ch03')
        assert 'STATE=CLOSED' in r2.stdout, r2.stdout

    def test_chapters_are_isolated(self, work_root):
        """不同章节的 E3 不合并计数（harness §4 明确要求）"""
        _run('e3_window.py', '--work-root', str(work_root),
             '--correlation-id', 'ch03', '--record', '--outcome', 'ERROR')
        r = _run('e3_window.py', '--work-root', str(work_root),
                 '--correlation-id', 'ch04', '--record', '--outcome', 'ERROR')
        assert r.returncode == 0, 'ch04 不应受 ch03 影响'
        assert 'STATE=CLOSED' in r.stdout

    def test_status_does_not_record(self, work_root):
        _run('e3_window.py', '--work-root', str(work_root),
             '--correlation-id', 'ch03', '--record', '--outcome', 'ERROR')
        r = _run('e3_window.py', '--work-root', str(work_root),
                 '--correlation-id', 'ch03', '--status')
        assert 'E3_COUNT=1' in r.stdout

    def test_list_all(self, work_root):
        _run('e3_window.py', '--work-root', str(work_root),
             '--correlation-id', 'ch03', '--record', '--outcome', 'ERROR')
        r = _run('e3_window.py', '--work-root', str(work_root), '--list')
        assert 'ch03' in r.stdout


# ══════════════════════════════════════════════════════════════════════
# budget_guard.py —— 相位级 token 守护
# ══════════════════════════════════════════════════════════════════════

class TestBudgetGuard:
    def test_healthy_budget_exit_0(self, work_root):
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'RETRIEVE', 'tokens_in': 1000, 'tokens_out': 1000,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'STATUS=OK' in r.stdout

    def test_phase_over_budget_detected(self, work_root):
        """RETRIEVE 软上限 40K，超了必须报且 exit 1"""
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'RETRIEVE', 'tokens_in': 30000, 'tokens_out': 20000,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert r.returncode == 1
        assert 'RETRIEVE' in r.stdout
        assert '⚠超限' in r.stdout or '超限' in r.stdout

    def test_retrieve_is_p0_no_cut_hint(self, work_root):
        """RETRIEVE 属 P0 —— 必须提示「禁止削减」"""
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'RETRIEVE', 'tokens_in': 30000, 'tokens_out': 20000,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert 'P0' in r.stdout
        assert '禁止削减' in r.stdout

    def test_hard_limit_exit_2(self, work_root):
        """达章节硬上限 → exit 2（必须保存现场上报）"""
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'RETRIEVE', 'tokens_in': 200000, 'tokens_out': 0,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert r.returncode == 2
        assert 'HARD_LIMIT_REACHED' in r.stdout

    def test_degrade_threshold_suggested(self, work_root):
        """达 80% → 提示降级档"""
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'PRODUCE-R1', 'tokens_in': 130000, 'tokens_out': 0,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert r.returncode in (1, 2)
        assert 'DEGRADE_SUGGESTED' in r.stdout or 'HARD_LIMIT_REACHED' in r.stdout

    def test_unknown_phase_tokens_warned(self, work_root):
        """无 phase 的历史行必须告警（不能静默吞掉 token）"""
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'tokens_in': 5000, 'tokens_out': 5000,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert '无 phase 归属' in r.stderr

    def test_estimated_tokens_marked(self, work_root):
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'RETRIEVE', 'tokens_in': 1000, 'tokens_out': 1000,
            'estimated': True,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root))
        assert 'estimated' in r.stderr

    def test_json_output(self, work_root):
        _write_trace(work_root, [{
            'task_id': 'ch01-T1', 'type': 'RESULT', 'outcome': 'OK',
            'phase': 'RETRIEVE', 'tokens_in': 1000, 'tokens_out': 1000,
        }])
        r = _run('budget_guard.py', '--work-root', str(work_root), '--json')
        data = json.loads(r.stdout)
        assert data['status'] == 'OK'
        assert data['hard_limit'] == 150000
        assert data['per_phase'][0]['phase'] == 'RETRIEVE'

    def test_phase_filter(self, work_root):
        _write_trace(work_root, [
            {'task_id': 'a', 'type': 'RESULT', 'outcome': 'OK',
             'phase': 'RETRIEVE', 'tokens_in': 100, 'tokens_out': 100},
            {'task_id': 'b', 'type': 'RESULT', 'outcome': 'OK',
             'phase': 'PRODUCE-R1', 'tokens_in': 100, 'tokens_out': 100},
        ])
        r = _run('budget_guard.py', '--work-root', str(work_root), '--phase', 'RETRIEVE')
        assert 'RETRIEVE' in r.stdout
        assert 'PRODUCE-R1' not in r.stdout


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
