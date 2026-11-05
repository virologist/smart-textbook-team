#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_protocol_eval.py — 协议组件评测集（R1 · 复诊 §3.2 R1）

为什么要有这个文件
==================
首诊 §3.4.2 的五环闭环「指标 → 学习 → 协议修订 → **评测回归** → 新基线」，
「评测回归」是唯一的**验证闸门**——它决定「协议改完到底有没有变好」。
此前 `protocol-eval` 只在 `skills/learn-protocol/SKILL.md` §流程第 4 步
以文字存在，**零实现** ⇒ 改协议变成盲改。

本文件与 `scripts/protocol_eval.py` 的分工
=========================================
  · `scripts/protocol_eval.py` —— **评测执行体**：跑 5 个协议组件的离线评测，
    输出 0-1 分数 + 失败项清单，门槛 ≥0.80（与 router eval 同门槛）。
  · `tests/test_protocol_eval.py`（本文件）—— **评测集的护栏**：验证评测集
    本身是否有效，尤其是**反向例**（注入缺陷后评测集必须 FAIL）。

⚠️ 最关键的一条纪律
====================
**评测集全绿本身不能证明评测集有效**——它可能只是「什么都没测」。
因此本文件的核心是**反向注入**：把真实组件的行为改坏（改阈值、改顺序、
改状态机、改判据），评测集**必须**报 FAIL 且分数跌破门槛。
若注入缺陷后评测集仍然全绿 ⇒ 该组件的评测用例是自证的，必须补用例。

用例编号约定：`T_PE_01` …（pytest 侧）/ `PE-R*` …（评测集侧）
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = PKG_ROOT / 'scripts'
EVAL_SCRIPT = SCRIPT_DIR / 'protocol_eval.py'


