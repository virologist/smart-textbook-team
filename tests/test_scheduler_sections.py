#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scheduler_sections.py — Batch 4 升级 B：节级拓扑波次调度回归

验收重点（诊断 §3.2 升级 B / Q2）：
  ① strong-dep / no-dep 拓扑分波（波内并行、波间串行）
  ② 并发度**复用章级 Q2 四级授权**，不另立默认值
  ③ token 预算不足 ⇒ 波次降为串行（优雅退化，不截断执行）
  ④ 解析歧义/成环/矛盾 ⇒ exit 2 或 1，绝不静默当「无依赖」放行
  ⑤ 反向例纪律：每个拒绝/降级判定都有「修好后翻绿」对照
  ⑥ 默认 --mode chapters 行为不变（既有调用方兼容）

运行：python3 -m pytest tests/test_scheduler_sections.py -q
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

import scheduler as sch  # noqa: E402

HEADER = sch.SECTION_DEPS_HEADER
R11 = ('1.1', '—', 'yes', 'T1,T2', '800')
R12 = ('1.2', '1.1', 'no', 'T3', '1200')
R13 = ('1.3', '—', 'yes', '—', '900')


@pytest.fixture()
def work_root():
    d = tempfile.mkdtemp(prefix='stt_sched_sec_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def design(root: Path, rows: list[tuple] | None = None,
           chapter: str = 'ch01', *, with_table: bool = True,
           header: tuple = HEADER, sep: bool = True) -> Path:
    """生成含 §C.1 依赖表的 chapter_design.md。"""
    rows = [R11, R12, R13] if rows is None else rows
    lines = ['# chapter_design', '', '## C. 分节写作计划', '',
             '| 节号 | 节标题 | 字数目标 |', '| --- | --- | --- |',
             '| 1.1 | 概述 | 800 |', '', '## C.1 节依赖标注', '']
    if with_table:
        lines.append(sch.SECTION_DEPS_BEGIN)
        lines.append('| ' + ' | '.join(header) + ' |')
        if sep:
            lines.append('| ' + ' | '.join(['---'] * len(header)) + ' |')
        for row in rows:
            lines.append('| ' + ' | '.join(row) + ' |')
        lines.append(sch.SECTION_DEPS_END)
    p = root / '章节' / chapter / 'chapter_design.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return p


def run_plan(root: Path, *extra: str, env: dict | None = None):
    # 默认隔离 Q2 的三个环境变量 ⇒ 「无授权退化串行」等断言不受宿主环境干扰；
    # 显式传 env 的用例（T_B4_08）自行构造，验证环境变量授权确实生效。
    if env is None:
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ('STB_MAX_CONCURRENCY', 'STB_RATE_LIMIT',
                            'STB_TOKEN_BUDGET')}
    cmd = [sys.executable, str(SCRIPTS / 'scheduler.py'),
           '--work-root', str(root), 'plan', '--mode', 'sections',
           '--chapter', 'ch01', '--json']
    return subprocess.run(cmd + list(extra), capture_output=True, text=True,
                          env=env)


