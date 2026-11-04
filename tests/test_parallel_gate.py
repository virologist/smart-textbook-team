#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_parallel_gate.py — Batch 3 并行裁决门回归（2026-11-04 B3 批次）

覆盖诊断 §3.2 升级 A / 升级 C 的两条风险控制：
  ① 知识块共享锚「只增不改」：删/改/重复/解析失败/同一文件自比对全部不得放行
  ② 图表位变更率 > 阈值（严格大于）⇒ 回退串行 + 写合规 trace + 出 learn 信号
  ③ 反向例纪律：每个拒绝判定都要有「修好后翻绿」或「调阈值后翻绿」的对照，
     证明断言不是恒真（见 T_B3_03/04/16/18/22）
  ④ 图表位正则与门禁 4 的 SSOT 同源（防第二份正则漂移）

运行：python3 -m pytest tests/test_parallel_gate.py -q
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

import parallel_gate as pg  # noqa: E402
import check_manuscript as cm  # noqa: E402

HEADER = ['block_id', '知识域', 'Bloom 层级', '字数目标', '依赖块', '可并行标记']
B1 = ('KB-01', '病原学', '理解', '800', '—', 'yes')
B2 = ('KB-02', '流行病学', '应用', '1200', 'KB-01', 'no')
B3 = ('KB-03', '防控', '分析', '900', 'KB-02', 'no')


@pytest.fixture()
def work_root():
    """临时工作区（不用 pytest tmp_path：OneDrive 沙箱下 basetemp 会被拦截）"""
    d = tempfile.mkdtemp(prefix='stt_pg_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_cli(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / 'parallel_gate.py'), *extra],
        capture_output=True, text=True)


def design(root: Path, name: str, rows: list[tuple],
           header: list[str] = HEADER, *, with_anchor: bool = True,
           sep: bool = True) -> str:
    """生成带机器可读锚区块的 chapter_design.md，返回路径字符串。"""
    lines = ['# chapter_design', '']
    if with_anchor:
        lines.append(pg.ANCHOR_BEGIN)
        lines.append('| ' + ' | '.join(header) + ' |')
        if sep:
            lines.append('| ' + ' | '.join(['---'] * len(header)) + ' |')
        for row in rows:
            lines.append('| ' + ' | '.join(row) + ' |')
        lines.append(pg.ANCHOR_END)
    p = root / name
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(p)


def draft(root: Path, name: str, slots: list[tuple[str, str]]) -> str:
    """生成含图表位的稿；slots = [(编号 '1-1', 描述), ...]。"""
    lines = ['# 章正文', '']
    for stem, desc in slots:
        lines.append(f'[图 {stem}：{desc}]')
        lines.append('')
    p = root / name
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(p)


def anchor_cli(v1: str, refined: str, out: str = '') -> subprocess.CompletedProcess:
    cmd = ['anchor', '--v1', v1, '--refined', refined]
    if out:
        cmd += ['--out', out]
    return run_cli(*cmd)


def drift_cli(frozen: str, current: str, chapter: str = 'ch01',
              *extra: str) -> subprocess.CompletedProcess:
    return run_cli('visual-drift', '--frozen', frozen, '--current', current,
                   '--chapter', chapter, *extra)


# ── 升级 A：知识块共享锚 ────────────────────────────────────────────────

