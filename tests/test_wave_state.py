#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_wave_state.py — R2 批次：波次状态落盘 + 契约回写 + 主理人裁决

验收重点（实施后复诊 R2）：
  ① 波次计划**有持久化锚点**（`运行态/wave_{ch##}_w{n}.json`）——
     修复「B4 波次只 print 到 stdout」⇒ 契约回写/效率指标/断点续跑三处断链
  ② **计划与授权分离**：`wave_verdict` 初始 `PENDING`，脚本**不得**自行写；
     正式裁决由主理人落定（READY|BLOCKED|BUDGET_DEGRADED）
  ③ `plan_hash` **只覆盖内容**——并发授权变化不得让指纹改变
  ④ 契约回写口径与 `count_net_words.py` **同源**
  ⑤ 非法输入**不落盘**；落盘失败**显式报错**（不静默）
  ⑥ 效率指标 `wave_time` / `parallel_gain` 有数据源，且**不静默当 0**
  ⑦ 反向例纪律：每个拒绝/降级判定都有「修好后翻绿」对照

运行：python3 -m pytest tests/test_wave_state.py -q
"""
from __future__ import annotations

import json
import os
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
    d = tempfile.mkdtemp(prefix='stt_wave_state_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def design(root: Path, rows: list[tuple] | None = None,
           chapter: str = 'ch01', *, with_table: bool = True) -> Path:
    """生成含 §C.1 依赖表的 chapter_design.md。"""
    rows = [R11, R12, R13] if rows is None else rows
    lines = ['# chapter_design', '', '## C. 分节写作计划', '',
             '| 节号 | 节标题 | 字数目标 |', '| --- | --- | --- |',
             '| 1.1 | 概述 | 800 |', '', '## C.1 节依赖标注', '']
    if with_table:
        lines.append(sch.SECTION_DEPS_BEGIN)
        lines.append('| ' + ' | '.join(HEADER) + ' |')
        lines.append('| ' + ' | '.join(['---'] * len(HEADER)) + ' |')
        for row in rows:
            lines.append('| ' + ' | '.join(row) + ' |')
        lines.append(sch.SECTION_DEPS_END)
    p = root / '章节' / chapter / 'chapter_design.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return p


def _env() -> dict:
    """隔离 Q2 三个环境变量 ⇒ 并发授权断言不受宿主环境干扰。"""
    return {k: v for k, v in os.environ.items()
            if k not in ('STB_MAX_CONCURRENCY', 'STB_RATE_LIMIT',
                         'STB_TOKEN_BUDGET')}


def run_plan(root: Path, *extra: str, env: dict | None = None):
    if env is None:
        env = _env()
    cmd = [sys.executable, str(SCRIPTS / 'scheduler.py'),
           '--work-root', str(root), 'plan', '--mode', 'sections',
           '--chapter', 'ch01', '--json']
    return subprocess.run(cmd + list(extra), capture_output=True, text=True,
                          env=env)


def ok_plan(root: Path, *extra: str) -> dict:
    r = run_plan(root, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def run_check(root: Path, *extra: str):
    cmd = [sys.executable, str(SCRIPTS / 'contract_check.py'),
           '--work-root', str(root), '--chapter', 'ch01']
    return subprocess.run(cmd + list(extra), capture_output=True, text=True)


def write_section(root: Path, sec: str, text: str) -> Path:
    p = root / '章节' / 'ch01' / 'sections' / f'{sec}.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


# ── 1. 落盘：锚点存在且字段完整 ────────────────────────────────────────

class TestWaveStateWrite:
    def test_T_R2_01_wave_states_written(self, work_root):
        """全部波次都落盘为 运行态/wave_{ch##}_w{n}.json。"""
        design(work_root)
        r = run_plan(work_root, '--write-wave-state')
        assert r.returncode == 0, r.stdout + r.stderr
        d = work_root / '运行态'
        files = sorted(p.name for p in d.glob('wave_ch01_w*.json'))
        assert files == ['wave_ch01_w1.json', 'wave_ch01_w2.json']

    def test_T_R2_02_schema_and_out_waves_fields_preserved(self, work_root):
        """顶层保留既有 out_waves 全字段（既有消费方按同一形状读取）。"""
        design(work_root)
        p = ok_plan(work_root, '--write-wave-state')
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['schema'] == 'stt.wave_state/1'
        assert st['chapter'] == 'ch01'
        for key in ('wave_id', 'sections', 'concurrency', 'estimated_tokens',
                    'budget_degraded', 'tasks'):
            assert key in st, f'缺 out_waves 字段 {key}'
        # 值与 plan 一致（不是另算一份）
        w0 = p['waves'][0]
        assert st['wave_id'] == w0['wave_id']
        assert st['sections'] == w0['sections']
        assert st['concurrency'] == w0['concurrency']
        assert st['estimated_tokens'] == w0['estimated_tokens']
        assert st['budget_degraded'] == w0['budget_degraded']
        assert len(st['tasks']) == len(w0['tasks'])

    def test_T_R2_03_verdict_pending_and_proposed(self, work_root):
        """wave_verdict 初始 PENDING；proposed_verdict 是机器建议。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['wave_verdict'] == 'PENDING'
        assert st['proposed_verdict'] == 'READY'
        assert st['verdict_by'] is None and st['verdict_at'] is None

    def test_T_R2_04_proposed_degraded_on_budget_overrun(self, work_root):
        """预算不足 ⇒ proposed_verdict=BUDGET_DEGRADED（机器建议）。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state', '--token-budget', '1000',
                '--max-concurrency', '2')
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['budget_degraded'] is True
        assert st['proposed_verdict'] == 'BUDGET_DEGRADED'
        # 反向例：预算充足 ⇒ 回到 READY（证明不是恒真）
        ok_plan(work_root, '--write-wave-state', '--token-budget', '10000000',
                '--max-concurrency', '2')
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['budget_degraded'] is False
        assert st['proposed_verdict'] == 'READY'

    def test_T_R2_05_contract_snapshot_per_section(self, work_root):
        """contract 快照按节号记录任务契约；net_words 初始为 None。

        术语有两个方向，缺一不可：
          · `defined_terms` = 本节**定义/首用**的术语（§C.1「关键术语」列）
          · `required_terms` = **上游注入**、本节须沿用的术语
        """
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert set(st['contract']) == {'1.1', '1.3'}
        assert st['net_words'] == {'1.1': None, '1.3': None}
        e = st['contract']['1.1']
        assert e['task_id'] == 'ch01-PRODUCE-R1-节1.1'
        assert e['must_produce'] == '章节/ch01/sections/1.1.md'
        assert e['produced'] is False
        # 本节定义 T1,T2；无上游 ⇒ 无注入项
        assert e['defined_terms'] == ['T1', 'T2']
        assert e['required_terms'] == []
        # 下游 1.2 强依赖 1.1 ⇒ 注入 1.1 的术语
        st2 = json.loads((work_root / '运行态' / 'wave_ch01_w2.json')
                         .read_text(encoding='utf-8'))
        assert st2['contract']['1.2']['required_terms'] == ['T1', 'T2']
        assert st2['contract']['1.2']['defined_terms'] == ['T3']


