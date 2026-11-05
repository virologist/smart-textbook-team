#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_chapter_deps_declaration.py — R4 批次：存量章节 exports/imports 补声明回归

背景（复诊 §3.4 R4）：
  第 7 项「跨章术语依赖图」机制已建好（`check_cross_chapter.py` 第 7 项），
  但**存量章节零声明** ⇒ 依赖图为空 ⇒ 机制「建好但空转」，只产 WARN。
  R4 的动作是：首批 2-3 章补真实声明，让依赖图被真实数据激活。

验收重点：
  ① 存量章节声明后，依赖图 WARN 归零、`declared_chapters` 非空（机制真激活）
  ② imports ⊆ 上游 exports 成立（正向）
  ③ 反向例：删上游 exports ⇒ 下游 FAIL ⇒ 补回 ⇒ 翻绿（成对写）
  ④ `--affected-from` BFS 闭包命中下游
  ⑤ **零污染**（R4 的真实风险点）：
     - 交付稿 frontmatter 不得含 exports/imports
     - 净字数不受 frontmatter 影响（口径同源 `count_net_words.py`）
     - `build_manuscript` 的「draft 无 frontmatter」WARN 不得被部分 frontmatter 静默吞掉
  ⑥ 声明的术语必须**有正文实证**（不是凭空写的标签）

运行：python3 -m pytest tests/test_chapter_deps_declaration.py -q
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PKG_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import build_manuscript  # noqa: E402
import check_cross_chapter as ccc  # noqa: E402
import count_net_words  # noqa: E402

# 真实教材工作区（主仓）。R4 在该工作区补了首批声明；测试直接针对它取真值。
#
# ⚠️ 路径**不得硬编码**（`check_domain_neutral.py` 的「硬编码绝对路径」判据会 FAIL，
#    且它用 `root.rglob('*')` 扫全包、含 tests/）。
# 与包仓是**两个独立 git 仓**（tb-writer / smart-textbook-team），不在同一目录树下
# ⇒ 无法从包仓路径上溯推导 ⇒ 只能用环境变量 `STT_REAL_ROOT` 指定。
def _find_real_root() -> Path | None:
    env = os.environ.get('STT_REAL_ROOT')
    if env:
        p = Path(env).expanduser()
        return p if (p / '章节').is_dir() else None
    return None


REAL_ROOT = _find_real_root()

# 包内自包含 fixture（源自真实教材的 frontmatter 原文 + 术语实证窗口）
FIXTURE_ROOT = PKG_ROOT / 'tests' / 'fixtures' / 'chapter_deps'


def run_cli(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / 'check_cross_chapter.py'),
         '--work-root', str(root), '--json', *extra],
        capture_output=True, text=True)


def dep_meta(root: Path, *extra: str) -> dict:
    r = run_cli(root, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)['term_dependency']


