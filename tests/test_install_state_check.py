#!/usr/bin/env python3
"""test_install_state_check.py — 安装态一致性检查器的回归测试（2026-11-04 B1 批次）

背景
----
诊断报告 Q1（严重度：高，影响面：协议正确性）：
  `my-experts` / `experts` 是 `type: directory` + `autoUpdate: false`
  的 marketplace → 宿主**不会**把源码同步到 cache；
  而 `installed_plugins.json` 里 239 条 installPath **全部**指向 cache。
  ⇒ 源码改了、commit 了、push 了，专家团跑的**仍是旧代码**。

更隐蔽的一层：版本号相同也会漏。
  宿主按 `plugin.json` 的 version 判定「是否需要更新」——
  源码改内容但没升版本号 → 宿主判定「无需更新」→ cache 永远停在旧快照。
  ⇒ 必须做**内容级 sha256 比对**，只比版本号是不够的。

首版实现踩过的坑（这就是本文件存在的理由）：
  只排除了元数据**目录**，没排除元数据**文件** `.downloaded_at`
  （宿主写的下载时间戳，只存在于安装态）→ 12 个包恒定报「内容陈旧 1 项」
  → 真漂移被噪声淹没，一致包数从 26 掉到 20（实测）。

本文件做两件事：
  ① 正向：构造可控的假插件根，验证分类（SRC_ONLY/DIFF/CACHE_ONLY/
     SOURCE_MISSING）与退出码（0/1/2）符合约定；
  ② 负向：注入元数据噪声，验证**不产生假漂移**（真漂移零容忍 + 假漂移零容忍）。

运行：python3 -m pytest tests/test_install_state_check.py -v
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

import install_state_check as isc  # noqa: E402


# ── 工具 ────────────────────────────────────────────────────────────────

@pytest.fixture()
def work_root():
    """临时工作区。

    不用 pytest 内置 tmp_path —— 本包运行在 OneDrive 沙箱环境下，
    pytest 的 basetemp 创建会被宿主拦截（FileExistsError），
    而 tempfile.mkdtemp 走同一挂载点却正常。已实测。
    """
    d = tempfile.mkdtemp(prefix='stt_isc_')
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        isc._FILE_HASH_CACHE.clear()


def _write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    return p


def make_plugins_root(root: Path, *, mp: str = 'my-experts',
                      pkg: str = 'demo-pkg',
                      src_files: dict | None = None,
                      cache_files: dict | None = None,
                      src_dir_exists: bool = True,
                      cache_dir_exists: bool = True,
                      installed: bool = True,
                      known: bool = True) -> Path:
    """搭一个最小可用的「假插件根」。

    结构：
      <root>/marketplaces/<mp>/plugins/<pkg>/...     ← 源码态
      <root>/cache/<mp>/<pkg>/<ver>/...              ← 安装态
      <root>/installed_plugins.json                  ← installPath 登记表
      <root>/known_marketplaces.json                 ← directory 型 path 登记
    """
    src_root = root / 'marketplaces' / mp / 'plugins' / pkg
    cache_root = root / 'cache' / mp / pkg / '1.0.0'

    if src_dir_exists:
        src_root.mkdir(parents=True, exist_ok=True)
        for rel, body in (src_files or {}).items():
            _write(src_root / rel, body)
    if cache_dir_exists:
        cache_root.mkdir(parents=True, exist_ok=True)
        for rel, body in (cache_files or {}).items():
            _write(cache_root / rel, body)

    if installed:
        _write(root / 'installed_plugins.json', json.dumps({
            'plugins': {
                f'{mp}:{pkg}': [{
                    'installPath': str(cache_root),
                    'version': '1.0.0',
                    'name': pkg,
                }],
            },
        }, ensure_ascii=False))
    if known:
        _write(root / 'known_marketplaces.json', json.dumps({
            'marketplaces': {
                mp: {
                    'type': 'directory',
                    'source': {'source': 'directory',
                               'path': str(root / 'marketplaces' / mp)},
                    'autoUpdate': False,
                },
            },
        }, ensure_ascii=False))
    return root


def run_cli(*extra: str) -> subprocess.CompletedProcess:
    """裸跑 install_state_check.py（不经 shell，便于断言退出码）"""
    cmd = [sys.executable, str(SCRIPTS / 'install_state_check.py')]
    return subprocess.run(cmd + list(extra), capture_output=True, text=True)


# ══════════════════════════════════════════════════════════════════════
# 1. 文件收集与元数据排除（假漂移零容忍 —— 首版实战的坑）
# ══════════════════════════════════════════════════════════════════════

class TestCollectFiles:
    """collect_files 必须把元数据挡在包内容之外"""

    def test_excludes_downloaded_at_file(self, work_root):
        """首版真坑：.downloaded_at 是宿主下载时间戳，只在安装态。

        不排除 → 每个包恒定报「内容陈旧 1 项」→ 真漂移被噪声淹没。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / '.downloaded_at', '2026-11-04T10:00:00')
        files = isc.collect_files(pkg)
        assert 'a.py' in files
        assert '.downloaded_at' not in files, '下载时间戳不是包内容，必须排除'

    @pytest.mark.parametrize('dirname', ['.git', '.in_use', '.pytest_cache',
                                         '__pycache__'])
    def test_excludes_metadata_dirs(self, work_root, dirname):
        """元数据目录不是包内容（.in_use 是宿主运行时锁，含 pid/procStart）"""
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / dirname / 'noise.txt', 'noise')
        files = isc.collect_files(pkg)
        assert 'a.py' in files
        assert not any(k.startswith(dirname + '/') for k in files)

    def test_excludes_ds_store_file(self, work_root):
        pkg = work_root / 'pkg'
        _write(pkg / '.DS_Store', 'junk')
        assert isc.collect_files(pkg) == {}

    def test_missing_dir_returns_empty(self, work_root):
        assert isc.collect_files(work_root / 'nope') == {}

    def test_sha256_cache_is_keyed_by_path(self, work_root):
        """同一文件算两次必须走缓存（性能），但不同路径不能串味"""
        a = _write(work_root / 'a.txt', 'aaa')
        b = _write(work_root / 'b.txt', 'bbb')
        h_a = isc._sha256(a)
        h_b = isc._sha256(b)
        assert h_a != h_b
        assert isc._sha256(a) == h_a


