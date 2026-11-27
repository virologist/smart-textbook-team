#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_package_release.py — 分发包排除清单的回归测试（2026-11-27 DEF-2）

背景
----
`package_release.sh` 的排除清单是**分发包瘦身 + 内部信息不外泄**的唯一闸门。
清单是**黑名单式**的：每加一个新目录进来，默认都会被 `zip -r` 打进分发包。

DEF-2（2026-11-27 复测）：`04-test/`（流程留档目录，收录测试报告 /
审计报告 / 成员报告）**未被排除** ⇒ 打进对外分发 zip。
该目录与 `.harness-kb` / `.wiki-creator` / `docs/00_archive` 同级——
都是「仓库内有意留痕（04-test 甚至是 git 跟踪的公开流程证据），
但不对外分发」的内部资产。此前只有后三者被排除，04-test 漏排。

本文件做两件事：
  ① 负向：断言打包产物 zip 内**不含** `04-test/` 条目；
  ② 正向：断言打包产物 zip 内**含** `.codebuddy-plugin/plugin.json`
     （防「排除逻辑写错位置，把整包内容也排掉了」这种过度修正）。

⚠ 为什么不用 pytest 内置 `tmp_path`：本包运行在 OneDrive 沙箱环境下，
  pytest 的 basetemp 创建会被宿主拦截（FileExistsError），而
  `tempfile.mkdtemp` 走同一挂载点却正常。已实测（与 tests/test_core_scripts.py
  的 work_root fixture 同一口径，理由见该文件注释）。

运行：python3 -m pytest tests/test_package_release.py -v
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_SH = PKG_ROOT / 'scripts' / 'package_release.sh'


# ── 工具 ────────────────────────────────────────────────────────────────

