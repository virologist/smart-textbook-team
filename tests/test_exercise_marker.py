#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_exercise_marker.py — 习题位标记口径统一回归（R3-遗留 L1a，2026-11-05）

==============================================================================
病灶（真实跑批暴露，stt-diag-20261101/B/findings-B.md:202）
------------------------------------------------------------------------------
习题位标记存在**两套互不兼容的形式**，且分属不同层：

  · 设计层（chapter_design §C）：`[习题位 {节号}：{Bloom 层级}×{题数}]`
    —— 只在 `agents/subject-writer.md` 一处声明；
  · 书稿层（draft / 交付）：`[习题 {章}-{序}]`
    —— 在 `references/chapter-structure.md` / `references/profiles/veterinary.md` /
       `skills/manuscript-delivery/SKILL.md` §1.3 / `scripts/check_manuscript.py`
       的 `RE_EXERCISE` / `scripts/compute_metrics.py` C9 **五处**声明。

⇒ writer 按自己规范（唯一那份声明）写的习题位，`RE_EXERCISE` **永远匹配不到**
   ⇒ 判据 4.8 恒走「本章无 [习题 X-Y] 标记」WARN 分支
   ⇒ **习题位缺失 / 断号永不被拦**（4.8 形同虚设）。

⇒ 修复不止是「改一份文档」：真实历史产物里已存在的 legacy 习题位
   （e2e_ch06 5 处 / ch08 e2e 5 处 / fixtures ch03 1 处）在旧口径下是
   **静默隐身**的——章节「看起来有习题」，但 4.8 与 C9 都当它不存在。
   ⇒ 必须给 legacy 一条**显式判 FAIL**的判据（4.8b）：错误要报错，不能退化成「缺」。

验收重点（正反双向）
------------------------------------------------------------------------------
  ① canonical `[习题 1-1]` 被 4.8 识别、编号连续时判 PASS
  ② legacy `[习题位 6.1：记忆×2]` 被 4.8b 判 **FAIL**（不得静默放过）
  ③ 4.8 与 4.8b 互不遮蔽：只有 legacy 时，4.8 走 WARN、4.8b 走 FAIL
  ④ 规范层：四份 SSOT + writer 声明口径一致（不再有两套形式并存）
  ⑤ 净字数口径：`[习题 1-1]` 整行/行内都必须被剔除（否则字数漂移）
  ⑥ C9 结构完整率：canonical 与 legacy **都算「习题位存在」**
     （结构只答「有没有」，格式由 4.8b 单独判，否则同一缺陷被重复计一次）
  ⑦ 反向注入：把 4.8b 关掉 ⇒ 用例必须 FAIL（证明用例不自证）

运行：python3 -m pytest tests/test_exercise_marker.py -q
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'