# ══════════════════════════════════════════════════════════════════════
# 2. 比对分类（4 种状态）
# ══════════════════════════════════════════════════════════════════════

class TestComparePair:
    """compare_pair 的分类必须与诊断报告口径一致"""

    def test_all_same(self, work_root):
        src = work_root / 'src'
        cache = work_root / 'cache'
        _write(src / 'a.py', 'same')
        _write(cache / 'a.py', 'same')
        r = isc.compare_pair(src, cache)
        assert r['consistent'] is True
        assert r['status'] == 'SAME'
        assert r['src_only'] == [] and r['diff'] == [] and r['cache_only'] == []

    def test_src_only(self, work_root):
        """仅源码有 → 安装态缺文件 → 运行时加载不到"""
        src = work_root / 'src'
        cache = work_root / 'cache'
        _write(src / 'a.py', 'same')
        _write(src / 'scheduler.py', 'new')
        _write(cache / 'a.py', 'same')
        r = isc.compare_pair(src, cache)
        assert r['status'] == 'DRIFT'
        assert r['src_only'] == ['scheduler.py']
        assert r['diff'] == [] and r['cache_only'] == []

    def test_diff(self, work_root):
        """两边都有但内容不同 → 运行时跑的是旧代码"""
        src = work_root / 'src'
        cache = work_root / 'cache'
        _write(src / 'a.py', 'NEW')
        _write(cache / 'a.py', 'OLD')
        r = isc.compare_pair(src, cache)
        assert r['status'] == 'DRIFT'
        assert r['diff'] == ['a.py']
        assert r['src_only'] == [] and r['cache_only'] == []

    def test_cache_only(self, work_root):
        """仅安装态有 → 源码已删，可能是残留垃圾"""
        src = work_root / 'src'
        cache = work_root / 'cache'
        _write(src / 'a.py', 'same')
        _write(cache / 'a.py', 'same')
        _write(cache / 'leftover.py', 'stale')
        r = isc.compare_pair(src, cache)
        assert r['status'] == 'DRIFT'
        assert r['cache_only'] == ['leftover.py']

    def test_same_count_excludes_diff(self, work_root):
        src = work_root / 'src'
        cache = work_root / 'cache'
        _write(src / 'a.py', 'x')
        _write(src / 'b.py', 'x')
        _write(cache / 'a.py', 'x')
        _write(cache / 'b.py', 'DIFFERENT')
        r = isc.compare_pair(src, cache)
        assert r['same_count'] == 1
        assert r['diff'] == ['b.py']