def dep_issues(root: Path, *extra: str) -> list[dict]:
    r = run_cli(root, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return [i for i in json.loads(r.stdout)['issues'] if i['type'] == '术语依赖图']


def draft(root: Path, ch: str, *, exports: list[str] | None = None,
          imports: list | None = None, body: str = '本章正文，介绍基本概念与操作。',
          extra_fm: list[str] | None = None) -> Path:
    """造一个带 frontmatter 的章稿。extra_fm 用于插入额外 YAML 键（如 exports）。"""
    lines = ['---', f'章节号: {ch}', '章节标题: 测试章', '教材名: 测试教材',
             '字数目标: 500', '版本: v1', '学科profile: veterinary']
    if extra_fm:
        lines.extend(extra_fm)
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


@pytest.fixture()
def work_root():
    d = tempfile.mkdtemp(prefix='stt_r4_dep_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def real_copy():
    """**包内自包含 fixture** 的临时副本——默认就能跑，不依赖外部仓。

    fixture 源自真实教材 `tb_禽病学-职业本科版` 的 ch_01 / ch_02：
    frontmatter **逐字保留**（含 R4 补的 exports/imports 声明），
    正文取「声明术语所在行 ± 1 上下文」的窗口（12 KB，非全文），
    以保证「术语必须有正文实证」这条判据可在包内独立验证。
    """
    d = Path(tempfile.mkdtemp(prefix='stt_r4_fix_'))
    try:
        shutil.copytree(FIXTURE_ROOT, d / '章节')
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def live_copy():
    """**真实教材工作区**的临时副本——真值对照（需环境变量）。

    与包仓是**两个独立 git 仓**（tb-writer / smart-textbook-team），
    不在同一目录树下 ⇒ 无法从包仓路径上溯推导 ⇒ 只能用环境变量指定。
    未设置时本组测试 skip（不影响默认回归的完整性）。
    """
    if REAL_ROOT is None:
        pytest.skip('未设置 STT_REAL_ROOT（指向真实教材工作区）——跳过真值对照')
    src = REAL_ROOT / '章节'
    if not src.is_dir():
        pytest.skip(f'真实教材工作区不存在：{src}')
    d = Path(tempfile.mkdtemp(prefix='stt_r4_live_'))
    try:
        shutil.copytree(src, d / '章节')
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── ① 存量章节声明后机制真激活 ─────────────────────────────────────────
class TestActivation:
    def test_T_R4_01_real_chapters_declared(self, real_copy):
        """真实教材两章已声明 ⇒ undeclared_chapters 为空（依赖图非空）。"""
        meta = dep_meta(real_copy)
        assert 'ch_01' in meta['declared_chapters']
        assert 'ch_02' in meta['declared_chapters']
        assert meta['undeclared_chapters'] == [], meta['undeclared_chapters']

    def test_T_R4_02_real_graph_has_no_fail(self, real_copy):
        """真实声明自洽：imports ⊆ 上游 exports ⇒ 第 7 项零 FAIL。"""
        fails = [i for i in dep_issues(real_copy) if i['severity'] == 'FAIL']
        assert not fails, fails

    def test_T_R4_03_no_warn_after_declaration(self, real_copy):
        """声明后第 7 项不再产「未声明」WARN（这是 R4 的直接目标）。"""
        warns = [i for i in dep_issues(real_copy) if i['severity'] == 'WARN']
        assert not warns, warns

    def test_T_R4_04_closure_hits_downstream(self, real_copy):
        """--affected-from ch_01 ⇒ BFS 闭包命中 ch_02。"""
        meta = dep_meta(real_copy, '--affected-from', 'ch_01')
        assert meta['affected_chapters'] == ['ch_02'], meta['affected_chapters']

    def test_T_R4_05_exports_nonempty(self, real_copy):
        """真实声明不是空壳：两章 exports 均有内容。"""
        meta = dep_meta(real_copy)
        assert len(meta['exports']['ch_01']) >= 3
        assert len(meta['exports']['ch_02']) >= 1
        assert len(meta['imports']['ch_02']) >= 1


# ── ②③ 反向例：删上游 exports ⇒ 下游 FAIL ⇒ 补回翻绿 ───────────────────
class TestReverse:
    def test_T_R4_06_upstream_removed_term_fails(self, real_copy):
        """删上游 exports 的「新城疫」⇒ 下游 ch_02 立即 FAIL。"""
        p = real_copy / '章节' / 'ch_01' / 'draft.md'
        t = p.read_text(encoding='utf-8')
        t2 = t.replace('  - 新城疫\n', '', 1)
        assert t2 != t, '未找到待删的上游 exports 项'
        p.write_text(t2, encoding='utf-8')
        fails = [i for i in dep_issues(real_copy) if i['severity'] == 'FAIL']
        assert len(fails) == 1, fails
        assert '已不在' in fails[0]['detail'], fails[0]['detail']

    def test_T_R4_07_reverse_restored_goes_green(self, real_copy):
        """反向对照：上游补回该术语 ⇒ 第 7 项翻绿。"""
        p = real_copy / '章节' / 'ch_01' / 'draft.md'
        t = p.read_text(encoding='utf-8')
        t2 = t.replace('  - 新城疫\n', '', 1)
        assert t2 != t
        p.write_text(t2, encoding='utf-8')
        assert [i for i in dep_issues(real_copy) if i['severity'] == 'FAIL']
        # 补回
        t3 = p.read_text(encoding='utf-8')
        t4 = t3.replace('  - 低致病性禽流感\n', '  - 低致病性禽流感\n  - 新城疫\n', 1)
        assert t4 != t3
        p.write_text(t4, encoding='utf-8')
        assert not [i for i in dep_issues(real_copy) if i['severity'] == 'FAIL']

    def test_T_R4_08_strict_exit_code(self, real_copy):
        """--strict 下上游删术语 ⇒ exit 1（不得静默放行）。"""
        p = real_copy / '章节' / 'ch_01' / 'draft.md'
        t = p.read_text(encoding='utf-8')
        p.write_text(t.replace('  - 新城疫\n', '', 1), encoding='utf-8')
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / 'check_cross_chapter.py'),
             '--work-root', str(real_copy), '--strict'],
            capture_output=True, text=True)
        assert r.returncode == 1, r.stdout + r.stderr

    def test_T_R4_09_downstream_imports_must_match_upstream(self, work_root):
        """正向：下游 imports 全部命中上游 exports ⇒ 零 FAIL。"""
        draft(work_root, 'ch01', exports=['T0', 'T1'])
        draft(work_root, 'ch02', imports=[{'term': 'T0', 'from': 'ch01'},
                                          {'term': 'T1', 'from': 'ch01'}])
        assert not [i for i in dep_issues(work_root) if i['severity'] == 'FAIL']