@pytest.fixture()
def work_root():
    """临时工作区（不用 pytest tmp_path：OneDrive 沙箱下 basetemp 创建会被拦截）。"""
    d = tempfile.mkdtemp(prefix='stt_pkgrel_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run_package(out_zip: Path) -> subprocess.CompletedProcess:
    """跑 package_release.sh，**显式**传输出路径。

    ⚠ 绝不能省略输出路径——脚本默认写 OneDrive 真实分发路径
    （DEFAULT_OUT），测试里跑默认分支会污染真实分发包。
    """
    return subprocess.run(
        ['bash', str(PACKAGE_SH), str(out_zip)],
        cwd=str(PKG_ROOT), capture_output=True, text=True)


def _zip_names(out_zip: Path) -> list[str]:
    """zip 内全部条目名（目录条目也含）。"""
    with zipfile.ZipFile(out_zip) as zf:
        return zf.namelist()


def _assert_predicate_can_see(predicate, target_rel: str,
                              real_names: list[str]) -> None:
    """**前置自检**：断言「某路径不在 zip 内」之前，先证明**断言用的那个谓词**
    真的能观察到该路径。

    ⚠ 为什么必须加这层（coder2 2026-11-27 提醒，同类坑）：
      负例断言 `assert not [n for n in names if P(n)]` 在 zip 恰好不含该
      路径时会**真空通过**——若谓词 P 本身写错（前缀拼错、大小写不符、
      层级偏移），用例会静默空转、假绿。典型同源事故：某反例把
      `task-router` 误写成 `task_router`，正则不匹配 ⇒ 该行根本不进
      判定路径 ⇒ 用例什么都没测却报绿。

    实现要点（**第一版写错过，此处是修正版**）：
      必须把**断言真正使用的那��谓词对象**传进来，再拿它去匹配合成探针；
      若守卫自己另写一份谓词，守卫测的就不是断言用的那个谓词 ⇒ 谓词写错
      时守卫照样通过 ⇒ 守卫形同虚设（这正是第一版的缺陷：守卫合成自己
      要找的路径再去找它 ⇒ 永远通过）。

    `predicate`：断言用的谓词（形如 `lambda n: n.startswith(prefix)`）。
    `target_rel`：目标相对路径（如 '04-test' / 'docs/00_archive'）。
    `real_names`：真实 zip 的条目名（仅作探针场景上下文）。
    """
    probe = f'smart-textbook-team/{target_rel}/探针.md'
    synthetic = list(real_names) + [probe]
    assert any(predicate(n) for n in synthetic), (
        f'断言谓词无法观察 {target_rel}（前缀可能拼错/层级偏移）⇒ '
        f'本用例会真空通过、什么都没测'
    )


# ══════════════════════════════════════════════════════════════════════
# 1. 排除清单：内部资产不进分发包
# ══════════════════════════════════════════════════════════════════════

class TestPackageExcludesInternalAssets:
    """负向：内部流程资产必须不在 zip 内"""

    def test_04_test_dir_not_in_zip(self, work_root):
        """DEF-2 核心回归：`04-test/` 不进分发包。

        04-test 收录测试报告 / 一致性审计报告 / 可靠性诊断报告等流程留档，
        属内部运行态证据——与 .harness-kb / .wiki-creator / docs/00_archive
        同口径，不应对外分发。
        """
        out = work_root / 'out.zip'
        r = _run_package(out)
        assert r.returncode == 0, r.stdout + r.stderr
        assert out.is_file(), '打包产物未生成'

        names = _zip_names(out)
        # 谓词**只定义一次**，自检与断言共用 ⇒ 守卫测的就是断言用的那个
        is_04_test = lambda n: n.startswith('smart-textbook-team/04-test')  # noqa: E731
        _assert_predicate_can_see(is_04_test, '04-test', names)
        leaked = [n for n in names if is_04_test(n)]
        assert not leaked, f'04-test 泄漏进分发包: {leaked}'

    @pytest.mark.parametrize('dirname', ['.harness-kb', '.wiki-creator'])
    def test_runtime_dirs_still_excluded(self, work_root, dirname):
        """回归护栏：既有排除项不得被本次改动挤掉。"""
        out = work_root / 'out.zip'
        r = _run_package(out)
        assert r.returncode == 0, r.stdout + r.stderr
        names = _zip_names(out)
        is_dir = lambda n: n.startswith(f'smart-textbook-team/{dirname}')  # noqa: E731
        _assert_predicate_can_see(is_dir, dirname, names)
        leaked = [n for n in names if is_dir(n)]
        assert not leaked, f'{dirname} 泄漏进分发包: {leaked}'

    def test_00_archive_still_excluded(self, work_root):
        """回归护栏：docs/00_archive 归档留痕仍不进分发包。"""
        out = work_root / 'out.zip'
        r = _run_package(out)
        assert r.returncode == 0, r.stdout + r.stderr
        names = _zip_names(out)
        is_archive = lambda n: n.startswith('smart-textbook-team/docs/00_archive')  # noqa: E731
        _assert_predicate_can_see(is_archive, 'docs/00_archive', names)
        leaked = [n for n in names if is_archive(n)]
        assert not leaked, f'docs/00_archive 泄漏进分发包: {leaked}'

    def test_predicate_guard_detects_broken_predicate(self):
        """**前置自检自身的负控制**：谓词写错时，守卫必须 FAIL。

        证明 `_assert_predicate_can_see` 不是「永远通过」的摆设——
        喂一个**根本观察不到**目标路径的谓词（模拟前缀拼错），它必须报错。
        这条同时锁死守卫的实现：若守卫自己另写谓词 / 自造探针路径，
        本用例会红（守卫形同虚设）。
        """
        broken = lambda n: n.startswith('smart-textbook-team/04-tst')  # noqa: E731
        with pytest.raises(AssertionError, match='无法观察'):
            _assert_predicate_can_see(broken, '04-test', ['smart-textbook-team/a.py'])


# ══════════════════════════════════════════════════════════════════════
# 2. 正向：包内容必须齐全（防「排除写过头」）
# ══════════════════════════════════════════════════════════════════════

class TestPackageKeepsCoreContent:
    """正向：排除清单不得误伤真实包内容"""

    def test_plugin_manifest_present_in_zip(self, work_root):
        """`.codebuddy-plugin/plugin.json` 必须在 zip 内。

        这是宿主识别插件的必需文件——排除逻辑若写错路径（如把排除项
        误写成包根），会把整包内容一起排掉，本用例即为守卫。
        """
        out = work_root / 'out.zip'
        r = _run_package(out)
        assert r.returncode == 0, r.stdout + r.stderr

        names = _zip_names(out)
        assert 'smart-textbook-team/.codebuddy-plugin/plugin.json' in names, \
            f'plugin.json 缺失（排除逻辑误伤包内容）: {names[:20]}'

    def test_scripts_and_skills_present_in_zip(self, work_root):
        """脚本与技能目录必须完整（包内容的骨架）。"""
        out = work_root / 'out.zip'
        r = _run_package(out)
        assert r.returncode == 0, r.stdout + r.stderr

        names = _zip_names(out)
        assert any(n.startswith('smart-textbook-team/scripts/') for n in names), \
            'scripts/ 缺失'
        assert any(n.startswith('smart-textbook-team/skills/') for n in names), \
            'skills/ 缺失'

    def test_zip_version_matches_source_manifest(self, work_root):
        """zip 内 plugin.json 的版本必须与源仓一致（打包脚本自带闸门）。"""
        import json
        out = work_root / 'out.zip'
        r = _run_package(out)
        assert r.returncode == 0, r.stdout + r.stderr

        with zipfile.ZipFile(out) as zf:
            data = json.loads(zf.read(
                'smart-textbook-team/.codebuddy-plugin/plugin.json').decode('utf-8'))
        src = json.loads((PKG_ROOT / '.codebuddy-plugin' / 'plugin.json')
                         .read_text(encoding='utf-8'))
        assert data['version'] == src['version'], \
            f"zip 版本 {data['version']} != 源仓 {src['version']}"


# ══════════════════════════════════════════════════════════════════════
# 3. 幂等：同输入重跑同结果（写操作幂等要求）
# ══════════════════════════════════════════════════════════════════════

class TestPackageIsIdempotent:
    """打包到同一路径重跑 ⇒ 结果等价（覆盖式写入不得产生累积差异）"""

    def test_repackage_same_path_same_content(self, work_root):
        out = work_root / 'out.zip'
        r1 = _run_package(out)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        first = sorted(_zip_names(out))

        r2 = _run_package(out)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        second = sorted(_zip_names(out))

        assert first == second, '重复打包产物条目不一致（幂等性被破坏）'
        assert not any(n.startswith('smart-textbook-team/04-test')
                       for n in second), '重复打包后 04-test 仍泄漏'