# ══════════════════════════════════════════════════════════════════════
# 3. 登记表解析与源码定位
# ══════════════════════════════════════════════════════════════════════

class TestRegistryParsing:
    """installed_plugins.json / known_marketplaces.json 解析"""

    def test_read_installed_map(self, work_root):
        make_plugins_root(work_root)
        m = isc.read_installed_map(work_root)
        assert 'my-experts/demo-pkg' in m
        info = m['my-experts/demo-pkg']
        assert info['version'] == '1.0.0'
        assert info['installPath'].endswith('demo-pkg/1.0.0')

    def test_read_installed_map_accepts_dict_entry(self, work_root):
        """installed_plugins.json 里 value 可能是 dict 而非 list"""
        _write(work_root / 'installed_plugins.json', json.dumps({
            'plugins': {
                'my-experts:demo': {
                    'installPath': str(work_root / 'cache/my-experts/demo/1.0.0'),
                    'version': '2.0.0',
                },
            },
        }))
        m = isc.read_installed_map(work_root)
        assert m['my-experts/demo']['version'] == '2.0.0'

    def test_read_installed_map_ignores_other_marketplaces(self, work_root):
        """官方 marketplace 的 cache 由宿主自己管，不查"""
        _write(work_root / 'installed_plugins.json', json.dumps({
            'plugins': {
                'official:foo': [{'installPath': '/x/cache/official/foo/1.0.0',
                                 'version': '1.0.0'}],
            },
        }))
        assert isc.read_installed_map(work_root) == {}

    def test_read_installed_map_tolerates_bad_json(self, work_root):
        _write(work_root / 'installed_plugins.json', '{not json')
        assert isc.read_installed_map(work_root) == {}

    def test_find_source_dir_prefers_known_path(self, work_root):
        """directory 型 marketplace 的 path 未必是 marketplaces/{mp}"""
        alt = work_root / 'alt_location'
        pkg = alt / 'plugins' / 'demo-pkg'
        _write(pkg / 'a.py', 'x')
        _write(work_root / 'known_marketplaces.json', json.dumps({
            'marketplaces': {
                'my-experts': {
                    'source': {'source': 'directory', 'path': str(alt)},
                },
            },
        }))
        found = isc.find_source_dir(work_root, 'my-experts', 'demo-pkg')
        assert found is not None and found == pkg

    def test_find_source_dir_falls_back_to_default_layout(self, work_root):
        """known_marketplaces.json 读不到时回落默认布局"""
        make_plugins_root(work_root, known=False)
        found = isc.find_source_dir(work_root, 'my-experts', 'demo-pkg')
        assert found is not None
        assert found.name == 'demo-pkg'
        assert found.parent.name == 'plugins'

    def test_find_source_dir_returns_none_when_absent(self, work_root):
        make_plugins_root(work_root, src_dir_exists=False)
        assert isc.find_source_dir(work_root, 'my-experts', 'demo-pkg') is None


# ══════════════════════════════════════════════════════════════════════
# 4. 报告生成
# ══════════════════════════════════════════════════════════════════════