# ── 2. plan_hash：只覆盖内容，不受授权影响 ──────────────────────────────

class TestPlanHash:
    def test_T_R2_06_hash_stable_across_concurrency_authorization(self, work_root):
        """并发授权变化不得改变 plan_hash（授权不是「计划变更」）。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        h1 = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))['plan_hash']
        ok_plan(work_root, '--write-wave-state', '--max-concurrency', '3')
        h2 = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))['plan_hash']
        assert h1 == h2
        assert h1.startswith('sha256:') and len(h1) == len('sha256:') + 64

    def test_T_R2_07_hash_changes_when_contract_changes(self, work_root):
        """契约内容变化 ⇒ 指纹必须变（否则「计划已变更」会漏报）。

        三个维度各测一次：字数目标、术语定义、依赖关系。
        """
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        h1 = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))['plan_hash']
        # ① 术语定义变化（defined_terms）⇒ 指纹必须变
        design(work_root, [('1.1', '—', 'yes', 'T1,T2', '800'),
                           ('1.2', '1.1', 'no', 'T3', '1200'),
                           ('1.3', '—', 'yes', 'T9', '900')])
        ok_plan(work_root, '--write-wave-state')
        h2 = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))['plan_hash']
        assert h1 != h2, '术语定义变了，指纹却没变 ⇒ 漏报「计划已变更」'

    def test_T_R2_07b_hash_changes_when_word_budget_changes(self, work_root):
        """字数目标变化 ⇒ 指纹必须变（预算降级判据依赖它）。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        h1 = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))['plan_hash']
        design(work_root, [('1.1', '—', 'yes', 'T1,T2', '999'),
                           ('1.2', '1.1', 'no', 'T3', '1200'),
                           ('1.3', '—', 'yes', '—', '900')])
        ok_plan(work_root, '--write-wave-state')
        h2 = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))['plan_hash']
        assert h1 != h2


# ── 3. 计划与授权分离：脚本不写 wave_verdict ───────────────────────────

