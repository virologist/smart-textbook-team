#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_compute_metrics_label.py — C9 标签完整率口径修正回归（R3 真实跑批，2026-11-05）

缺陷：`compute_metrics._product_quality` 的数据标签完整率用**句级**匹配，
但标签在教材通用写法里写在**句末标点之后**（「……产蛋率93%。[实](PMID: …）」）
⇒ 句级正则只截到句号，标签落在匹配范围外 ⇒ 误判「未标注」。

实测（同一份真实稿 ch01，33129 汉字）：
  · 旧口径：句级 20/105 = 19%   ← 误报 FAIL
  · 修后：  句级 186/188 = 98.9% ← PASS

验收重点：
  ① 句尾标点之后的标签必须计入
  ② 行内标签（句中）仍计入（不得回退）
  ③ 真·未标注仍判未标注（不得因放宽而漏检）
  ④ 反向例：删掉标签 ⇒ 必须翻红

运行：python3 -m pytest tests/test_compute_metrics_label.py -q
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import compute_metrics as cm  # noqa: E402


@pytest.fixture()
def work_root():
    d = tempfile.mkdtemp(prefix='stt_c9label_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def write_draft(root: Path, body: str) -> Path:
    ch = root / '章节' / 'ch01'
    ch.mkdir(parents=True, exist_ok=True)
    p = ch / 'draft.md'
    p.write_text(body, encoding='utf-8')
    return p


def label_rate(root: Path) -> float | None:
    q = cm._product_quality(root)
    assert q is not None, '章节存在但 _product_quality 返回 None'
    return q['label_rate']


class TestLabelAttribution:
    def test_T_R3_10_tag_after_sentence_punct_counts(self, work_root):
        """句尾标点之后的标签必须计入（本次修复的主场景）。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n')
        assert label_rate(work_root) == 1.0

    def test_T_R3_11_tag_inside_sentence_counts(self, work_root):
        """句中标签仍计入（不得回退旧行为）。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率[实](PMID: 12345678)93%。\n')
        assert label_rate(work_root) == 1.0

    def test_T_R3_12_untagged_sentence_still_fails(self, work_root):
        """反向例：真·未标注仍判未标注（不得因放宽口径而漏检）。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。\n')
        assert label_rate(work_root) == 0.0

    def test_T_R3_13_reverse_remove_tag_turns_red(self, work_root):
        """反向例：删掉标签 ⇒ 必须翻红。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n')
        assert label_rate(work_root) == 1.0
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。\n')
        assert label_rate(work_root) == 0.0

    def test_T_R3_14_mixed_tagged_and_untagged(self, work_root):
        """混合场景：1 条带标签 + 1 条不带 ⇒ 50%。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n\n'
                    '次日死亡率15%。\n')
        assert label_rate(work_root) == 0.5

    def test_T_R3_15_no_numeric_sentence_is_na(self, work_root):
        """无数值陈述 ⇒ N/A（不静默当 0）。"""
        write_draft(work_root, '# 第一章\n\n本章介绍禽病诊断框架。\n')
        q = cm._product_quality(work_root)
        assert q['label_rate'] is None or q['chapters'][0]['labels'].startswith('N/A')


# ══════════════════════════════════════════════════════════════════════
# R3-遗留 L2：分母口径必须是「带具体数值的陈述句」（2026-11-05）
# ══════════════════════════════════════════════════════════════════════
#
# 病灶（真实章 ch_01 实测，33129 汉字）：
#   触发词命中 188 句，其中 **55 句只有触发词而无数值**
#   （如「本病多见于日龄较大鸡群」「免疫程序规范与否影响保护率」）
#   ⇒ 原口径把这类**无数值定性描述**计入分母 ⇒ 覆盖率被系统性稀释。
#   实测：旧口径 32/188 = 0.172；修正后 27/133 = 0.203。
#
# 协议依据：subject-writer §2「每条**学科数据**必须带标签」
#   ⇒ 分母只该算「数据句」，不该算无数值定性句。
#
# ⚠ 反向纪律：分母收窄**不得**掩盖真缺陷
#   ⇒ 用例同时锁住「无数值句不计入」与「有数值但无标签仍判未标注」。

class TestLabelDenominator:
    """分母口径：只算「带具体数值」的陈述句"""

    def test_T_L2_01_no_value_sentence_not_in_denominator(self, work_root):
        """无数值定性句（只含触发词）⇒ 不计入分母。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本病多见于日龄较大鸡群，免疫程序规范与否影响保护率。\n')
        q = cm._product_quality(work_root)
        ch = q['chapters'][0]
        assert ch['labels'].startswith('N/A'), ch['labels']
        assert '触发词命中但无数值' in ch.get('labels_no_value', ''), ch

    def test_T_L2_02_no_value_sentence_does_not_lower_rate(self, work_root):
        """反向：加了无数值句，覆盖率**不得**下降。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n')
        r1 = label_rate(work_root)
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n\n'
                    '本病多见于日龄较大鸡群，免疫程序规范与否影响保护率。\n')
        r2 = label_rate(work_root)
        assert r1 == 1.0
        assert r2 == 1.0, f'无数值句污染了分母：{r1} → {r2}'

    def test_T_L2_03_valued_sentence_without_tag_still_fails(self, work_root):
        """反向：无数值口径收窄后，真·有数值无标签**仍判未标注**。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本场产蛋率93%。\n')
        assert label_rate(work_root) == 0.0

    def test_T_L2_04_mixed_no_value_and_value(self, work_root):
        """混合：无数值句不计入，有数值句计入分母。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本病多见于日龄较大鸡群。\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n')
        q = cm._product_quality(work_root)
        assert q['chapters'][0]['labels'] == '1/1', q['chapters'][0]['labels']
        assert label_rate(work_root) == 1.0

    def test_T_L2_05_ordinal_number_is_not_a_value(self, work_root):
        """「3号舍」「12 000羽存栏」等**计数**是否算数据？—— 计数是数据。

        本用例只锁住「纯序号不算」：'3号舍' 里的 3 后接「号」，
        不在数值单位表内 ⇒ 该句无数值 ⇒ 不计入分母。
        """
        write_draft(work_root,
                    '# 第一章\n\n'
                    '3号舍存栏12000羽，产蛋率93%。[实](PMID: 12345678)\n')
        q = cm._product_quality(work_root)
        assert q['chapters'][0]['labels'] == '1/1', q['chapters'][0]['labels']

    def test_T_L2_06_real_chapter_denominator_shape(self, work_root):
        """形态回归：分母明细须同时给出「被剔除的无数值句数」，可审计。"""
        write_draft(work_root,
                    '# 第一章\n\n'
                    '本病多见于日龄较大鸡群。\n\n'
                    '本场产蛋率93%。[实](PMID: 12345678)\n\n'
                    '次日死亡率15%。\n')
        q = cm._product_quality(work_root)
        ch = q['chapters'][0]
        assert ch['labels'] == '1/2', ch['labels']
        assert '触发词命中但无数值' in ch.get('labels_no_value', ''), ch
