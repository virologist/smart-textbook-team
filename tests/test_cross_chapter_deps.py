#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_cross_chapter_deps.py — Batch 4 升级 F：第 7 项术语依赖图回归

验收重点（诊断 §3.2 升级 F / Q6）：
  ① imports ⊆ 上游 exports（上游删/改术语 ⇒ 下游失配被抓）
  ② `--affected-from` 按静态 imports 反向边做 BFS 闭包，只重跑受影响下游
  ③ 缺 from / 来源章不存在 / frontmatter 损坏 ⇒ FAIL，不静默跳过
  ④ 未声明 exports/imports 的章记 WARN（渐进接入，不阻塞）
  ⑤ 反向例：每个 FAIL 都有「修好后翻绿」对照
  ⑥ 既有 6 项检查仍在（第 7 项是追加，不是替换）

运行：python3 -m pytest tests/test_cross_chapter_deps.py -q
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

import check_cross_chapter as ccc  # noqa: E402


@pytest.fixture()
def work_root():
    d = tempfile.mkdtemp(prefix='stt_xch_dep_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def draft(root: Path, ch: str, *, exports: list[str] | None = None,
          imports: list | None = None, body: str = '本章正文，介绍基本概念与操作。') -> Path:
    lines = ['---', f'章节号: {ch}', '教材名: 测试教材', '字数目标: 500',
             '实际净字数: 500', '版本: v1', '学科profile: veterinary']
    if exports is not None:
        lines.append('exports: [' + ', '.join(exports) + ']')
    if imports is not None:
        lines.append('imports:')
        for it in imports:
            if isinstance(it, dict):
                lines.append(f"  - term: {it.get('term', '')}")
                if it.get('from'):
                    lines.append(f"    from: {it['from']}")
            else:
                lines.append(f'  - {it}')
    lines += ['---', '', body, '']
    p = root / '章节' / ch / 'draft.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join(lines), encoding='utf-8')
    return p


def run_cli(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / 'check_cross_chapter.py'),
         '--work-root', str(root), '--json', *extra],
        capture_output=True, text=True)


