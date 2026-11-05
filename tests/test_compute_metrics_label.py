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