class TestVerdictSeparation:
    def test_T_R2_08_script_never_writes_verdict(self, work_root):
        """落盘/回写都不得写 wave_verdict——授权判断归主理人。"""
        design(work_root)
        write_section(work_root, '1.1', '# 1.1\n\n正文内容。\n')
        ok_plan(work_root, '--write-wave-state')
        r = run_check(work_root, '--wave', '1', '--json')
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout)
        assert out['wave_verdict'] == 'PENDING'
        assert out['verdict_untouched'] is True
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['wave_verdict'] == 'PENDING'

    def test_T_R2_09_lead_verdict_persisted(self, work_root):
        """主理人裁决落定后 wave_verdict 被写入并带裁决元信息。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        r = run_check(work_root, '--wave', '1', '--verdict', 'READY',
                      '--verdict-reason', '本波 2 节全部交付', '--json')
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout)
        assert out['wave_verdict'] == 'READY'
        assert out['verdict_by'] == 'smart-textbook-team-team-lead'
        assert out['verdict_reason'] == '本波 2 节全部交付'
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['wave_verdict'] == 'READY'
        assert st['verdict_at']

    def test_T_R2_10_illegal_verdict_rejected(self, work_root):
        """非法裁决值 ⇒ 报错退出，不静默写入。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        r = run_check(work_root, '--wave', '1', '--verdict', 'MAYBE')
        assert r.returncode == 4, r.stdout + r.stderr
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['wave_verdict'] == 'PENDING'   # 未被污染

    def test_T_R2_11_verdict_requires_wave(self, work_root):
        """--verdict 必须配合 --wave（不知道改哪个波次 ⇒ 拒绝）。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        r = run_check(work_root, '--verdict', 'READY')
        assert r.returncode == 4, r.stdout + r.stderr


# ── 4. 契约回写：produced / net_words / reason ──────────────────────────

class TestContractPatch:
    def test_T_R2_12_patch_marks_delivered_with_net_words(self, work_root):
        """回写标记 produced 并按 SSOT 口径算净字数。"""
        design(work_root)
        write_section(work_root, '1.1', '# 1.1 概述\n\n这里是正文内容。\n')
        ok_plan(work_root, '--write-wave-state')
        r = run_check(work_root, '--wave', '1', '--json')
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout)
        assert out['delivered'] == ['1.1']
        assert out['missing'] == ['1.3']
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        assert st['contract']['1.1']['produced'] is True
        assert st['contract']['1.3']['produced'] is False
        assert st['net_words']['1.1'] == out['net_words']['1.1']
        assert st['net_words']['1.1'] > 0
        assert st['net_words']['1.3'] is None
        assert '已交付 1/2 节' in st['reason']
        assert st['patched_by'] == 'contract_check.py'

    def test_T_R2_13_net_words_same_source_as_count_net_words(self, work_root):
        """回写净字数与 count_net_words.py 逐字一致（同源口径）。"""
        from count_net_words import count_net_words
        design(work_root)
        body = '# 1.1 概述\n\n测试字数用的示例句子。[图 1：结构示意]\n'
        write_section(work_root, '1.1', body)
        ok_plan(work_root, '--write-wave-state')
        run_check(work_root, '--wave', '1', '--json')
        st = json.loads((work_root / '运行态' / 'wave_ch01_w1.json')
                        .read_text(encoding='utf-8'))
        want = count_net_words(body)['net_final']
        assert st['net_words']['1.1'] == want

    def test_T_R2_14_patch_missing_state_file_errors(self, work_root):
        """波次状态文件不存在 ⇒ 报错退出（不静默跳过）。"""
        design(work_root)
        r = run_check(work_root, '--wave', '9', '--json')
        assert r.returncode == 4, r.stdout + r.stderr

    def test_T_R2_15_patch_rejects_schema_mismatch(self, work_root):
        """schema 不匹配 ⇒ 拒绝回写（宁可报错也不污染锚点）。"""
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        p = work_root / '运行态' / 'wave_ch01_w1.json'
        st = json.loads(p.read_text(encoding='utf-8'))
        st['schema'] = 'stt.wave_state/999'
        p.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
        r = run_check(work_root, '--wave', '1', '--json')
        assert r.returncode == 4, r.stdout + r.stderr


# ── 5. 落盘失败显式报错；非法输入不落盘 ────────────────────────────────

class TestFailureHandling:
    def test_T_R2_16_invalid_table_does_not_write_state(self, work_root):
        """§C.1 表非法 ⇒ 不落盘波次状态（绝不把失败计划写成事实）。"""
        design(work_root, [('1.1', '9.9', 'no', 'T1', '800')])
        r = run_plan(work_root, '--write-wave-state')
        assert r.returncode == 2, r.stdout + r.stderr
        assert not (work_root / '运行态').exists() or \
            not list((work_root / '运行态').glob('wave_ch01_w*.json'))

    def test_T_R2_17_cycle_does_not_write_state(self, work_root):
        """依赖成环 ⇒ 不落盘。"""
        design(work_root, [('1.1', '1.2', 'no', 'T1', '800'),
                           ('1.2', '1.1', 'no', 'T2', '800')])
        r = run_plan(work_root, '--write-wave-state')
        assert r.returncode == 1, r.stdout + r.stderr
        assert not list((work_root / '运行态').glob('wave_ch01_w*.json'))

    def test_T_R2_18_write_failure_explicit(self, work_root, monkeypatch):
        """落盘失败 ⇒ 显式报错 + exit 5（不得静默放行派工）。"""
        design(work_root)
        # 让 运行态/ 变成一个**文件**（不是目录）⇒ mkdir 必然失败
        (work_root / '运行态').write_text('block', encoding='utf-8')
        r = run_plan(work_root, '--write-wave-state')
        assert r.returncode == 5, r.stdout + r.stderr
        assert '落盘失败' in (r.stdout + r.stderr)

    def test_T_R2_19_write_failure_with_reverse(self, work_root):
        """反向例：去掉阻断后 ⇒ 翻绿（exit 0 且文件落盘）。"""
        design(work_root)
        (work_root / '运行态').write_text('block', encoding='utf-8')
        assert run_plan(work_root, '--write-wave-state').returncode == 5
        (work_root / '运行态').unlink()
        assert run_plan(work_root, '--write-wave-state').returncode == 0
        assert list((work_root / '运行态').glob('wave_ch01_w*.json'))


# ── 6. 效率指标：wave_time / parallel_gain ─────────────────────────────

class TestWaveMetrics:
    def _trace(self, root: Path, task_id: str, start: str, dur: int):
        import datetime as _dt
        s = _dt.datetime.fromisoformat(start)
        e = s + _dt.timedelta(milliseconds=dur)
        p = root / '运行态' / 'trace.jsonl'
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            'task_id': task_id, 'correlation_id': 'ch01',
            'from': 'smart-textbook-team-subject-writer',
            'to': 'smart-textbook-team-team-lead',
            'type': 'RESULT', 'outcome': 'OK', 'duration_ms': dur,
            'phase': 'PRODUCE-R1', 'start': s.isoformat(),
            'ts': e.isoformat(),
        }
        with p.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def test_T_R2_20_wave_time_and_gain_computed(self, work_root):
        """wave_time = 波次墙钟；parallel_gain = 串行基准 ÷ 墙钟。"""
        import compute_metrics as cm
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        base = '2026-11-05T00:00:00+00:00'
        # w1 = [1.1, 1.3]（无依赖同波）；两节并行：各 1000ms，同时起跑
        self._trace(work_root, 'ch01-PRODUCE-R1-节1.1', base, 1000)
        self._trace(work_root, 'ch01-PRODUCE-R1-节1.3', base, 1000)
        traces, _ = cm.load_traces(work_root)
        m = cm.compute(traces, work_root=work_root)
        wm = m['wave_metrics']
        assert wm is not None
        w1 = [w for w in wm['waves'] if w['wave_id'] == 1][0]
        assert w1['wave_time_ms'] == 1000            # 并行 ⇒ 墙钟 = 单节耗时
        assert w1['serial_baseline_ms'] == 2000     # 串行基准 = 两节之和
        assert w1['parallel_gain'] == 2.0           # 2 倍加速

    def test_T_R2_21_serial_wave_gain_is_one(self, work_root):
        """单节波 ⇒ gain = 1.0（无并行收益，不是虚构加速）。"""
        import compute_metrics as cm
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        base = '2026-11-05T00:00:00+00:00'
        self._trace(work_root, 'ch01-PRODUCE-R1-节1.2', base, 1500)
        traces, _ = cm.load_traces(work_root)
        m = cm.compute(traces, work_root=work_root)
        w2 = [w for w in m['wave_metrics']['waves'] if w['wave_id'] == 2][0]
        assert w2['wave_time_ms'] == 1500
        assert w2['parallel_gain'] == 1.0

    def test_T_R2_22_no_wave_state_gives_none_not_zero(self, work_root):
        """无波次锚点 ⇒ None + 说明，**不静默当 0**。"""
        import compute_metrics as cm
        design(work_root)
        traces, _ = cm.load_traces(work_root)
        m = cm.compute(traces, work_root=work_root)
        assert m['wave_time_ms'] is None
        assert m['parallel_gain'] is None
        assert m['wave_metrics'] is None

    def test_T_R2_23_wave_state_without_trace_is_data_insufficient(self, work_root):
        """有锚点但无可判定 trace ⇒ None + 说明，不是「耗时 0」。"""
        import compute_metrics as cm
        design(work_root)
        ok_plan(work_root, '--write-wave-state')
        traces, _ = cm.load_traces(work_root)
        m = cm.compute(traces, work_root=work_root)
        assert m['wave_time_ms'] is None
        assert m['parallel_gain'] is None
        assert m['wave_metrics']['waves'] == []
        assert '数据不足' in m['wave_metrics']['note']