class TestAnchor:
    def test_T_B3_01_identical_is_ok(self, work_root):
        v1 = design(work_root, 'v1.md', [B1, B2])
        r = anchor_cli(v1, design(work_root, 'refined.md', [B1, B2]))
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr
        assert 'DECISION=ANCHOR_OK' in r.stdout

    def test_T_B3_02_only_add_is_ok_and_baseline_unchanged(self, work_root):
        v1 = design(work_root, 'v1.md', [B1, B2])
        refined = design(work_root, 'refined.md', [B1, B2, B3])
        out = str(work_root / 'anchor.json')
        r = anchor_cli(v1, refined, out)
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr
        rep = json.loads(Path(out).read_text(encoding='utf-8'))
        assert rep['baseline_ids'] == ['KB-01', 'KB-02']   # 门禁 2 永远按 v1
        assert rep['added_ids'] == ['KB-03']
        assert rep['baseline_count'] == 2 and rep['refined_count'] == 3

    def test_T_B3_03_removed_block_rejected_with_reverse(self, work_root):
        v1 = design(work_root, 'v1.md', [B1, B2])
        bad = design(work_root, 'bad.md', [B1])
        r = anchor_cli(v1, bad)
        assert r.returncode == pg.EXIT_DECISION, r.stdout + r.stderr
        assert 'KB-02' in r.stdout and '删块' in r.stderr
        # 反向例：把被删的块补回 ⇒ 必须翻绿（证明不是恒真拒绝）
        good = design(work_root, 'good.md', [B1, B2])
        assert anchor_cli(v1, good).returncode == pg.EXIT_OK

    def test_T_B3_04_modified_block_rejected_with_reverse(self, work_root):
        v1 = design(work_root, 'v1.md', [B1, B2])
        changed = ('KB-02', '流行病学', '创造', '1200', 'KB-01', 'no')
        r = anchor_cli(v1, design(work_root, 'bad.md', [B1, changed]))
        assert r.returncode == pg.EXIT_DECISION, r.stdout + r.stderr
        assert 'KB-02' in r.stdout
        assert anchor_cli(v1, design(work_root, 'good.md', [B1, B2])).returncode == pg.EXIT_OK

    def test_T_B3_05_whitespace_only_is_not_modification(self, work_root):
        """首尾空白归一：纯排版差异不得判为「改块」（防过严误杀）。"""
        v1 = design(work_root, 'v1.md', [B1])
        spaced = ('KB-01', '  病原学  ', ' 理解 ', '800', '—', 'yes')
        r = anchor_cli(v1, design(work_root, 'refined.md', [spaced]))
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr

    def test_T_B3_06_duplicate_id_rejected(self, work_root):
        v1 = design(work_root, 'v1.md', [B1])
        r = anchor_cli(v1, design(work_root, 'refined.md', [B1, B1]))
        assert r.returncode == pg.EXIT_DECISION, r.stdout + r.stderr
        assert 'KB-01' in r.stdout

    def test_T_B3_07_missing_anchor_is_input_error(self, work_root):
        v1 = design(work_root, 'v1.md', [B1])
        plain = design(work_root, 'plain.md', [], with_anchor=False)
        r = anchor_cli(v1, plain)
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '锚区块' in r.stderr

    def test_T_B3_08_empty_table_is_input_error(self, work_root):
        v1 = design(work_root, 'v1.md', [B1])
        r = anchor_cli(v1, design(work_root, 'empty.md', []))
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '空锚' in r.stderr

    def test_T_B3_09_column_mismatch_is_input_error(self, work_root):
        v1 = design(work_root, 'v1.md', [B1])
        p = work_root / 'mis.md'
        p.write_text(f'{pg.ANCHOR_BEGIN}\n'
                     '| block_id | 知识域 |\n| --- | --- |\n'
                     f'| KB-01 | 病原学 | 理解 | 800 |\n{pg.ANCHOR_END}\n',
                     encoding='utf-8')
        r = anchor_cli(v1, str(p))
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '列错位' in r.stderr

    def test_T_B3_10_same_file_self_compare_rejected(self, work_root):
        """恒真守卫：同一文件自比对必然全等，不得作为「通过」证据。"""
        v1 = design(work_root, 'v1.md', [B1])
        r = anchor_cli(v1, v1)
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '同一文件' in r.stderr

    def test_T_B3_11_missing_file_is_input_error(self, work_root):
        v1 = design(work_root, 'v1.md', [B1])
        r = anchor_cli(v1, str(work_root / 'nope.md'))
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '不存在' in r.stderr

    def test_T_B3_12_report_carries_baseline_ids_for_gate2(self, work_root):
        v1 = design(work_root, 'v1.md', [B1, B2, B3])
        out = str(work_root / '运行态' / 'anchor_ch01.json')
        r = anchor_cli(v1, design(work_root, 'refined.md', [B1, B2, B3, ('KB-04', '诊断', '应用', '600', '—', 'yes')]), out)
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr
        rep = json.loads(Path(out).read_text(encoding='utf-8'))
        assert rep['decision'] == pg.DECISION_ANCHOR_OK
        assert rep['baseline_ids'] == ['KB-01', 'KB-02', 'KB-03']
        assert rep['violations'] == []

    def test_T_B3_13_illegal_block_id_is_input_error(self, work_root):
        v1 = design(work_root, 'v1.md', [B1])
        bad = ('块 一', '病原学', '理解', '800', '—', 'yes')
        r = anchor_cli(v1, design(work_root, 'bad.md', [bad]))
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert 'block_id 非法' in r.stderr