# ── ⑤ 零污染：交付稿 / 净字数 / WARN 判据 ──────────────────────────────
class TestNoContamination:
    def test_T_R4_10_delivery_has_no_exports(self, work_root):
        """交付稿 frontmatter 不得含 exports/imports（装配器只重建七项）。"""
        draft(work_root, 'ch01', exports=['T0'], body='# 第一章 测试\n\n正文内容。\n')
        out = build_manuscript.assemble_md(work_root, 'ch01', '测试教材')
        text = out.read_text(encoding='utf-8')
        assert not re.search(r'^(exports|imports):', text, re.M), \
            '交付稿被 exports/imports 污染'

    def test_T_R4_11_delivery_frontmatter_has_seven(self, work_root):
        """交付稿 frontmatter 仍是七项（元数据不被依赖声明挤占）。"""
        draft(work_root, 'ch01', exports=['T0'], body='# 第一章 测试\n\n正文内容。\n')
        out = build_manuscript.assemble_md(work_root, 'ch01', '测试教材')
        text = out.read_text(encoding='utf-8')
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        assert m, '交付稿无 frontmatter'
        keys = re.findall(r"^([^\s:#]+)\s*:", m.group(1), re.M)
        assert len(keys) == 7, keys

    def test_T_R4_12_net_words_unaffected(self, work_root):
        """加 frontmatter 声明不改变净字数（口径同源 count_net_words.py）。"""
        p = draft(work_root, 'ch01', body='# 第一章 测试\n\n正文内容。\n')
        before = count_net_words.count_net_words(p.read_text(encoding='utf-8'))['net_final']
        p2 = draft(work_root, 'ch02', exports=['T0'],
                   body='# 第一章 测试\n\n正文内容。\n')
        after = count_net_words.count_net_words(p2.read_text(encoding='utf-8'))['net_final']
        assert before == after, (before, after)

    def test_T_R4_13_partial_frontmatter_still_warns(self, work_root):
        """真实缺陷回归：draft 只有 exports ⇒ 「无 frontmatter」WARN 不得被吞掉。

        原判据 `if not existing:` 只要 draft 带**任何一个**键就整条 WARN 消失，
        而七项其实仍靠推导兜底 ⇒ 静默。R4 补声明正是这类场景，必须显式报缺失。
        """
        p = work_root / '章节' / 'ch01' / 'draft.md'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\nexports: [T1]\n---\n\n# 测试章\n\n正文。\n', encoding='utf-8')
        warns: list[str] = []
        orig_log = build_manuscript.log

        def _cap(msg: str, level: str = 'INFO'):
            if level in ('WARN', 'ERROR'):
                warns.append(f'[{level}] {msg}')
            orig_log(msg, level)

        build_manuscript.log = _cap
        try:
            build_manuscript.assemble_md(work_root, 'ch01', '测试教材')
        finally:
            build_manuscript.log = orig_log
        joined = '\n'.join(warns)
        assert 'frontmatter 缺' in joined, joined
        assert '教材名' in joined, joined

    def test_T_R4_14_no_frontmatter_warns(self, work_root):
        """无 frontmatter ⇒ 仍报「draft 无 frontmatter」。"""
        p = work_root / '章节' / 'ch01' / 'draft.md'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# 测试章\n\n正文。\n', encoding='utf-8')
        warns: list[str] = []
        orig_log = build_manuscript.log

        def _cap(msg: str, level: str = 'INFO'):
            if level in ('WARN', 'ERROR'):
                warns.append(f'[{level}] {msg}')
            orig_log(msg, level)

        build_manuscript.log = _cap
        try:
            build_manuscript.assemble_md(work_root, 'ch01', '测试教材')
        finally:
            build_manuscript.log = orig_log
        assert 'draft 无 frontmatter' in '\n'.join(warns), warns

    def test_T_R4_15_full_frontmatter_no_fm_warn(self, work_root):
        """七项齐全 ⇒ 不报 frontmatter 类 WARN。

        只看 WARN/ERROR 级日志：INFO 级的「装配完成（frontmatter 七项…）」
        是正常回执，不是告警，不能算命中。
        """
        draft(work_root, 'ch01', body='# 第一章 测试\n\n正文内容。\n')
        warns: list[str] = []
        orig_log = build_manuscript.log

        def _cap(msg: str, level: str = 'INFO'):
            if level in ('WARN', 'ERROR'):
                warns.append(f'[{level}] {msg}')
            orig_log(msg, level)

        build_manuscript.log = _cap
        try:
            build_manuscript.assemble_md(work_root, 'ch01', '测试教材')
        finally:
            build_manuscript.log = orig_log
        assert not any('frontmatter' in w for w in warns), warns