def ok_plan(root: Path, *extra: str) -> dict:
    r = run_plan(root, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


# ── 1. 拓扑波次 ─────────────────────────────────────────────────────────

class TestWaves:
    def test_T_B4_01_two_waves_by_strong_dep(self, work_root):
        design(work_root)
        p = ok_plan(work_root)
        assert [w['sections'] for w in p['waves']] == [['1.1', '1.3'], ['1.2']]
        assert p['mode'] == 'sections' and p['chapter'] == 'ch01'

    def test_T_B4_02_chain_produces_three_waves(self, work_root):
        rows = [('1.1', '—', 'yes', 'T1', '800'),
                ('1.2', '1.1', 'no', 'T2', '800'),
                ('1.3', '1.2', 'no', 'T3', '800')]
        design(work_root, rows)
        p = ok_plan(work_root)
        assert [w['sections'] for w in p['waves']] == [['1.1'], ['1.2'], ['1.3']]

    def test_T_B4_03_cycle_rejected_with_reverse(self, work_root):
        rows = [('1.1', '1.2', 'no', 'T1', '800'),
                ('1.2', '1.1', 'no', 'T2', '800')]
        design(work_root, rows)
        r = run_plan(work_root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert json.loads(r.stdout)['reason'] == 'SECTION_DEPENDENCY_CYCLE'
        # 反向例：去掉一条边 ⇒ 必须翻绿
        design(work_root, [('1.1', '—', 'yes', 'T1', '800'),
                           ('1.2', '1.1', 'no', 'T2', '800')])
        assert run_plan(work_root).returncode == 0

    def test_T_B4_04_tasks_carry_must_produce_and_terms(self, work_root):
        design(work_root)
        p = ok_plan(work_root)
        t2 = p['waves'][1]['tasks'][0]
        assert t2['节号'] == '1.2'
        assert t2['must_produce'] == '章节/ch01/sections/1.2.md'
        assert t2['task_id'] == 'ch01-PRODUCE-R1-节1.2'
        assert t2['strong_dep'] == ['1.1']
        assert t2['required_terms'] == ['T1', 'T2']  # 上游 1.1 的关键术语
        assert p['waves'][0]['tasks'][0]['required_terms'] == []


# ── 2. Q2 并发度四级授权 ────────────────────────────────────────────────

class TestConcurrency:
    def test_T_B4_05_no_authorization_degrades_to_serial(self, work_root):
        design(work_root)
        p = ok_plan(work_root)
        assert p['concurrency'] == 1
        assert any('退化为串行' in n for n in p['concurrency_notes'])

    def test_T_B4_06_explicit_concurrency_with_reverse(self, work_root):
        design(work_root)
        p = ok_plan(work_root, '--max-concurrency', '2')
        assert p['concurrency'] == 2
        assert p['waves'][0]['concurrency'] == 2
        assert p['waves'][1]['concurrency'] == 1   # 波内只有 1 节
        # 反向例：不给授权 ⇒ 回到 1（证明并发度不是写死的）
        assert ok_plan(work_root)['concurrency'] == 1

    def test_T_B4_07_branch_cap_applies(self, work_root):
        rows = [(f'1.{i}', '—', 'yes', '—', '500') for i in range(1, 8)]
        design(work_root, rows)
        p = ok_plan(work_root, '--max-concurrency', '99')
        assert p['concurrency'] == sch.BRANCH_CAP == 5
        assert any('硬上限' in n for n in p['concurrency_notes'])

    def test_T_B4_08_env_max_concurrency(self, work_root):
        import os
        design(work_root)
        env = dict(os.environ)
        env.pop('STB_MAX_CONCURRENCY', None)
        env.pop('STB_RATE_LIMIT', None)
        env['STB_MAX_CONCURRENCY'] = '2'
        r = run_plan(work_root, env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)['concurrency'] == 2


# ── 3. 预算降级串行 ─────────────────────────────────────────────────────

class TestBudgetDegrade:
    def test_T_B4_09_over_budget_degrades_with_reverse(self, work_root):
        design(work_root)
        low = ok_plan(work_root, '--token-budget', '1000',
                      '--max-concurrency', '2')
        assert low['waves'][0]['budget_degraded'] is True
        assert low['waves'][0]['concurrency'] == 1
        assert any('降为串行' in n for n in low['concurrency_notes'])
        # 反向例：预算充足 ⇒ 不降级、保持并发（证明降级不是恒真）
        high = ok_plan(work_root, '--token-budget', '10000000',
                       '--max-concurrency', '2')
        assert high['waves'][0]['budget_degraded'] is False
        assert high['waves'][0]['concurrency'] == 2

    def test_T_B4_10_no_budget_does_not_degrade(self, work_root):
        design(work_root)
        p = ok_plan(work_root, '--max-concurrency', '2')
        assert p['token_budget'] is None
        assert all(not w['budget_degraded'] for w in p['waves'])


# ── 4. 输入契约：不得静默放行 ───────────────────────────────────────────

class TestInputContract:
    @pytest.mark.parametrize('case,rows,kw', [
        ('unknown_dep', [('1.1', '9.9', 'no', 'T1', '800')], {}),
        ('contradiction', [('1.1', '1.2', 'yes', 'T1', '800'),
                           ('1.2', '—', 'no', 'T2', '800')], {}),
        ('bad_words', [('1.1', '—', 'yes', 'T1', '很多')], {}),
        ('zero_words', [('1.1', '—', 'yes', 'T1', '0')], {}),
        ('duplicate', [('1.1', '—', 'yes', 'T1', '800'),
                       ('1.1', '—', 'yes', 'T2', '800')], {}),
        ('bad_bool', [('1.1', '—', 'maybe', 'T1', '800')], {}),
        ('empty_table', [], {}),
        ('bad_header', [R11], {'header': ('节号', 'strong-dep', 'no-dep', '关键术语')}),
    ])
    def test_T_B4_11_invalid_table_rejected(self, work_root, case, rows, kw):
        design(work_root, rows, **kw)
        r = run_plan(work_root)
        assert r.returncode == 2, f'{case}: {r.stdout + r.stderr}'
        assert json.loads(r.stdout)['reason'] == 'SECTION_DEPS_INVALID'

    def test_T_B4_12_missing_table_rejected_with_reverse(self, work_root):
        design(work_root, with_table=False)
        r = run_plan(work_root)
        assert r.returncode == 2, r.stdout + r.stderr
        assert '不得按' in json.loads(r.stdout)['detail']
        # 反向例：补回表 ⇒ 翻绿
        design(work_root)
        assert run_plan(work_root).returncode == 0

    def test_T_B4_13_column_mismatch_rejected(self, work_root):
        p = design(work_root)
        txt = p.read_text(encoding='utf-8').replace(
            '| 1.2 | 1.1 | no | T3 | 1200 |', '| 1.2 | 1.1 | no | T3 |')
        p.write_text(txt, encoding='utf-8')
        r = run_plan(work_root)
        assert r.returncode == 2, r.stdout + r.stderr
        assert '列错位' in json.loads(r.stdout)['detail']

    def test_T_B4_14_bad_chapter_rejected(self, work_root):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / 'scheduler.py'),
             '--work-root', str(work_root), 'plan', '--mode', 'sections',
             '--chapter', 'chapter1'], capture_output=True, text=True)
        assert r.returncode == 2, r.stdout + r.stderr

    def test_T_B4_15_default_mode_chapters_unchanged(self, work_root):
        """兼容反向例：不带 --mode 时仍走章级 plan（无 book-spec ⇒ exit 2）。"""
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / 'scheduler.py'),
             '--work-root', str(work_root), 'plan', '--json'],
            capture_output=True, text=True)
        assert r.returncode == 2, r.stdout + r.stderr
        assert json.loads(r.stdout)['reason'] == 'BOOK_SPEC_MISSING'