# ── 升级 C：图表位漂移与回退 ────────────────────────────────────────────

class TestVisualDrift:
    def test_T_B3_14_no_change_continues_parallel(self, work_root):
        f = draft(work_root, 'frozen.md', [('1-1', '传播链'), ('1-2', '发病率趋势')])
        c = draft(work_root, 'current.md', [('1-1', '传播链'), ('1-2', '发病率趋势')])
        r = drift_cli(f, c)
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr
        assert 'DECISION=CONTINUE_PARALLEL' in r.stdout

    def test_T_B3_15_exactly_50pct_does_not_fallback(self, work_root):
        """严格大于：等于阈值不回退（与 architect 密度 <0.3 同一纪律）。"""
        f = draft(work_root, 'frozen.md', [('1-1', '传播链'), ('1-2', '发病率趋势')])
        c = draft(work_root, 'current.md', [('1-1', '传播链改'), ('1-2', '发病率趋势')])
        out = str(work_root / 'd.json')
        r = run_cli('visual-drift', '--frozen', f, '--current', c,
                    '--chapter', 'ch01', '--threshold', '0.5', '--out', out)
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr
        rep = json.loads(Path(out).read_text(encoding='utf-8'))
        assert rep['changed_ratio'] == 0.5
        assert rep['strictly_greater'] is False
        assert rep['decision'] == pg.DECISION_CONTINUE

    def test_T_B3_16_over_50pct_fallback_with_reverse(self, work_root):
        f = draft(work_root, 'frozen.md',
                  [('1-1', '传播链'), ('1-2', '发病率趋势'),
                   ('1-3', '剖检变化'), ('1-4', '免疫程序'), ('1-5', '防控流程')])
        c = draft(work_root, 'current.md',
                  [('1-1', '传播链改'), ('1-2', '发病率改'),
                   ('1-3', '剖检改'), ('1-4', '免疫程序'), ('1-5', '防控流程')])
        out = str(work_root / 'd.json')
        low = run_cli('visual-drift', '--frozen', f, '--current', c,
                      '--chapter', 'ch01', '--threshold', '0.5', '--out', out)
        assert low.returncode == pg.EXIT_DECISION, low.stdout + low.stderr
        rep = json.loads(Path(out).read_text(encoding='utf-8'))
        assert rep['decision'] == pg.DECISION_FALLBACK
        assert rep['changed_ratio'] == 0.6
        assert rep['learn_signal']['signal_type'] == 'parallel_fallback'
        assert rep['learn_signal']['metric_evidence']['red_line'] is True
        # 反向例：阈值调高到 0.8 ⇒ 同一场景必须翻绿（证明告警不是恒真）
        high = run_cli('visual-drift', '--frozen', f, '--current', c,
                       '--chapter', 'ch01', '--threshold', '0.8')
        assert high.returncode == pg.EXIT_OK, high.stdout + high.stderr

    def test_T_B3_17_removed_slot_counts_as_changed(self, work_root):
        f = draft(work_root, 'frozen.md', [('1-1', '传播链'), ('1-2', '发病率')])
        c = draft(work_root, 'current.md', [('1-1', '传播链')])
        out = str(work_root / 'd.json')
        # 默认阈值 0.5 下 1/2 恰好不越界（严格大于）；调低到 0.4 才回退。
        r_def = drift_cli(f, c)
        assert r_def.returncode == pg.EXIT_OK, r_def.stdout + r_def.stderr
        r = run_cli('visual-drift', '--frozen', f, '--current', c,
                    '--chapter', 'ch01', '--threshold', '0.4', '--out', out)
        assert r.returncode == pg.EXIT_DECISION, r.stdout + r.stderr
        rep = json.loads(Path(out).read_text(encoding='utf-8'))
        assert rep['removed_slots'] == ['1-2']
        assert rep['changed_slots'] == ['1-2']
        assert rep['changed_ratio'] == 0.5

    def test_T_B3_18_added_slot_does_not_count_with_reverse(self, work_root):
        """新增图位只意味着另画一张，不使既有规格卡作废 ⇒ 不计入分子。"""
        f = draft(work_root, 'frozen.md', [('1-1', '传播链'), ('1-2', '发病率')])
        c = draft(work_root, 'current.md',
                  [('1-1', '传播链'), ('1-2', '发病率'), ('1-3', '新增图')])
        out = str(work_root / 'd.json')
        r = run_cli('visual-drift', '--frozen', f, '--current', c,
                    '--chapter', 'ch01', '--out', out)
        assert r.returncode == pg.EXIT_OK, r.stdout + r.stderr
        rep = json.loads(Path(out).read_text(encoding='utf-8'))
        assert rep['added_slots'] == ['1-3']
        assert rep['changed_ratio'] == 0.0
        # 反向例：同样新增，但改掉一个既有图位描述 ⇒ 50% 变更（仍不越界）；
        # 改掉两个 ⇒ 100% 越界，证明分子确实只由既有图决定
        c2 = draft(work_root, 'current2.md',
                   [('1-1', '改'), ('1-2', '改'), ('1-3', '新增图')])
        r2 = drift_cli(f, c2)
        assert r2.returncode == pg.EXIT_DECISION, r2.stdout + r2.stderr

    def test_T_B3_19_empty_frozen_is_input_error(self, work_root):
        f = draft(work_root, 'frozen.md', [])
        c = draft(work_root, 'current.md', [('1-1', '传播链')])
        r = drift_cli(f, c)
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '无基准' in r.stderr

    def test_T_B3_20_duplicate_slot_conflict_is_input_error(self, work_root):
        f = draft(work_root, 'frozen.md', [('1-1', '传播链'), ('1-1', '另一描述')])
        c = draft(work_root, 'current.md', [('1-1', '传播链')])
        r = drift_cli(f, c)
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '重复且描述不一致' in r.stderr

    def test_T_B3_21_figure_regex_is_single_ssot(self):
        """防漂移：图表位正则必须来自 check_manuscript.py，不得复制第二份。"""
        assert pg.RE_FIGURE_SLOT.pattern == cm.RE_FIGURE_SLOT.pattern

    def test_T_B3_22_write_trace_only_on_fallback_and_compliant(self, work_root):
        """回退时经 record_trace.py 写合规 STATUS；正常路径一行不写。"""
        f = draft(work_root, 'frozen.md', [('1-1', '传播链'), ('1-2', '发病率')])
        c_ok = draft(work_root, 'ok.md', [('1-1', '传播链'), ('1-2', '发病率')])
        c_bad = draft(work_root, 'bad.md', [('1-1', '改'), ('1-2', '改')])
        wr = str(work_root / 'ws')
        base = ['--work-root', wr, '--write-trace']
        r_ok = run_cli('visual-drift', '--frozen', f, '--current', c_ok,
                       '--chapter', 'ch01', *base)
        assert r_ok.returncode == pg.EXIT_OK, r_ok.stdout + r_ok.stderr
        trace = Path(wr) / '运行态' / 'trace.jsonl'
        assert not trace.exists(), '正常路径不得污染 trace'
        r_bad = run_cli('visual-drift', '--frozen', f, '--current', c_bad,
                        '--chapter', 'ch01', *base)
        assert r_bad.returncode == pg.EXIT_DECISION, r_bad.stdout + r_bad.stderr
        rec = json.loads(trace.read_text(encoding='utf-8').splitlines()[-1])
        assert rec['type'] == 'STATUS' and rec['phase'] == 'VISUALIZE'
        assert rec['start'] and not rec.get('timing_degraded')
        assert 'VISUALIZE_PARALLEL_FALLBACK' in rec['notes']

    def test_T_B3_23_bad_chapter_is_input_error(self, work_root):
        f = draft(work_root, 'frozen.md', [('1-1', '传播链')])
        c = draft(work_root, 'current.md', [('1-1', '传播链')])
        r = drift_cli(f, c, chapter='chapter1')
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr

    def test_T_B3_24_threshold_out_of_range_is_input_error(self, work_root):
        f = draft(work_root, 'frozen.md', [('1-1', '传播链')])
        c = draft(work_root, 'current.md', [('1-1', '传播链')])
        r = run_cli('visual-drift', '--frozen', f, '--current', c,
                    '--chapter', 'ch01', '--threshold', '1.5')
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr

    def test_T_B3_25_same_file_drift_compare_rejected(self, work_root):
        f = draft(work_root, 'frozen.md', [('1-1', '传播链')])
        r = drift_cli(f, f)
        assert r.returncode == pg.EXIT_INPUT_ERROR, r.stdout + r.stderr
        assert '同一文件' in r.stderr