def _load_module(name: str, path: Path):
    """按路径加载模块（不走 sys.path，避免与包内其它模块名冲突）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f'无法加载 {path}'
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pe = _load_module('_stt_test_protocol_eval', EVAL_SCRIPT)


def _tmpdir(prefix: str) -> Path:
    """沙箱环境下 pytest 的 tmp_path 不可用（broker 拦截 /var/folders），
    改用 tempfile.mkdtemp（与包内其它测试一致）。"""
    return Path(tempfile.mkdtemp(prefix=prefix))


# ═══════════════════════════════════════════════════════════════════════
# A 组：评测执行体基本契约
# ═══════════════════════════════════════════════════════════════════════
class TestEvalContract:
    """评测执行体的输出格式与门禁契约。"""

    def test_pe_01_builtin_cases_cover_five_components(self):
        """T_PE_01: 首批 5 组件必须全部有评测用例。"""
        cases = pe.builtin_cases()
        comps = {c['component'] for c in cases}
        expected = {'routing-threshold', 'circuit-breaker', 'budget-priority',
                    'section-topology', 'recovery-classification'}
        assert expected <= comps, f'缺组件评测用例: {expected - comps}'

    def test_pe_02_case_ids_unique(self):
        """T_PE_02: 用例 ID 必须唯一（否则失败项清单会混淆）。"""
        cases = pe.builtin_cases()
        ids = [c['id'] for c in cases]
        assert len(ids) == len(set(ids)), '用例 ID 有重复'

    def test_pe_03_builtin_cases_all_pass(self):
        """T_PE_03: 内置评测集当前应全绿（真实组件行为符合协议）。"""
        report = pe.run_cases(pe.builtin_cases())
        assert report['failed'] == 0, (
            f'内置评测集有 {report["failed"]} 项失败: '
            f'{[(f["id"], f["detail"]) for f in report["failures"]]}')
        assert report['score'] >= pe.DEFAULT_THRESHOLD

    def test_pe_04_report_schema_fields(self):
        """T_PE_04: 输出格式 =「分数 + 失败项清单」（与 router eval 对齐）。"""
        report = pe.run_cases(pe.builtin_cases())
        assert report['schema'] == 'stt.protocol_eval/1'
        for k in ('score', 'passed', 'failed', 'total',
                  'per_component', 'failures'):
            assert k in report, f'报告缺字段 {k}'
        assert 0.0 <= report['score'] <= 1.0

    def test_pe_05_json_output_machine_parsable(self):
        """T_PE_05: `--json` 输出不得被组件 stdout 污染。

        反向意义：被测组件（e3_window.record 等）直接 print 到 stdout，
        若不抑制，`--json` 就不是合法 JSON ⇒ 机器读不了评测结果。
        """
        r = subprocess.run([sys.executable, str(EVAL_SCRIPT), '--json'],
                           capture_output=True, text=True, timeout=180,
                           cwd=str(PKG_ROOT))
        assert r.returncode == 0, f'exit={r.returncode} stderr={r.stderr[:400]}'
        data = json.loads(r.stdout)          # 解析失败会直接抛异常
        assert data['schema'] == 'stt.protocol_eval/1'
        assert data['passed_gate'] is True

    def test_pe_06_exit_codes_gate(self):
        """T_PE_06: 门槛语义——低于阈值必须 exit 1（拒绝合入）。"""
        r = subprocess.run([sys.executable, str(EVAL_SCRIPT), '--threshold', '1.01'],
                           capture_output=True, text=True, timeout=180,
                           cwd=str(PKG_ROOT))
        assert r.returncode == 1, f'阈值不可能达到时应 exit 1，实为 {r.returncode}'

    def test_pe_07_single_component_eval(self):
        """T_PE_07: `--component` 单独评测某组件（门禁接入需要）。"""
        r = subprocess.run(
            [sys.executable, str(EVAL_SCRIPT), '--component', 'circuit-breaker',
             '--json'],
            capture_output=True, text=True, timeout=180, cwd=str(PKG_ROOT))
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data['per_component']) == 1
        assert data['per_component'][0]['component'] == 'circuit-breaker'

    def test_pe_08_invalid_cases_exit_3(self):
        """T_PE_08: 用例集结构非法必须 exit 3（明确报错，不静默放行）。"""
        tmp = _tmpdir('stt-pe-bad-')
        try:
            bad = tmp / 'bad.json'
            bad.write_text(json.dumps([{'id': 'X'}]), encoding='utf-8')  # 缺 component
            r = subprocess.run(
                [sys.executable, str(EVAL_SCRIPT), '--cases', str(bad)],
                capture_output=True, text=True, timeout=180, cwd=str(PKG_ROOT))
            assert r.returncode == 3, f'实为 {r.returncode}'
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# B 组：反向注入 —— 评测集必须能抓出真实缺陷
# ═══════════════════════════════════════════════════════════════════════
class TestReverseInjection:
    """核心纪律：注入缺陷后评测集必须 FAIL。

    若某组件在注入缺陷后仍全绿 ⇒ 该组件的评测用例是自证的，
    必须补用例（本测试即护栏）。
    """

    def test_pe_10_broken_circuit_threshold_must_fail(self):
        """T_PE_10: 把 E3 阈值从 2 改成 99（熔断永不触发）⇒ 评测集必须 FAIL。

        这验证 circuit-breaker 组件的用例真在评熔断行为，而非空转。

        ⚠ 注意断言的是**组件级底线**而非总分：实测把熔断改坏后总分仍
        0.882 ≥ 0.80（合并口径会稀释单组件失效）⇒ 必须靠组件级底线拦下。
        这条测试正是守住「双闸」设计的护栏。
        """
        mod = pe.load_component('e3_window')
        original = mod.E3_THRESHOLD
        try:
            mod.E3_THRESHOLD = 99          # 熔断永不触发
            report = pe.run_cases(pe.builtin_cases())
        finally:
            mod.E3_THRESHOLD = original
        assert report['failed'] > 0, '熔断阈值改坏后评测集仍全绿 ⇒ 用例自证'
        assert 'circuit-breaker' in report['weak_components'], (
            f'熔断组件跌破底线但未被拦下：weak={report["weak_components"]} '
            f'score={report["score"]}')

    def test_pe_11_broken_circuit_window_must_fail(self):
        """T_PE_11: 把滑动窗口从 3 改成 30（窗口永不滑出）⇒ 必须 FAIL。"""
        mod = pe.load_component('e3_window')
        original = mod.WINDOW_SIZE
        try:
            mod.WINDOW_SIZE = 30
            report = pe.run_cases(pe.builtin_cases())
        finally:
            mod.WINDOW_SIZE = original
        assert report['failed'] > 0, '窗口改坏后评测集仍全绿 ⇒ 用例自证'

    def test_pe_12_inverted_budget_priority_must_fail(self):
        """T_PE_12: 把 RETRIEVE 从 P0 降为 P4（允许削减）⇒ 必须 FAIL。

        这验证 budget-priority 的「禁止为保 P1/P3 而削减 P0」红线真被评到。
        """
        mod = pe.load_component('budget_guard')
        original = dict(mod.CUT_PRIORITY)
        try:
            mod.CUT_PRIORITY['RETRIEVE'] = ('P4', '可砍')
            report = pe.run_cases(pe.builtin_cases())
        finally:
            mod.CUT_PRIORITY.clear()
            mod.CUT_PRIORITY.update(original)
        assert report['failed'] > 0, '削减优先级倒置后评测集仍全绿 ⇒ 用例自证'

    def test_pe_13_broken_wave_split_must_fail(self):
        """T_PE_13: 把 section_waves 改成「不检查依赖」⇒ 必须 FAIL。

        这验证节级拓扑用例真在评「strong-dep 必先行」，而非只看波数。
        """
        mod = pe.load_component('scheduler')
        original = mod.section_waves

        def broken(rows):
            # 故意不检查 strong_dep ⇒ 所有节挤进第一波
            return [[r for r in rows]], []

        try:
            mod.section_waves = broken
            report = pe.run_cases(pe.builtin_cases())
        finally:
            mod.section_waves = original
        assert report['failed'] > 0, '拓扑分波改坏后评测集仍全绿 ⇒ 用例自证'

    def test_pe_14_inverted_recovery_class_must_fail(self):
        """T_PE_14: 把 classify_missing 的 RECOVERABLE/NEVER_PRODUCED 对调 ⇒ 必须 FAIL。

        这验证恢复分类用例真在评判据，而非空跑。
        """
        mod = pe.load_component('assemble_sections')
        original = mod.classify_missing

        def broken(missing, baseline, baseline_status, chapter):
            out = original(missing, baseline, baseline_status, chapter)
            for it in out:
                it['classification'] = ('NEVER_PRODUCED'
                                        if it['classification'] == 'RECOVERABLE'
                                        else 'RECOVERABLE')
            return out

        try:
            mod.classify_missing = broken
            report = pe.run_cases(pe.builtin_cases())
        finally:
            mod.classify_missing = original
        assert report['failed'] > 0, '恢复分类倒置后评测集仍全绿 ⇒ 用例自证'

    def test_pe_15_raised_router_threshold_must_fail(self):
        """T_PE_15: 把 router 置信度阈值抬到 100 ⇒ 必须 FAIL。

        这验证 routing-threshold 用例真在评阈值边界。
        """
        router = pe._load_router()
        original = router['threshold']
        try:
            router['threshold'] = 100
            # 重跑路由评测（阈值变更只影响该组件）
            cases = [c for c in pe.builtin_cases()
                     if c['component'] == 'routing-threshold']
            report = pe.run_cases(cases)
        finally:
            router['threshold'] = original
        assert report['failed'] > 0, '路由阈值改坏后评测集仍全绿 ⇒ 用例自证'

    def test_pe_16_组件级底线拦下单组件失效(self):
        """T_PE_16: 单组件严重失效 ⇒ 总分可能仍达标，但**组件级底线必须拦下**。

        这是 R1 实测暴露的设计缺陷护栏：合并总分会把单组件失效稀释
        （熔断改坏后总分 0.882 ≥ 0.80）⇒ 只看总分会放行一个已坏的协议。
        """
        mod = pe.load_component('e3_window')
        original = mod.E3_THRESHOLD
        try:
            mod.E3_THRESHOLD = 99
            report = pe.run_cases(pe.builtin_cases())
        finally:
            mod.E3_THRESHOLD = original
        # 总分可能仍 ≥0.80（这正是问题所在）
        # 但弱组件必须被点名，且整体门禁必须不通过
        assert report['weak_components'], '未点名弱组件 ⇒ 双闸失效'
        weak = [pc for pc in report['per_component']
                if pc['component'] in report['weak_components']]
        assert all(pc['below_component_threshold'] for pc in weak)
        assert all(pc['score'] < pe.DEFAULT_COMPONENT_THRESHOLD for pc in weak)

    def test_pe_17_全部组件达标时双闸通过(self):
        """T_PE_17: 无注入时，弱组件清单必须为空（双闸不误伤）。"""
        report = pe.run_cases(pe.builtin_cases())
        assert report['weak_components'] == [], (
            f'无注入却出现弱组件: {report["weak_components"]}')
        for pc in report['per_component']:
            assert not pc['below_component_threshold']


# ═══════════════════════════════════════════════════════════════════════
# C 组：组件行为契约（真实实现的直接断言）
# ═══════════════════════════════════════════════════════════════════════
class TestComponentContract:
    """直接断言真实组件行为（不经过评测集，避免「用评测集证评测集」）。"""

    def test_pe_20_circuit_three_state_transitions(self):
        """T_PE_20: CLOSED → OPEN → HALF_OPEN → CLOSED / OPEN 三态闭环。

        这条同时守住 R1 修复的实现缺口：HALF_OPEN 与 exit 2 此前只写在
        docstring 里、从未实现（协议声明三态、执行体只有两态）。
        """
        mod = pe.load_component('e3_window')
        tmp = _tmpdir('stt-pe-cb-')
        try:
            mod.record(tmp, 'ch01', 'ERROR')
            mod.record(tmp, 'ch01', 'ERROR')
            st = mod._load_state(tmp)['ch01']
            assert st['state'] == 'OPEN', st

            rc = mod.probe(tmp, 'ch01')
            assert rc == 2, f'probe 应返回 exit 2，实为 {rc}'
            assert mod._load_state(tmp)['ch01']['state'] == 'HALF_OPEN'

            mod.record(tmp, 'ch01', 'OK')
            assert mod._load_state(tmp)['ch01']['state'] == 'CLOSED'

            # 探测失败 ⇒ 回 OPEN
            mod.record(tmp, 'ch01', 'ERROR')
            mod.record(tmp, 'ch01', 'ERROR')
            mod.probe(tmp, 'ch01')
            mod.record(tmp, 'ch01', 'ERROR')
            assert mod._load_state(tmp)['ch01']['state'] == 'OPEN'
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pe_21_probe_rejected_when_not_open(self):
        """T_PE_21: CLOSED 态不得进入 HALF_OPEN（防熔断被随意绕过）。"""
        mod = pe.load_component('e3_window')
        tmp = _tmpdir('stt-pe-cb2-')
        try:
            rc = mod.probe(tmp, 'ch01')
            assert rc == 3, f'非 OPEN 态 probe 应 exit 3，实为 {rc}'
            assert mod._load_state(tmp).get('ch01') is None
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pe_22_corrupt_baseline_not_bare_never_produced(self):
        """T_PE_22: 清单损坏 ⇒ 证据须含「无法证明」，不得裸判 NEVER_PRODUCED。"""
        mod = pe.load_component('assemble_sections')
        out = mod.classify_missing(['1.1'], {}, 'corrupt', 'ch01')
        assert out, '应有分类结果'
        assert '无法证明' in out[0]['evidence'], out[0]['evidence']

    def test_pe_23_no_strong_dep_within_wave(self):
        """T_PE_23: 直接断言分波结果里同波无 strong-dep 关系。"""
        mod = pe.load_component('scheduler')
        rows = [
            {'节号': '1.1', 'strong_dep': [], 'no_dep': [], 'terms': [],
             'word_budget': 0, 'estimated_tokens': 0},
            {'节号': '1.2', 'strong_dep': ['1.1'], 'no_dep': [], 'terms': [],
             'word_budget': 0, 'estimated_tokens': 0},
        ]
        waves, cycle = mod.section_waves(rows)
        assert not cycle
        for w in waves:
            ids = {r['节号'] for r in w}
            for r in w:
                assert not [d for d in r['strong_dep'] if d in ids], '同波出现强依赖'


# ═══════════════════════════════════════════════════════════════════════
# D 组：门禁接入（learn-protocol 协议一致性）
# ═══════════════════════════════════════════════════════════════════════
class TestGateWiring:
    """protocol-eval 必须真正接进 learn-protocol 流程（否则闭环仍缺末环）。"""

    def test_pe_30_learn_protocol_references_script(self):
        """T_PE_30: learn-protocol 必须指向 scripts/protocol_eval.py。"""
        skill = PKG_ROOT / 'skills' / 'learn-protocol' / 'SKILL.md'
        assert skill.is_file(), 'learn-protocol skill 不存在'
        text = skill.read_text(encoding='utf-8')
        assert 'protocol_eval.py' in text, (
            'learn-protocol 未引用 protocol_eval.py —— 评测闸门未真正接入')

    def test_pe_31_learn_protocol_declares_threshold(self):
        """T_PE_31: learn-protocol 必须声明 0.80 门槛。"""
        text = (PKG_ROOT / 'skills' / 'learn-protocol' / 'SKILL.md').read_text(
            encoding='utf-8')
        assert '0.80' in text or '0.8' in text, 'learn-protocol 未声明门槛'

    def test_pe_32_eval_script_exit_semantics(self):
        """T_PE_32: 达标 exit 0 / 未达标 exit 1（门禁可接入 CI）。"""
        r = subprocess.run([sys.executable, str(EVAL_SCRIPT)],
                           capture_output=True, text=True, timeout=180,
                           cwd=str(PKG_ROOT))
        assert r.returncode == 0, f'内置评测集应达标，实为 {r.returncode}\n{r.stdout[-500:]}'


if __name__ == '__main__':
    sys.exit(pytest_main() if False else 0)


def pytest_main() -> int:
    import pytest
    return pytest.main([__file__, '-v'])
