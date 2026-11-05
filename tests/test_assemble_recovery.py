#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_assemble_recovery.py — Batch 4 升级 E：缺失节恢复协议回归

验收重点（诊断 §3.2 升级 E / Q5）：
  ① RECOVERABLE vs NEVER_PRODUCED 的判据是「上次成功拼接清单」而非猜
  ② 脚本只报不 spawn（报告 script_only_reports=true，绝不自行重派）
  ③ 两种分类都写合规 BLOCK trace（type=BLOCK ⇒ 纳入 compute_metrics.retry_rate）
  ④ 退出码 0/1/2/3 分层；清单损坏不得静默当「从未产出」
  ⑤ 反向例：补齐缺节 ⇒ 翻绿；修好标签 ⇒ 翻绿；--no-trace ⇒ 不写

运行：python3 -m pytest tests/test_assemble_recovery.py -q
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


@pytest.fixture()
def work_root():
    d = tempfile.mkdtemp(prefix='stt_asmb_rec_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


def setup(root: Path, sections: list[str] | None = None,
          manifest_sections: list[str] | None = None,
          *, manifest_corrupt: bool = False) -> Path:
    """建工作区：设计节序固定 1.1/1.2/1.3。"""
    ch = root / '章节' / 'ch01'
    _write(ch / 'chapter_design.md',
           '# chapter_design\n\n## C. 分节写作计划\n\n'
           '| 节号 | 节标题 | 字数目标 |\n| --- | --- | --- |\n'
           '| 1.1 | 概述 | 800 |\n| 1.2 | 病原 | 1200 |\n'
           '| 1.3 | 防控 | 900 |\n')
    (ch / 'sections').mkdir(parents=True, exist_ok=True)  # 空目录也要建：区分 exit 0 与 exit 2
    for s in (sections if sections is not None else ['1.1', '1.2', '1.3']):
        _write(ch / 'sections' / f'{s}.md', f'# {s} 标题\n\n本节正文内容。\n')
    if manifest_corrupt:
        _write(ch / '拼接清单.json', '{ 这不是合法 JSON')
    elif manifest_sections is not None:
        _write(ch / '拼接清单.json', json.dumps({
            'chapter': 'ch01', 'order': manifest_sections,
            'sections': [{'节号': s, '文件': f'sections/{s}.md'}
                         for s in manifest_sections],
        }, ensure_ascii=False))
    return ch


def run_assemble(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / 'assemble_sections.py'),
         '--work-root', str(root), '--chapter', 'ch01', *extra],
        capture_output=True, text=True)


def report_of(root: Path) -> dict:
    p = root / '运行态' / 'section_recovery_ch01.json'
    assert p.is_file(), f'恢复报告未落盘: {p}'
    return json.loads(p.read_text(encoding='utf-8'))


def trace_of(root: Path) -> list[dict]:
    p = root / '运行态' / 'trace.jsonl'
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]


class TestRecovery:
    def test_T_B4_16_recoverable_when_in_previous_manifest(self, work_root):
        setup(work_root, sections=['1.1', '1.3'],
              manifest_sections=['1.1', '1.2', '1.3'])
        r = run_assemble(work_root, '--skip-check')
        assert r.returncode == 3, r.stdout + r.stderr
        rep = report_of(work_root)
        assert rep['status'] == 'RECOVERY_REQUIRED'
        assert rep['baseline_status'] == 'ok'
        assert rep['missing'][0]['节号'] == '1.2'
        assert rep['missing'][0]['classification'] == 'RECOVERABLE'
        assert '曾成功落盘' in rep['missing'][0]['evidence']
        assert rep['missing'][0]['spawn_hint']['must_produce'] == \
            '章节/ch01/sections/1.2.md'

    def test_T_B4_17_never_produced_without_manifest(self, work_root):
        setup(work_root, sections=['1.1', '1.3'])
        r = run_assemble(work_root, '--skip-check')
        assert r.returncode == 3, r.stdout + r.stderr
        rep = report_of(work_root)
        assert rep['baseline_status'] == 'missing'
        assert rep['missing'][0]['classification'] == 'NEVER_PRODUCED'
        assert 'on_partial=BLOCK' in rep['missing'][0]['suggested_action']

    def test_T_B4_18_reverse_fill_section_makes_it_green(self, work_root):
        """反向例：补回缺节文件 ⇒ exit 0 且不再出恢复报告。"""
        ch = setup(work_root, sections=['1.1', '1.3'])
        assert run_assemble(work_root, '--skip-check').returncode == 3
        _write(ch / 'sections' / '1.2.md', '# 1.2 病原\n\n补齐的正文。\n')
        r = run_assemble(work_root, '--skip-check')
        assert r.returncode == 0, r.stdout + r.stderr
        assert (ch / 'draft.md').is_file()
        assert (ch / '拼接清单.json').is_file()

    def test_T_B4_19_mixed_classification(self, work_root):
        setup(work_root, sections=['1.2'],
              manifest_sections=['1.1', '1.2'])
        assert run_assemble(work_root, '--skip-check').returncode == 3
        rep = report_of(work_root)
        kinds = {it['节号']: it['classification'] for it in rep['missing']}
        assert kinds == {'1.1': 'RECOVERABLE', '1.3': 'NEVER_PRODUCED'}

    def test_T_B4_20_block_trace_is_compliant(self, work_root):
        setup(work_root, sections=['1.1'])
        assert run_assemble(work_root, '--skip-check').returncode == 3
        rows = trace_of(work_root)
        assert len(rows) == 1, rows
        rec = rows[0]
        assert rec['type'] == 'BLOCK'          # compute_metrics.retry_rate 认这个
        assert rec['phase'] == 'PRODUCE-R1'
        assert rec['start'] and not rec.get('timing_degraded')
        assert 'SECTION_RECOVERY' in rec['notes']
        assert report_of(work_root)['trace_written'] is True

    def test_T_B4_21_no_trace_switch_with_reverse(self, work_root):
        setup(work_root, sections=['1.1'])
        r = run_assemble(work_root, '--skip-check', '--no-trace')
        assert r.returncode == 3, r.stdout + r.stderr
        assert trace_of(work_root) == []
        assert report_of(work_root)['trace_written'] is False
        # 反向例：默认（不加开关）必须写
        assert run_assemble(work_root, '--skip-check').returncode == 3
        assert len(trace_of(work_root)) == 1

    def test_T_B4_22_corrupt_manifest_not_silent(self, work_root):
        setup(work_root, sections=['1.1'], manifest_corrupt=True)
        r = run_assemble(work_root, '--skip-check')
        assert r.returncode == 3, r.stdout + r.stderr
        rep = report_of(work_root)
        assert rep['baseline_status'] == 'corrupt'
        assert '基线状态' in r.stderr
        assert all(it['classification'] == 'NEVER_PRODUCED' for it in rep['missing'])
        assert '保守按从未产出' in rep['missing'][0]['evidence']

    def test_T_B4_23_script_only_reports_never_spawns(self, work_root):
        setup(work_root, sections=['1.1'])
        run_assemble(work_root, '--skip-check')
        rep = report_of(work_root)
        assert rep['script_only_reports'] is True
        assert all('spawn_hint' in it and 'must_produce' in it['spawn_hint']
                   for it in rep['missing'])
        # 只报不 spawn：不得擅自创建缺失的节文件
        assert not (work_root / '章节' / 'ch01' / 'sections' / '1.2.md').exists()