def dep_issues(root: Path, *extra: str) -> list[dict]:
    r = run_cli(root, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return [i for i in json.loads(r.stdout)['issues'] if i['type'] == '术语依赖图']


class TestGraph:
    def test_T_B4_27_valid_graph_no_fail(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', exports=['T1', 'T2'])
        draft(work_root, 'ch03', imports=[{'term': 'T1', 'from': 'ch02'}])
        issues = dep_issues(work_root)
        assert not [i for i in issues if i['severity'] == 'FAIL'], issues

    def test_T_B4_28_upstream_removed_term_fail_with_reverse(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', exports=['T2'])   # T1 被上游删了
        draft(work_root, 'ch03', imports=[{'term': 'T1', 'from': 'ch02'}])
        fails = [i for i in dep_issues(work_root) if i['severity'] == 'FAIL']
        assert len(fails) == 1 and '已不在' in fails[0]['detail'], fails
        # 反向例：上游补回 T1 ⇒ 必须翻绿
        draft(work_root, 'ch02', exports=['T1', 'T2'])
        assert not [i for i in dep_issues(work_root) if i['severity'] == 'FAIL']

    def test_T_B4_29_unknown_source_fail_with_reverse(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', imports=[{'term': 'T9', 'from': 'ch99'}])
        assert any('无 draft.md' in i['detail'] for i in dep_issues(work_root))
        # 反向例：把来源改成现存章并让它 exports 该术语 ⇒ 翻绿
        draft(work_root, 'ch01', exports=['T0', 'T9'])
        draft(work_root, 'ch02', imports=[{'term': 'T9', 'from': 'ch01'}])
        assert not [i for i in dep_issues(work_root) if i['severity'] == 'FAIL']

    def test_T_B4_30_missing_from_fail_with_reverse(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', imports=['T0'])   # 简写，无来源章号
        assert any('缺 term/from' in i['detail'] for i in dep_issues(work_root))
        # 反向例：补 from ⇒ 翻绿
        draft(work_root, 'ch02', imports=[{'term': 'T0', 'from': 'ch01'}])
        assert not [i for i in dep_issues(work_root) if i['severity'] == 'FAIL']

    def test_T_B4_31_undeclared_is_warn_only(self, work_root):
        draft(work_root, 'ch01')   # 无 exports/imports
        draft(work_root, 'ch02')
        r = run_cli(work_root, '--strict')
        assert r.returncode == 0, r.stdout + r.stderr
        issues = [i for i in json.loads(r.stdout)['issues'] if i['type'] == '术语依赖图']
        assert len(issues) == 2 and all(i['severity'] == 'WARN' for i in issues)

    def test_T_B4_32_affected_from_closure(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', exports=['T1'], imports=[{'term': 'T0', 'from': 'ch01'}])
        draft(work_root, 'ch03', exports=['T2'], imports=[{'term': 'T1', 'from': 'ch02'}])
        draft(work_root, 'ch04', exports=['T3'], imports=[{'term': 'T2', 'from': 'ch03'}])
        r = run_cli(work_root, '--affected-from', 'ch02')
        assert r.returncode == 0, r.stdout + r.stderr
        meta = json.loads(r.stdout)['term_dependency']
        assert meta['affected_chapters'] == ['ch03', 'ch04']   # BFS 间接下游

    def test_T_B4_33_affected_from_scopes_out_unrelated_fail(self, work_root):
        """反向例：无关章的失配在 --affected-from 下不应触发 FAIL。"""
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', exports=['T1'])
        draft(work_root, 'ch03', imports=[{'term': 'MISSING', 'from': 'ch01'}])  # 与 ch02 无关
        assert any(i['severity'] == 'FAIL' for i in dep_issues(work_root))
        scoped = dep_issues(work_root, '--affected-from', 'ch02')
        assert not [i for i in scoped if i['severity'] == 'FAIL'], scoped

    def test_T_B4_34_unknown_affected_from_not_silent_pass(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', exports=['T1'])
        issues = dep_issues(work_root, '--affected-from', 'ch99')
        assert any('无可校验目标' in i['detail'] for i in issues), issues

    def test_T_B4_35_broken_yaml_is_fail(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        p = work_root / '章节' / 'ch02' / 'draft.md'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\nexports: [unterminated\n---\n\n正文。\n', encoding='utf-8')
        assert any('YAML 非法' in i['detail'] for i in dep_issues(work_root))

    def test_T_B4_36_strict_fail_exits_1_with_reverse(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', imports=[{'term': 'T1', 'from': 'ch01'}])
        r = run_cli(work_root, '--strict')
        assert r.returncode == 1, r.stdout + r.stderr
        # 反向例：上游补 T1 ⇒ --strict 翻绿
        draft(work_root, 'ch01', exports=['T0', 'T1'])
        assert run_cli(work_root, '--strict').returncode == 0

    def test_T_B4_37_six_legacy_checks_still_present(self, work_root):
        draft(work_root, 'ch01', exports=['T0'])
        draft(work_root, 'ch02', exports=['T1'])
        out = json.loads(run_cli(work_root).stdout)
        assert 'term_dependency' in out and out['term_dependency']['check'] == 7
        # 既有六项函数仍可独立调用（不是被第 7 项替换掉）
        chapters = ccc.load_chapters(work_root)
        assert set(chapters) == {'ch01', 'ch02'}
        assert isinstance(ccc.check_figure_continuity(chapters), list)
        assert isinstance(ccc.check_duplication(chapters), list)

    def test_T_B4_38_closure_pure_function(self):
        deps = {
            'ch01': {'imports': []},
            'ch02': {'imports': [{'term': 'T0', 'from': 'ch01'}]},
            'ch03': {'imports': [{'term': 'T1', 'from': 'ch02'}]},
            'ch04': {'imports': []},
        }
        assert ccc.dependency_closure(deps, 'ch01') == ['ch02', 'ch03']
        assert ccc.dependency_closure(deps, 'ch03') == []
        assert ccc.dependency_closure(deps, 'ch04') == []