class TestBuildReport:
    """build_report 的四种状态与计数"""

    def test_consistent_report(self, work_root):
        make_plugins_root(work_root,
                          src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        rep = isc.build_report(work_root, ('my-experts',), None)
        assert rep['total'] == 1
        assert rep['consistent'] == 1
        assert rep['drift'] == 0
        assert rep['status'] == 'CONSISTENT'

    def test_source_missing_orphan(self, work_root):
        """源码目录不存在 → 安装态成孤儿（源码已删但宿主还在装）"""
        make_plugins_root(work_root, src_dir_exists=False,
                          cache_files={'a.py': 'x'})
        rep = isc.build_report(work_root, ('my-experts',), None)
        p = rep['packages'][0]
        assert p['status'] == 'SOURCE_MISSING'
        assert p['consistent'] is False
        assert rep['status'] == 'DRIFT'

    def test_cache_missing(self, work_root):
        """安装态目录不存在 → 宿主可能未真正安装"""
        make_plugins_root(work_root, src_files={'a.py': 'x'},
                          cache_dir_exists=False)
        rep = isc.build_report(work_root, ('my-experts',), None)
        p = rep['packages'][0]
        assert p['status'] == 'CACHE_MISSING'
        assert rep['status'] == 'DRIFT'

    def test_pkg_filter(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        rep = isc.build_report(work_root, ('my-experts',), ['other-pkg'])
        assert rep['total'] == 0

    def test_marketplace_filter(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        rep = isc.build_report(work_root, ('experts',), None)
        assert rep['total'] == 0


# ══════════════════════════════════════════════════════════════════════
# 5. 默认插件根探测（领域中立门禁：不许硬编码宿主点目录）
# ══════════════════════════════════════════════════════════════════════

class TestDefaultPluginsRoot:
    """default_plugins_root：环境变量优先 → 候选根兜底 → None"""

    def test_env_var_wins(self, work_root, monkeypatch):
        make_plugins_root(work_root)
        monkeypatch.setenv(isc.INSTALL_ROOT_ENV, str(work_root))
        got = isc.default_plugins_root()
        assert got is not None and got == work_root.resolve()

    def test_env_var_invalid_falls_back(self, work_root, monkeypatch):
        """环境变量指向不存在目录 → 不崩，回落候选根"""
        monkeypatch.setenv(isc.INSTALL_ROOT_ENV, str(work_root / 'nope'))
        home = work_root / 'fakehome'
        (home / '.workbuddy' / 'plugins').mkdir(parents=True)
        monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
        got = isc.default_plugins_root()
        assert got is not None
        assert got == (home / '.workbuddy' / 'plugins').resolve()

    def test_candidate_fallback_supports_second_product_root(self, work_root,
                                                            monkeypatch):
        """宿主各产品点目录名不同 → 必须支持多候选，不能写死一个"""
        home = work_root / 'home2'
        (home / '.codebuddy' / 'plugins').mkdir(parents=True)
        monkeypatch.delenv(isc.INSTALL_ROOT_ENV, raising=False)
        monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
        got = isc.default_plugins_root()
        assert got is not None
        assert got == (home / '.codebuddy' / 'plugins').resolve()

    def test_returns_none_when_nothing_found(self, work_root, monkeypatch):
        home = work_root / 'emptyhome'
        home.mkdir()
        monkeypatch.delenv(isc.INSTALL_ROOT_ENV, raising=False)
        monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
        assert isc.default_plugins_root() is None

    def test_no_hardcoded_home_path_in_source(self):
        """源码里不得出现宿主点目录字面量（check_domain_neutral 门禁）"""
        src = (SCRIPTS / 'install_state_check.py').read_text(encoding='utf-8')
        for bad in ('/Users/', 'C:\\\\', '~/' + '.workbuddy'):
            assert bad not in src, f'硬编码绝对路径：{bad}'


# ══════════════════════════════════════════════════════════════════════
# 6. CLI 退出码（0 一致 / 1 漂移 / 2 输入错误）
# ══════════════════════════════════════════════════════════════════════

class TestCliExitCodes:
    """退出码契约：0=CONSISTENT 1=DRIFT 2=INPUT_ERROR"""

    def test_exit_0_when_consistent(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr

    def test_exit_1_when_drift(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'NEW'},
                          cache_files={'a.py': 'OLD'})
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_DRIFT, r.stdout + r.stderr

    def test_exit_2_when_root_missing(self, work_root):
        r = run_cli('--plugins-root', str(work_root / 'nope'))
        assert r.returncode == isc.EXIT_INPUT_ERROR

    def test_exit_2_when_root_unset(self, work_root, monkeypatch):
        """既无环境变量也无候选根 → 输入错误（不是崩溃）。

        注意：脚本在**子进程**里跑，monkeypatch 改不动它的 Path.home()；
        因此改用「环境变量指向不存在目录 + HOME 指向空目录」来构造
        「探测不到任何候选根」的场景。
        """
        home = work_root / 'bare'
        home.mkdir()
        monkeypatch.setenv('HOME', str(home))
        monkeypatch.setenv(isc.INSTALL_ROOT_ENV, str(work_root / 'nope'))
        r = run_cli()
        assert r.returncode == isc.EXIT_INPUT_ERROR, r.stdout + r.stderr

    def test_json_output_is_machine_readable(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        r = run_cli('--plugins-root', str(work_root), '--json')
        data = json.loads(r.stdout)
        assert data['status'] == 'CONSISTENT'
        assert data['total'] == 1
        assert 'packages' in data

    def test_metadata_only_difference_is_not_drift(self, work_root):
        """负向核心：安装态多一个 .downloaded_at → **不得**报漂移。

        这是首版实战的真坑（12 个包恒定报陈旧 1 项）。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        cache_dir = work_root / 'cache' / 'my-experts' / 'demo-pkg' / '1.0.0'
        _write(cache_dir / '.downloaded_at', '2026-11-04T10:00:00')
        (cache_dir / '.in_use').mkdir(exist_ok=True)
        _write(cache_dir / '.in_use' / '94544', '{"pid":123}')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr


# ══════════════════════════════════════════════════════════════════════
# 7. 快照机制（--snapshot / --changed-only）
# ══════════════════════════════════════════════════════════════════════

class TestSnapshot:
    """快照：存基线 → 比变化"""

    def test_snapshot_first_run_writes_file(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        snap = work_root / 'snap.json'
        run_cli('--plugins-root', str(work_root), '--snapshot', str(snap))
        assert snap.is_file()
        data = json.loads(snap.read_text(encoding='utf-8'))
        assert 'my-experts/demo-pkg' in data['packages']
        assert 'ts' in data

    def test_changed_only_detects_modification(self, work_root):
        """第一次快照 → 源码改动 → 第二次应报 MODIFIED"""
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        snap = work_root / 'snap.json'
        run_cli('--plugins-root', str(work_root), '--snapshot', str(snap))
        # 改源码 → 与快照相比出现漂移
        _write(work_root / 'marketplaces' / 'my-experts' / 'plugins' /
               'demo-pkg' / 'a.py', 'CHANGED')
        isc._FILE_HASH_CACHE.clear()
        r = run_cli('--plugins-root', str(work_root), '--snapshot', str(snap),
                    '--changed-only')
        assert 'MODIFIED' in r.stdout
        assert 'demo-pkg' in r.stdout

    def test_changed_only_hides_unchanged(self, work_root):
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        snap = work_root / 'snap.json'
        run_cli('--plugins-root', str(work_root), '--snapshot', str(snap))
        r = run_cli('--plugins-root', str(work_root), '--snapshot', str(snap),
                    '--changed-only')
        assert 'demo-pkg' not in r.stdout


# ══════════════════════════════════════════════════════════════════════
# 8. 只读契约（本脚本绝不改安装态文件）
# ══════════════════════════════════════════════════════════════════════

class TestReadOnlyContract:
    """只读：跑完检查器后，安装态与源码态文件内容一字不变"""

    def test_files_unchanged_after_run(self, work_root):
        src_files = {'a.py': 'same', 'sub/b.py': 'same'}
        cache_files = {'a.py': 'OLD'}
        make_plugins_root(work_root, src_files=src_files, cache_files=cache_files)
        src_root = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        cache_root = work_root / 'cache' / 'my-experts' / 'demo-pkg' / '1.0.0'

        before = {}
        for base in (src_root, cache_root):
            for p in sorted(base.rglob('*')):
                if p.is_file():
                    before[str(p)] = p.read_text(encoding='utf-8')

        run_cli('--plugins-root', str(work_root), '--json')

        after = {}
        for base in (src_root, cache_root):
            for p in sorted(base.rglob('*')):
                if p.is_file():
                    after[str(p)] = p.read_text(encoding='utf-8')
        assert before == after, '检查器必须只读，不得改动任何文件'