class TestExistingBehaviorUnchanged:
    def test_T_B4_24_self_check_failure_still_exit_1(self, work_root):
        ch = setup(work_root)
        _write(ch / 'sections' / '1.2.md', '发病率 12.5% 明显上升。\n')  # 缺数据标签
        r = run_assemble(work_root)
        assert r.returncode == 1, r.stdout + r.stderr
        # 反向例：补标签 ⇒ 翻绿
        _write(ch / 'sections' / '1.2.md', '发病率 12.5% [实] 明显上升。\n')
        assert run_assemble(work_root).returncode == 0

    def test_T_B4_25_empty_sections_is_exit_2(self, work_root):
        setup(work_root, sections=[])
        r = run_assemble(work_root, '--skip-check')
        assert r.returncode == 2, r.stdout + r.stderr

    def test_T_B4_26_no_sections_dir_is_whole_chapter_mode(self, work_root):
        setup(work_root)
        # 不用 shutil.rmtree：宿主 sitecustomize 的 _safe_shutil_rmtree 包装
        # 在本沙箱下会抛 FileNotFoundError（实测），逐文件 unlink + rmdir 规避。
        sec_dir = work_root / '章节' / 'ch01' / 'sections'
        for f in sec_dir.iterdir():
            f.unlink()
        sec_dir.rmdir()
        r = run_assemble(work_root, '--skip-check')
        assert r.returncode == 0, r.stdout + r.stderr


class TestSelfCheckScopeR3Fix:
    """R3 真实跑批暴露的门禁口径缺陷（2026-11-05）回归。

    缺陷：`self_check_section` 逐行判定时未剥离 YAML frontmatter、
    也未跳过 Markdown 标题行 ⇒ frontmatter 元数据（如
    `节标题: M2 急性死亡与高死亡率疾病群`）与节标题本身
    被当成「正文陈述」→ 正文标签齐全仍被拦（exit 1）。
    与门禁 3.1 原文「**正文中**凡含数值触发词的陈述」不符，
    也与整章 C9 指标（句级匹配）的口径不同源（C-05 病灶）。
    """

    def test_T_R3_01_frontmatter_trigger_word_not_flagged(self, work_root):
        ch = setup(work_root)
        _write(ch / 'sections' / '1.2.md',
               '---\n'
               '节号: "1.2"\n'
               '节标题: M2 急性死亡与高死亡率疾病群\n'
               'exports: [新城疫]\n'
               '---\n\n'
               '# 第二节 M2 急性死亡与高死亡率疾病群\n\n'
               '本节正文无触发词。\n')
        r = run_assemble(work_root)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_T_R3_02_heading_trigger_word_not_flagged(self, work_root):
        ch = setup(work_root)
        _write(ch / 'sections' / '1.2.md',
               '# 第二节 M2 急性死亡与高死亡率疾病群\n\n'
               '本节正文无触发词。\n')
        r = run_assemble(work_root)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_T_R3_03_body_trigger_word_still_flagged(self, work_root):
        """反向例：正文真缺标签仍必须拦（不得因放宽口径而漏检）。"""
        ch = setup(work_root)
        _write(ch / 'sections' / '1.2.md',
               '---\n节标题: 概述\n---\n\n'
               '## 小节标题\n\n'
               '本群发病率 12.5% 明显上升。\n')
        r = run_assemble(work_root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert '缺 [实]' in r.stderr

    def test_T_R3_04_reverse_add_body_tag_makes_green(self, work_root):
        ch = setup(work_root)
        _write(ch / 'sections' / '1.2.md',
               '---\n节标题: 概述\n---\n\n'
               '## 小节标题\n\n'
               '本群发病率 12.5% 明显上升。\n')
        assert run_assemble(work_root).returncode == 1
        _write(ch / 'sections' / '1.2.md',
               '---\n节标题: 概述\n---\n\n'
               '## 小节标题\n\n'
               '本群发病率 12.5% [实](PMID: 12345678) 明显上升。\n')
        assert run_assemble(work_root).returncode == 0
