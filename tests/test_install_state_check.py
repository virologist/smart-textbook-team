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

    def test_excludes_orphaned_at_file(self, work_root):
        """宿主「孤儿标记」时间戳，同 .downloaded_at 性质（只存在于安装态）。

        实测（2026-11-27）：zip 内 0 项 / 源码 git 跟踪 0 项 / 各版本 cache 皆有，
        内容为 epoch 毫秒。不排除 ⇒ 每次升版后宿主必然报「安装态多出 1 项」
        = 纯假漂移（v2.20.0 实测已发生）。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / '.orphaned_at', '1795746776286')
        files = isc.collect_files(pkg)
        assert 'a.py' in files
        assert '.orphaned_at' not in files, '宿主孤儿标记不是包内容，必须排除'

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

    @pytest.mark.parametrize('dirname', ['.workbuddy', '.versionctl'])
    def test_excludes_runtime_dirs(self, work_root, dirname):
        """运行态目录不是包内容（防复发守卫 · 2026-11-04 v3.28.7）

        背景：`.workbuddy/`（宿主运行态：记忆体/任务台账）与 `.versionctl/`
        （版本控制运行态）存在于本机源码工作副本，但被 `.gitignore` 排除
        （实测 `git ls-files` 命中 0 项）⇒ 它们**永远进不了分发包**。
        若不排除：vet-med 包恒定报「安装态缺失 294 项」= 纯假漂移。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / dirname / 'nested' / 'state.json', '{"run":1}')
        files = isc.collect_files(pkg)
        assert 'a.py' in files
        assert not any(k.startswith(dirname + '/') for k in files)
        assert not any('.workbuddy' in k or '.versionctl' in k for k in files)

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

    def test_sha256_oserror_returns_path_sentinel_not_empty_hash(self, work_root):
        """A3 负例（2026-11-16）：读失败不得返回空内容 sha256。

        病灶：两端文件都读失败（OSError）时，若都退回空内容 sha256
        (e3b0c44…)，会因「哈希相同」被误判为『不漂移』——把 IO 故障
        伪装成健康。修复后必须返回带路径的哨兵，且不同路径哨兵不同。
        """
        isc._FILE_HASH_CACHE.clear()
        # 目录当作文件打开 → OSError（IsADirectoryError 是 OSError 子类）
        d1 = work_root / 'unreadable_a'
        d2 = work_root / 'unreadable_b'
        d1.mkdir()
        d2.mkdir()
        h1 = isc._sha256(d1)
        h2 = isc._sha256(d2)
        empty = __import__('hashlib').sha256(b'').hexdigest()
        assert h1.startswith('__IO_ERROR__:'), f"读失败未返回哨兵: {h1}"
        assert h1 != empty, "读失败不得返回空内容 sha256（会伪装成『不漂移』）"
        assert h1 != h2, "两个不同路径的读失败哨兵必须不同，否则仍会误判一致"
        # 读失败不得写缓存：同一路径恢复为真实文件后应算出真哈希（非哨兵）
        isc._FILE_HASH_CACHE.clear()
        recovering = work_root / 'recovering.txt'
        h_fail = isc._sha256(recovering)   # 尚不存在 → FileNotFoundError (OSError)
        assert h_fail.startswith('__IO_ERROR__:')
        recovering.write_text('ok', encoding='utf-8')
        h_ok = isc._sha256(recovering)
        assert not h_ok.startswith('__IO_ERROR__:'), "同路径恢复后不得复用读失败哨兵"



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
        """负向核心：安装态多出宿主元数据文件 → **不得**报漂移。

        这是首版实战的真坑（12 个包恒定报陈旧 1 项）。
        ★v2.20.0：并入 `.orphaned_at` —— 宿主「孤儿标记」时间戳，同属只存在于
        安装态的元数据（实测 zip 内 0 项 / 源码 git 跟踪 0 项），不排除则每次
        升版后宿主必然报「安装态多出 1 项」= 假漂移。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        cache_dir = work_root / 'cache' / 'my-experts' / 'demo-pkg' / '1.0.0'
        _write(cache_dir / '.downloaded_at', '2026-11-04T10:00:00')
        _write(cache_dir / '.orphaned_at', '1795746776286')
        (cache_dir / '.in_use').mkdir(exist_ok=True)
        _write(cache_dir / '.in_use' / '94544', '{"pid":123}')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr

    def test_runtime_dirs_only_in_source_are_not_drift(self, work_root):
        """负向核心：源码侧多出运行态目录 ⇒ **不得**报「安装态缺失」。

        实战真坑（vet-med 包）：`.workbuddy/` + `.versionctl/` 只存在于
        本机源码工作副本（被 .gitignore 排除），安装态没有 ⇒ 首版把
        294 个运行态文件算成「包内容缺失」，假漂移淹没真漂移。
        本用例锁死该行为，防止有人「好心」把运行态加回包内容。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        _write(src_dir / '.workbuddy' / 'memory' / 'log.md', 'runtime')
        _write(src_dir / '.versionctl' / 'state.json', '{"v":1}')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr
        assert '安装态缺失' not in r.stdout, r.stdout + r.stderr

    def test_04_test_archive_dir_only_in_source_is_not_drift(self, work_root):
        """负向核心（2026-11-27 DEF-2）：源码侧有 `04-test/` ⇒ **不得**报漂移。

        `04-test/` 是流程留档目录（测试报告 / 审计报告 / 成员报告）。
        仓库内**有意 git 入库**（公开流程证据），但 package_release.sh
        打包阶段有意排除（不进对外分发包）——与 `00_archive` 同级
        「源码留痕但不进分发包」。

        ⚠ git 忽略剪枝对它**无效**：04-test 被 git 跟踪 ⇒ 不在
          `git ls-files --others --ignored` 输出里 ⇒ 只能靠
          SRC_ONLY_EXCLUDE_DIRS（仅源码侧剪）。
          修复分发包后宿主从新 zip 安装，安装态不再有 04-test/，检查器
          若不排除 ⇒ 源码侧 3 个留档文件全算成「安装态缺失」= 假漂移
          （2026-11-27 实测：src_only 3 项 / EXIT=1）。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        _write(src_dir / '04-test' / '测试报告.md', '# 流程留档')
        _write(src_dir / '04-test' / '可靠性诊断报告.md', '# 流程留档')
        # 前置自检：确认「04-test 真的落在源码侧」——否则下面「04-test 不出现
        # 在报告里」是真空通过（路径写错/剪枝过度都可能被误判为绿）。
        src_seen = isc.collect_files(
            src_dir, extra_exclude_dirs=isc.SRC_ONLY_EXCLUDE_DIRS)
        assert 'a.py' in src_seen, '前置自检失败：源码侧文件未被收集'
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr
        assert '安装态缺失' not in r.stdout, r.stdout + r.stderr
        assert '04-test' not in r.stdout, r.stdout + r.stderr

    def test_04_test_in_cache_side_is_still_reported(self, work_root):
        """反向（2026-11-27 DEF-2 返工核心）：安装态残留 `04-test/` ⇒ **必须报**。

        首版修复把 `04-test` 塞进全局 `EXCLUDE_DIRS`，而该常量的剪枝是
        **双向**的（collect_files 遍历时剪目录 + 文件名命中即跳过，两侧共用）
        ⇒ 安装态侧的 `04-test/` 也被一并剪掉 ⇒ 真残留被彻底屏蔽
        （实测 cache_only=[] / EXIT=0 = **漏报**），且与本脚本自身宣称的
        语义（「安装态反而有 ⇒ 仍按 cache_only 报出（该清）」）直接矛盾。

        正确语义（单向剪枝，与 git 忽略剪枝同构）：
          · 源码侧有、安装态无 ⇒ 正常 ⇒ 不算漂移；
          · 安装态有、源码无   ⇒ **真残留**（旧分发包留下的）⇒ 须报出来。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        cache_dir = work_root / 'cache' / 'my-experts' / 'demo-pkg' / '1.0.0'
        _write(cache_dir / '04-test' / '测试报告.md', '# 旧分发包残留')
        # 前置自检：确认该文件**真的**被安装态侧 collect_files 观察到
        # （若路径写错或被误剪，下面「必须报出」会真空通过）。
        cache_seen = isc.collect_files(cache_dir)
        assert '04-test/测试报告.md' in cache_seen, \
            '前置自检失败：安装态侧未观察到该残留文件（路径写错或被误剪）'
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_DRIFT, r.stdout + r.stderr
        assert '安装态多出' in r.stdout, r.stdout + r.stderr
        assert '04-test/测试报告.md' in r.stdout, r.stdout + r.stderr

    def test_04_test_src_only_exclusion_is_one_sided(self, work_root):
        """单元级：`04-test` 的剪枝**只**在源码侧生效。

        直接锁死 SRC_ONLY_EXCLUDE_DIRS 的单向语义：
          · 源码侧 collect_files 剪掉 04-test；
          · 安装态侧 collect_files **不剪**（否则真残留会被屏蔽）。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / '04-test' / '测试报告.md', '# 留档')
        # 源码侧（带 extra_exclude_dirs）⇒ 剪掉
        src_files = isc.collect_files(
            pkg, extra_exclude_dirs=isc.SRC_ONLY_EXCLUDE_DIRS)
        assert 'a.py' in src_files
        assert not any(k.startswith('04-test/') for k in src_files), \
            '源码侧未剪 04-test（假漂移会复发）'
        # 安装态侧（不传 extra）⇒ **不剪**，真残留必须看得见
        cache_files = isc.collect_files(pkg)
        assert any(k.startswith('04-test/') for k in cache_files), \
            '安装态侧也被剪 ⇒ 真残留被屏蔽（漏报）'

    def test_global_exclude_dirs_semantics_unchanged(self, work_root):
        """回归护栏：全局 EXCLUDE_DIRS 的**双向**语义不得被本次改动破坏。

        既有成员（.git / .in_use / .harness-kb / .wiki-creator …）是
        **运行态/元数据**目录——本就不该出现在任一侧 ⇒ 两侧都剪才是对的。
        本次改动只把「源码留痕但不分发」类目录（04-test / 00_archive）
        迁到 SRC_ONLY_EXCLUDE_DIRS 这个**单独通道**，**不触碰**全局常量
        的其余成员 ⇒ 它们的行为必须原样保留。

        ⚠ `00_archive` 已于 v2.20.0 迁出本集合（它是**归档留痕**，
          与 04-test 同构），故本用例**不再**断言它的双向剪枝。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        for rel in ('.harness-kb/状态.md', '.wiki-creator/底座.md'):
            _write(pkg / rel, '留档')
        files = isc.collect_files(pkg)
        assert 'a.py' in files
        for rel in ('.harness-kb', '.wiki-creator'):
            assert not any(k.startswith(rel + '/') for k in files), \
                f'{rel} 的双向剪枝语义被破坏'
        # 运行态目录**不应**出现在任一侧：源码侧与安装态侧都剪
        assert '00_archive' not in isc.EXCLUDE_DIRS, \
            '00_archive 属「源码留痕但不分发」，不应留在全局双向集合'
        assert '00_archive' in isc.SRC_ONLY_EXCLUDE_DIRS, \
            '00_archive 应在单向剪枝集合'

    # ── 00_archive：与 04-test 同构（v2.20.0 主理人授权一并闭环）──

    def test_00_archive_src_only_is_not_drift(self, work_root):
        """三态之一：源码侧有 `docs/00_archive/` ⇒ **不得**报漂移。

        `docs/00_archive/` 是**归档留痕目录**（git 跟踪的三个历史资产，
        2026-11-16 归档），package_release.sh 打包阶段有意排除
        （分发包 -876KB）——与 `04-test` **完全同构**：
          · 仓库内有意 git 入库做可追溯留痕；
          · 不进对外分发包；
          · 被 git 跟踪 ⇒ git 忽略剪枝对它天然无效。

        故源码侧有、安装态无 ⇒ 正常，不算漂移。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        _write(src_dir / 'docs' / '00_archive' / '旧资产.md', '# 归档留痕')
        # 前置自检：确认归档文件**真的**落在源码侧（否则「不报漂移」是真空通过）
        src_seen = isc.collect_files(
            src_dir, extra_exclude_dirs=isc.SRC_ONLY_EXCLUDE_DIRS)
        assert 'a.py' in src_seen, '前置自检失败：源码侧文件未被收集'
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr
        assert '安装态缺失' not in r.stdout, r.stdout + r.stderr
        assert '00_archive' not in r.stdout, r.stdout + r.stderr

    def test_00_archive_in_cache_side_is_still_reported(self, work_root):
        """三态之二：安装态残留 `docs/00_archive/` ⇒ **必须报** cache_only。

        与 `04-test` 同根同症状：`00_archive` 原先误放在全局 EXCLUDE_DIRS
        （双向剪枝）⇒ 安装态侧被一并剪掉 ⇒ 真残留被屏蔽、报不出
        （实测 cache_only=[] / EXIT=0 = 漏报）。迁入 SRC_ONLY 后修复。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        cache_dir = work_root / 'cache' / 'my-experts' / 'demo-pkg' / '1.0.0'
        _write(cache_dir / 'docs' / '00_archive' / '旧资产.md', '# 旧分发包残留')
        # 前置自检：确认安装态侧**确实观察到**该残留（否则「必须报出」真空通过）
        cache_seen = isc.collect_files(cache_dir)
        assert 'docs/00_archive/旧资产.md' in cache_seen, \
            '前置自检失败：安装态侧未观察到该残留（路径写错或被误剪）'
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_DRIFT, r.stdout + r.stderr
        assert '安装态多出' in r.stdout, r.stdout + r.stderr
        assert 'docs/00_archive/旧资产.md' in r.stdout, r.stdout + r.stderr

    def test_00_archive_nested_pruning_is_one_sided(self, work_root):
        """三态之三（单元级）：**嵌套路径** `docs/00_archive` 的单向剪枝。

        `04-test` 是顶层目录名，`00_archive` 是**嵌套**路径
        （docs/00_archive）——必须实测确认嵌套层级的剪枝按预期工作：
          · 源码侧：docs/00_archive/ 被剪；
          · 安装态侧：docs/00_archive/ **不剪**（真残留须看得见）；
          · 两侧都**不得**误伤 docs/ 下的其它内容（不得整棵剪掉 docs/）。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / 'docs' / 'normal.md', '# 正常文档')
        _write(pkg / 'docs' / '00_archive' / '旧资产.md', '# 归档')
        # 源码侧 ⇒ 剪掉嵌套的 00_archive，保留 docs/ 下其它内容
        src_files = isc.collect_files(
            pkg, extra_exclude_dirs=isc.SRC_ONLY_EXCLUDE_DIRS)
        assert 'a.py' in src_files
        assert 'docs/normal.md' in src_files, '嵌套剪枝误伤了 docs/ 下的正常文档'
        assert not any('00_archive' in k for k in src_files), \
            '源码侧未剪 docs/00_archive（假漂移会复发）'
        # 安装态侧 ⇒ **不剪**，真残留必须看得见
        cache_files = isc.collect_files(pkg)
        assert 'docs/00_archive/旧资产.md' in cache_files, \
            '安装态侧也被剪 ⇒ 真残留被屏蔽（漏报）'
        assert 'docs/normal.md' in cache_files

    def test_00_archive_same_semantics_as_04_test(self, work_root):
        """同口径回归：`00_archive` 与 `04-test` 必须**行为一致**。

        两者都是「仓库内有意留痕、但不进对外分发包」的目录 ⇒ 检查器
        必须一视同仁。若一个单向、一个双向 ⇒ 同类场景仍会漏报。
        """
        pkg = work_root / 'pkg'
        _write(pkg / 'a.py', 'x')
        _write(pkg / '04-test' / '报告.md', '# 留档')
        _write(pkg / 'docs' / '00_archive' / '旧资产.md', '# 归档')

        src_files = isc.collect_files(
            pkg, extra_exclude_dirs=isc.SRC_ONLY_EXCLUDE_DIRS)
        cache_files = isc.collect_files(pkg)
        for rel in ('04-test/', 'docs/00_archive/'):
            assert not any(k.startswith(rel) for k in src_files), \
                f'源码侧未剪 {rel}'
            assert any(k.startswith(rel) for k in cache_files), \
                f'安装态侧被剪 {rel}（与 04-test 口径不一致）'


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


# ══════════════════════════════════════════════════════════════════════
# 9. R3-遗留 L4a：git 忽略路径必须排除（假漂移零容忍 · 2026-11-05）
# ══════════════════════════════════════════════════════════════════════
#
# 实战病灶（vet-med-ppt-team 实测）：
#   `packages/.mirror_backups/`（mirror_sync.py 每次 --confirm 同步前的备份目录，
#   实测 227 个文件 / 20MB）已在该包 `.gitignore` 中明确排除
#   （`git ls-files` 命中 0 项）⇒ 它们**永远进不了分发包**。
#   但检查器只排除了固定 6 个目录名 ⇒ 源码侧的备份目录被算成
#   「安装态缺失 30 项」= **纯假漂移**，与真实漂移（39 项内容 diff）同量级
#   ⇒ 假漂移淹没真漂移。
#
# 修复：不再逐个点名排除目录，改为**读源码仓自己的 .gitignore 语义**
#      （`git ls-files --others --ignored --exclude-standard --full-name`）。
#
# ⚠ 三轮实测踩坑全部固化为反向用例（本组存在的理由）：
#   ① 取「路径首段」当前缀 ⇒ 'packages/' ⇒ 整个 packages/ 被剪（含真包内容）
#   ② 取「文件所在目录」当前缀 ⇒ 'scripts/' ⇒ 整个 scripts/ 被剪（含真包内容）
#      ⇒ 两者都把源码侧文件数从 357 打到 41/117，产生**反向假漂移**
#   ③ 只有**逐路径精确匹配**是安全口径。

class TestGitIgnoredPaths:
    """源码仓 .gitignore 排除的路径不得算作「安装态缺失」"""

    @staticmethod
    def _make_git_repo(pkg_dir: Path, ignore_lines: list[str],
                       cache_dir: Path | None = None) -> None:
        """把 pkg_dir 变成一个带 .gitignore 的独立 git 仓（真实 git 语义）。

        注意：仓根 = 包目录 ⇒ `git ls-files --full-name` 的路径基准
        与 collect_files 的「相对包根」口径一致（my-experts 各包均如此布局，
        实测 `git -C plugins/vet-med-ppt-team rev-parse --show-toplevel`
        返回包目录本身）。

        `cache_dir` 给定时，`.gitignore` **也写入安装态** —— 真实包两侧都带
        `.gitignore`（实测 vet-med-ppt-team 源码与 cache 均有该文件），
        它是**包内容**，不是忽略规则的载体就自动消失。
        """
        import subprocess as sp
        pkg_dir.mkdir(parents=True, exist_ok=True)
        body = '\n'.join(ignore_lines) + '\n'
        (pkg_dir / '.gitignore').write_text(body, encoding='utf-8')
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / '.gitignore').write_text(body, encoding='utf-8')
        sp.run(['git', 'init', '-q'], cwd=pkg_dir, check=True,
               capture_output=True)
        sp.run(['git', 'config', 'user.email', 't@t.t'], cwd=pkg_dir, check=True)
        sp.run(['git', 'config', 'user.name', 't'], cwd=pkg_dir, check=True)

    def test_ignored_backup_dir_not_reported_as_missing(self, work_root):
        """核心正向：源码侧被 gitignore 的备份目录 ⇒ 不得报「安装态缺失」"""
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        self._make_git_repo(src_dir, ['packages/.mirror_backups/'],
                           cache_dir=work_root / 'cache' / 'my-experts' /
                           'demo-pkg' / '1.0.0')
        _write(src_dir / 'packages' / '.mirror_backups' / '20261031-062546' /
               'CHANGELOG.md', 'backup')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr
        assert '安装态缺失' not in r.stdout, r.stdout + r.stderr

    def test_ignored_file_pattern_not_prune_whole_dir(self, work_root):
        """反向①：忽略的是**文件模式**（scripts/*.bak_*）⇒ 只跳该文件。

        不得因此把整个 scripts/ 剪掉 —— 那是真包内容，
        剪掉会反向产生「安装态多出」假漂移（实测源码侧 357→41）。
        """
        make_plugins_root(work_root,
                          src_files={'a.py': 'same', 'scripts/harness.py': 'code'},
                          cache_files={'a.py': 'same', 'scripts/harness.py': 'code'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        self._make_git_repo(src_dir, ['*.bak_*'],
                           cache_dir=work_root / 'cache' / 'my-experts' /
                           'demo-pkg' / '1.0.0')
        _write(src_dir / 'scripts' / 'insight_carrier.py.bak_t9', 'old copy')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr
        assert '安装态缺失' not in r.stdout, r.stdout + r.stderr
        assert '安装态多出' not in r.stdout, r.stdout + r.stderr

    def test_nested_ignored_dir_keeps_sibling_content(self, work_root):
        """反向②：嵌套忽略目录（packages/.mirror_backups/）⇒ 兄弟目录保留。

        packages/vet-med-ppt-team/ 是**真包内容**，
        不得因 packages/.mirror_backups/ 被忽略而一起消失。
        """
        make_plugins_root(work_root,
                          src_files={'packages/real-pkg/plugin.json': '{"v":"1"}'},
                          cache_files={'packages/real-pkg/plugin.json': '{"v":"1"}'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        self._make_git_repo(src_dir, ['packages/.mirror_backups/'],
                           cache_dir=work_root / 'cache' / 'my-experts' /
                           'demo-pkg' / '1.0.0')
        _write(src_dir / 'packages' / '.mirror_backups' / '20261031' / 'x.md', 'bk')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr
        assert '安装态缺失' not in r.stdout, r.stdout + r.stderr
        assert '安装态多出' not in r.stdout, r.stdout + r.stderr

    def test_cache_side_ignored_dir_is_still_reported(self, work_root):
        """反向③：git 忽略只作用于**源码侧**。

        安装态若反过来多出这些目录 ⇒ 那是**真残留**（该清），
        必须继续报 cache_only，否则真残留永远清不掉。
        """
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        cache_dir = work_root / 'cache' / 'my-experts' / 'demo-pkg' / '1.0.0'
        self._make_git_repo(src_dir, ['packages/.mirror_backups/'],
                           cache_dir=cache_dir)
        _write(cache_dir / 'packages' / '.mirror_backups' / '20261031' / 'x.md', 'residue')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_DRIFT, r.stdout + r.stderr
        # 人读报告里的「安装态多出」= cache_only（真残留，该清）
        assert '安装态多出' in r.stdout, r.stdout + r.stderr
        assert 'packages/.mirror_backups/20261031/x.md' in r.stdout, r.stdout + r.stderr

    def test_real_drift_still_detected_with_git_repo(self, work_root):
        """正向：git 仓存在时，**真漂移**仍必须被抓到（不能被过滤吞掉）"""
        make_plugins_root(work_root, src_files={'a.py': 'NEW', 'b.py': 'x'},
                          cache_files={'a.py': 'OLD', 'b.py': 'x'})
        src_dir = work_root / 'marketplaces' / 'my-experts' / 'plugins' / 'demo-pkg'
        self._make_git_repo(src_dir, ['packages/.mirror_backups/'],
                           cache_dir=work_root / 'cache' / 'my-experts' /
                           'demo-pkg' / '1.0.0')
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_DRIFT, r.stdout + r.stderr
        assert '内容陈旧' in r.stdout, r.stdout + r.stderr

    def test_non_git_dir_degrades_gracefully(self, work_root):
        """降级：非 git 目录 ⇒ 只用固定 EXCLUDE_DIRS，不得崩、不得误判。"""
        make_plugins_root(work_root, src_files={'a.py': 'same'},
                          cache_files={'a.py': 'same'})
        r = run_cli('--plugins-root', str(work_root))
        assert r.returncode == isc.EXIT_CONSISTENT, r.stdout + r.stderr

    def test_git_ignored_paths_helper_returns_exact_paths(self, work_root):
        """单元级：_git_ignored_paths 返回**精确路径**，不含目录推断。"""
        pkg = work_root / 'pkg'
        self._make_git_repo(pkg, ['packages/.mirror_backups/', '*.bak_*'])
        _write(pkg / 'packages' / '.mirror_backups' / '20261031' / 'x.md', 'bk')
        _write(pkg / 'a.py.bak_t9', 'old')
        got = isc._git_ignored_paths(pkg)
        assert 'packages/.mirror_backups/20261031/x.md' in got
        assert 'a.py.bak_t9' in got
        # 不得出现「被推断出来的目录前缀」
        assert 'packages/' not in got
        assert 'scripts/' not in got