def _load(name: str):
    """按文件路径加载 scripts/ 下模块（该目录非 package，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    assert spec and spec.loader, f'无法加载 {name}.py'
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load('check_manuscript')
cnw = _load('count_net_words')
cm = _load('compute_metrics')


# ── 夹具 ────────────────────────────────────────────────────────────────


@pytest.fixture()
def work_root():
    """临时工作区（不用 pytest tmp_path：OneDrive 沙箱下 basetemp 创建会被拦截）。"""
    d = tempfile.mkdtemp(prefix='stt_exmark_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _judge(text: str) -> dict[str, dict]:
    """跑 4.8/4.8b/4.9 三个判据，返回 {判据ID: 条目}。"""
    r = ck.Result()
    ck.check_exercise_ideology(text, r)
    return {i['id']: i for i in r.items}


# ── ① canonical 形式 ───────────────────────────────────────────────────


class TestCanonicalForm:
    def test_T_L1A_01_canonical_is_detected_and_continuous(self):
        """`[习题 1-1]`/`[习题 1-2]` 必须被 4.8 识别且判连续 PASS。"""
        got = _judge('[习题 1-1]\n\n[习题 1-2]\n')
        assert '4.8' in got, '4.8 判据缺失'
        assert got['4.8']['ok'], f"canonical 连续编号却判未通过: {got['4.8']}"
        assert '2 个' in got['4.8']['desc'], got['4.8']['desc']

    def test_T_L1A_02_canonical_discontinuity_fails(self):
        """`[习题 1-1]` 后直接 `[习题 1-3]` ⇒ 断号 ⇒ 4.8 FAIL。"""
        got = _judge('[习题 1-1]\n\n[习题 1-3]\n')
        assert not got['4.8']['ok'], '断号未被拦下'

    def test_T_L1A_03_canonical_does_not_trigger_4_8b(self):
        """canonical 形式不得触发 4.8b（格式合规）。"""
        got = _judge('[习题 1-1]\n')
        assert '4.8b' not in got, f'canonical 误触发 4.8b: {got.get("4.8b")}'


# ── ② legacy 形式必须显式 FAIL ─────────────────────────────────────────


class TestLegacyFormRejected:
    def test_T_L1A_04_legacy_is_explicitly_failed(self):
        """legacy `[习题位 6.1：记忆×2]` ⇒ 4.8b FAIL，且 detail 给出迁移指引。"""
        got = _judge('[习题位 6.1：记忆×2]\n')
        assert '4.8b' in got, 'legacy 形式未被任何判据捕获（静默放行）'
        assert not got['4.8b']['ok'], 'legacy 形式未判 FAIL'
        assert got['4.8b']['level'] == 'FAIL', got['4.8b']
        detail = got['4.8b']['detail']
        assert '6.1' in detail, f'detail 未指出具体节号: {detail}'
        assert '[习题 {章}-{序}]' in detail, f'detail 未给迁移指引: {detail}'

    def test_T_L1A_05_legacy_and_4_8_do_not_shadow_each_other(self):
        """只有 legacy 时：4.8 走 WARN（无 canonical）、4.8b 走 FAIL（格式错）。"""
        got = _judge('[习题位 6.1：记忆×2]\n')
        assert got['4.8']['level'] == 'WARN', f"4.8 应为 WARN: {got['4.8']}"
        assert not got['4.8']['ok'], '4.8 不应判通过'
        assert got['4.8b']['level'] == 'FAIL', f"4.8b 应为 FAIL: {got['4.8b']}"

    def test_T_L1A_06_legacy_multiple_all_reported(self):
        """多个 legacy 必须全部报出（不得只报第一个）。"""
        got = _judge('[习题位 6.1：记忆×2]\n[习题位 6.2：理解×2]\n[习题位 6.3：应用×3]\n')
        assert got['4.8b']['level'] == 'FAIL'
        assert '3 处' in got['4.8b']['detail'], got['4.8b']['detail']

    def test_T_L1A_07_legacy_in_manuscript_is_not_silently_ignored(self):
        """真实历史形态（e2e_ch06 原文）必须被抓出——不得因「看起来像习题」而放过。"""
        got = _judge('[习题位 6.1：记忆×2]\n[习题位 6.2：理解×2]\n')
        assert not got['4.8b']['ok'], '真实历史形态未被拦下'


# ── ④ 规范层口径一致 ───────────────────────────────────────────────────


class TestSpecConsistency:
    """四份 SSOT + writer 声明必须口径一致（不再两套形式并存）。"""

    SSOT_FILES = [
        'references/chapter-structure.md',
        'references/profiles/veterinary.md',
        'skills/manuscript-delivery/SKILL.md',
    ]

    def test_T_L1A_08_ssot_files_declare_canonical_form(self):
        for rel in self.SSOT_FILES:
            t = (PKG_ROOT / rel).read_text(encoding='utf-8')
            assert '[习题 {章}-{序}]' in t, f'{rel} 缺 canonical 形式声明'

    def test_T_L1A_09_writer_declares_canonical_form(self):
        """writer（唯一偏离源头）必须声明 canonical 形式。"""
        t = (PKG_ROOT / 'agents/subject-writer.md').read_text(encoding='utf-8')
        assert '[习题 {章}-{序}]' in t, 'writer 未声明 canonical 形式'
        assert '全章习题流水号' in t, 'writer 未说明编号依据是全章流水号'

    def test_T_L1A_10_writer_explicitly_forbids_legacy(self):
        """writer 必须**显式禁止** legacy 形式（否则新成员会继续踩同一个坑）。"""
        t = (PKG_ROOT / 'agents/subject-writer.md').read_text(encoding='utf-8')
        assert '不要写' in t or '不得' in t, 'writer 未显式禁止 legacy 形式'
        assert '[习题位 {节号}：{Bloom 层级}×{题数}]' in t, \
            'writer 未点名被禁的 legacy 形态'

    def test_T_L1A_11_design_layer_keeps_section_semantics(self):
        """设计层（architect）保留按节分配的语义——两层分工不能被抹平。"""
        t = (PKG_ROOT / 'agents/didactic-architect.md').read_text(encoding='utf-8')
        assert '[习题位 {节号}：{Bloom 层级}×{题数}]' in t, \
            '设计层结构化语义丢失（应保留在 chapter_design §C）'
        assert '不得原样落进书稿' in t, '未声明设计层不得落进书稿'

    def test_T_L1A_12_ssot_documents_two_layer_distinction(self):
        """manuscript-delivery §1.3 必须写明设计层/书稿层分工。"""
        t = (PKG_ROOT / 'skills/manuscript-delivery/SKILL.md').read_text(encoding='utf-8')
        assert '设计层' in t and '书稿层' in t, '未写明两层分工'
        assert '4.8b' in t, '未登记 4.8b 判据'


# ── ⑤ 净字数口径 ───────────────────────────────────────────────────────


class TestNetWordsExcludesExerciseMarkers:
    def test_T_L1A_13_canonical_block_line_excluded(self):
        """`[习题 1-1]` 整行必须被剔除（否则净字数漂移）。"""
        t = '## 小结\n\n这是正文内容。\n\n[习题 1-1]\n'
        # 「小结」2 + 「这是正文内容」6 = 8
        assert cnw.count_net_words(t)['net_final'] == 8, \
            cnw.count_net_words(t)['steps']

    def test_T_L1A_14_legacy_block_line_still_excluded(self):
        """legacy 整行也必须剔除（虽判 4.8b FAIL，但仍不该污染字数）。"""
        t = '## 小结\n\n这是正文内容。\n\n[习题位 6.1：记忆×2]\n'
        assert cnw.count_net_words(t)['net_final'] == 8, \
            cnw.count_net_words(t)['steps']

    def test_T_L1A_15_canonical_inline_excluded(self):
        """行内 canonical 标记也必须剔除（「小结」2 + 「正文在这里」5 + 「结束」2 = 9）。"""
        t = '## 小结\n\n正文在这里[习题 1-1]结束。\n'
        assert cnw.count_net_words(t)['net_final'] == 9, \
            cnw.count_net_words(t)['steps']

    def test_T_L1A_16_figure_marker_not_broken(self):
        """回归：图位剔除能力不得被本次改动破坏。"""
        t = '## 小结\n\n正文。[图 1-1：结构示意]\n'
        assert cnw.count_net_words(t)['net_final'] == 4, \
            cnw.count_net_words(t)['steps']


# ── ⑥ C9 结构完整率 ────────────────────────────────────────────────────


class TestC9StructureCounts:
    """C9 结构完整率只答「有没有习题位」，格式由 4.8b 单独判。"""

    def _struct_ok(self, text: str) -> int:
        required = {
            '章标题': re.search(r'^#\s+', text, re.M),
            '节标题': re.search(r'^##\s+', text, re.M),
            '图表': re.search(r'\[图\s*\d+-\d+|^\s*图\s*\d+-\d+', text, re.M),
            '习题位': re.search(r'\[习题\s*\d+-\d+|\[习题位\s*\d', text),
            '参考文献': re.search(r'^##\s*参考文献', text, re.M),
        }
        return sum(1 for v in required.values() if v)

    def test_T_L1A_17_canonical_counts_as_present(self):
        # 5 类必备段：章标题 / 节标题 / 图表 / 习题位 / 参考文献
        assert self._struct_ok(
            '# 标题\n\n## 节\n\n[图 1-1：示意]\n\n[习题 1-1]\n\n## 参考文献\n') == 5

    def test_T_L1A_18_legacy_counts_as_present(self):
        """legacy 也算「存在」——否则同一缺陷被结构扣分 + 格式 FAIL 重复计一次。"""
        assert self._struct_ok(
            '# 标题\n\n## 节\n\n[图 1-1：示意]\n\n[习题位 1.1：记忆×2]\n\n## 参考文献\n') == 5

    def test_T_L1A_19_no_marker_counts_absent(self):
        assert self._struct_ok(
            '# 标题\n\n## 节\n\n[图 1-1：示意]\n\n## 参考文献\n') == 4

    def test_T_L1A_20_compute_metrics_uses_same_rule(self):
        """compute_metrics 源码里的判据必须与本测试一致（防止两处漂移）。"""
        src = (SCRIPTS / 'compute_metrics.py').read_text(encoding='utf-8')
        m = re.search(r"'习题位':\s*re\.search\(([^,]+),", src)
        assert m, '未找到 compute_metrics 的习题位判据'
        pat = m.group(1)
        assert '\\[习题位' in pat, f'compute_metrics 未把 legacy 计入存在: {pat}'
        assert '\\[习题\\s*\\d' in pat, f'compute_metrics 未认 canonical: {pat}'


# ── ⑦ 反向注入：证明用例不自证 ─────────────────────────────────────────


class TestReverseInjection:
    """把真实行为改坏，确认用例 FAIL——全绿本身不能证明有效性。"""

    def test_T_L1A_21_inject_disable_4_8b_makes_test_fail(self):
        """注入①：关掉 legacy 识别 ⇒ 4.8b 用例必须 FAIL。"""
        src = (SCRIPTS / 'check_manuscript.py').read_text(encoding='utf-8')
        broken = src.replace(
            'legacy = RE_EXERCISE_LEGACY.findall(text)',
            'legacy = []  # 注入：故意关掉 legacy 识别')
        assert broken != src, '注入点未命中'
        d = tempfile.mkdtemp(prefix='stt_exmark_inj_')
        try:
            p = Path(d) / 'check_manuscript.py'
            p.write_text(broken, encoding='utf-8')
            spec = importlib.util.spec_from_file_location('ck_inj', p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules['ck_inj'] = mod
            spec.loader.exec_module(mod)
            r = mod.Result()
            mod.check_exercise_ideology('[习题位 6.1：记忆×2]\n', r)
            ids = {i['id'] for i in r.items}
            assert '4.8b' not in ids, '注入后 4.8b 仍在报告（注入无效）'
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_T_L1A_22_inject_widen_legacy_pattern_makes_test_fail(self):
        """注入②：把 legacy 正则放宽到误吞 canonical ⇒ **T_L1A_03 的断言必须失败**。

        做法：注入后**重跑真实断言**（canonical 不得触发 4.8b），
        断言该断言确实失败 —— 这直接证明 T_L1A_03 不是恒真断言。
        """
        src = (SCRIPTS / 'check_manuscript.py').read_text(encoding='utf-8')
        broken = src.replace(
            r'RE_EXERCISE_LEGACY = re.compile(r"\[习题位\s*(\d+(?:\.\d+)*)\s*[：:][^\]]*\]")',
            r'RE_EXERCISE_LEGACY = re.compile(r"\[习题[^\]]*\]")  # 注入：过度匹配')
        assert broken != src, '注入点未命中'
        d = tempfile.mkdtemp(prefix='stt_exmark_inj2_')
        try:
            p = Path(d) / 'check_manuscript.py'
            p.write_text(broken, encoding='utf-8')
            spec = importlib.util.spec_from_file_location('ck_inj2', p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules['ck_inj2'] = mod
            spec.loader.exec_module(mod)
            # 注入后 canonical 会被 legacy 正则误吞 ⇒ 4.8b 误报
            r = mod.Result()
            mod.check_exercise_ideology('[习题 1-1]\n', r)
            ids = {i['id'] for i in r.items}
            assert '4.8b' in ids, \
                '注入后 canonical 未误触发 4.8b（注入未生效）'
            # ⇒ 真实用例 T_L1A_03（canonical 不得触发 4.8b）在注入后必然失败
            with pytest.raises(AssertionError):
                assert '4.8b' not in ids
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_T_L1A_23_inject_revert_net_words_makes_test_fail(self):
        """注入③：把 count_net_words 退回只认 `[习题位]` ⇒ **T_L1A_13 的断言必须失败**。

        ⚠ 必须**同时**回退 `_BLOCK_MARK` 与 `_INLINE_MARK`：
           只退 `_BLOCK_MARK` 时，行内正则仍会剥掉 `[习题 1-1]` 的内容 ⇒
           净字数不变 ⇒ 注入**无效**（假阴性）。两处同退才真正制造偏差。
        """
        src = (SCRIPTS / 'count_net_words.py').read_text(encoding='utf-8')
        old_block = r'_BLOCK_MARK = re.compile(r"^\s*\[(图|表|习题位|习题\b)[^\n]*$", re.M)'
        old_inline = (r'_INLINE_MARK = re.compile(r"\[(图|表|习题位|习题\s*\d+-\d+)[^\]]*\]")'
                      r'   # 行内变体（不独立成行的图表位）')
        broken = src.replace(
            old_block,
            r'_BLOCK_MARK = re.compile(r"^\s*\[(图|表|习题位)\b.*$", re.M)  # 注入：退回旧口径')
        broken = broken.replace(
            old_inline,
            r'_INLINE_MARK = re.compile(r"\[(图|表|习题位)[^\]]*\]")  # 注入：退回旧口径')
        assert broken != src, '注入点未命中'
        assert '习题\\b' not in broken, '注入未生效（_BLOCK_MARK 未退回）'
        d = tempfile.mkdtemp(prefix='stt_exmark_inj3_')
        try:
            p = Path(d) / 'count_net_words.py'
            p.write_text(broken, encoding='utf-8')
            spec = importlib.util.spec_from_file_location('cnw_inj', p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules['cnw_inj'] = mod
            spec.loader.exec_module(mod)
            net = mod.count_net_words('## 小结\n\n这是正文内容。\n\n[习题 1-1]\n')['net_final']
            # ⇒ 真实用例 T_L1A_13（净字数 == 8）在注入后必然失败
            with pytest.raises(AssertionError):
                assert net == 8
        finally:
            shutil.rmtree(d, ignore_errors=True)