# ── ⑥ 声明的术语必须有正文实证（防「凭空造标签」）────────────────────
def _core(token: str, body: str) -> str:
    """取术语的「核心成分」用于正文实证匹配。

    依赖图判据是**符号字面精确匹配**（imports.term 必须逐字等于上游 exports 项），
    但本章正文里的**书写形式**可以不同（例：上游导出「H9N2亚型禽流感」，
    下游正文写「H9N2」）。

    匹配策略：**前缀梯度**——从最长开始逐字符截短，取第一个在正文中出现的
    前缀。取前缀（而非剥离后缀）是因为正文里的简称通常是原术语的**前缀**
    （「H9N2」是「H9N2亚型禽流感」的前缀），后缀剥离得到的是「H9N2禽流感」这种
    中间形态，反而匹配不上。
    """
    if token in body:
        return token
    # 最少保留 2 个字符，避免把「病」这种单字当成实质匹配
    for n in range(len(token) - 1, 1, -1):
        prefix = token[:n]
        if prefix in body:
            return prefix
    return token


class TestEvidence:
    def test_T_R4_16_exports_terms_appear_in_body(self, real_copy):
        """ch_01 的每个 exports 术语在正文中确有出现（不是凭空写的）。"""
        meta = dep_meta(real_copy)
        body = (real_copy / '章节' / 'ch_01' / 'draft.md').read_text(encoding='utf-8')
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", body, flags=re.S)
        for term in meta['exports']['ch_01']:
            assert term in body, f'ch_01 exports 术语「{term}」在正文中无实证'

    def test_T_R4_16b_ch02_exports_terms_appear_in_body(self, real_copy):
        """ch_02 的每个 exports 术语在正文中确有出现。

        这条是**编造标签的护栏**：初版声明里写过「禽流感病毒分类学命名规范」
        与「低致病性禽流感病毒」，二者在正文中 0 命中——纯凭印象写的标签。
        声明只有每个术语在正文出现 ≥1 次才算有据。
        """
        meta = dep_meta(real_copy)
        body = (real_copy / '章节' / 'ch_02' / 'draft.md').read_text(encoding='utf-8')
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", body, flags=re.S)
        for term in meta['exports']['ch_02']:
            assert term in body, f'ch_02 exports 术语「{term}」在正文中无实证'

    def test_T_R4_17_imports_terms_appear_in_body(self, real_copy):
        """ch_02 的每个 imports 术语在 ch_02 正文中确有出现（确实引用了上游）。

        允许核心成分匹配：term 是上游的**符号字面**，本章正文写法可不同。
        """
        meta = dep_meta(real_copy)
        body = (real_copy / '章节' / 'ch_02' / 'draft.md').read_text(encoding='utf-8')
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", body, flags=re.S)
        for item in meta['imports']['ch_02']:
            term = item['term']
            assert (term in body) or (_core(term, body) in body), \
                f'ch_02 imports 术语「{term}」在 ch_02 正文中无实证'

    def test_T_R4_18_no_self_loop(self, real_copy):
        """依赖图不得自环（自己 import 自己）。"""
        meta = dep_meta(real_copy)
        for ch, items in meta['imports'].items():
            for it in items:
                assert it['from'] != ch, f'{ch} 自环 import'

    def test_T_R4_19_import_term_is_exact_upstream_symbol(self, real_copy):
        """imports.term 必须逐字等于上游 exports 的某一项（判据的匹配前提）。"""
        meta = dep_meta(real_copy)
        for ch, items in meta['imports'].items():
            for it in items:
                src = it['from']
                assert it['term'] in meta['exports'].get(src, []), \
                    f'{ch} imports「{it["term"]}」不是 {src} 的 exports 成员'


# ── ⑦ 真值对照：包内 fixture 与真实教材工作区必须一致 ────────────────
class TestLiveParity:
    """包内 fixture 是真实教材的**快照**；两者必须一致，否则 fixture 已过期。"""

    def test_T_R4_20_fixture_frontmatter_matches_live(self, live_copy):
        """fixture 的 frontmatter 必须与真实教材**逐字一致**（含声明）。"""
        if REAL_ROOT is None:
            pytest.skip('未设置 STT_REAL_ROOT')
        for ch in ('ch_01', 'ch_02'):
            live = (live_copy / '章节' / ch / 'draft.md').read_text(encoding='utf-8')
            fix = (FIXTURE_ROOT / ch / 'draft.md').read_text(encoding='utf-8')
            lm = re.match(r"^---\s*\n(.*?)\n---\s*\n", live, re.S)
            fm_ = re.match(r"^---\s*\n(.*?)\n---\s*\n", fix, re.S)
            assert lm and fm_, f'{ch} 缺 frontmatter'
            assert lm.group(1) == fm_.group(1), \
                f'{ch} fixture 的 frontmatter 与真实教材不一致——fixture 已过期，须重新抽取'

    def test_T_R4_21_live_graph_activated(self, live_copy):
        """真实教材工作区：依赖图已激活（未声明章为空）。"""
        meta = dep_meta(live_copy)
        assert meta['undeclared_chapters'] == [], meta['undeclared_chapters']
        assert not [i for i in dep_issues(live_copy) if i['severity'] == 'FAIL']

    def test_T_R4_22_live_closure(self, live_copy):
        """真实教材工作区：--affected-from ch_01 ⇒ 闭包命中 ch_02。"""
        meta = dep_meta(live_copy, '--affected-from', 'ch_01')
        assert 'ch_02' in meta['affected_chapters'], meta['affected_chapters']


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
