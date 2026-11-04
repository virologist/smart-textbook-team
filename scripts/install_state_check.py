#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_state_check.py — 安装态（cache）与源码态（marketplaces）一致性检查器

问题背景
========
诊断报告 Q1（严重度：高，影响面：协议正确性）：

    `my-experts` / `experts` 两个 marketplace 在
    `known_marketplaces.json`（插件根下）里都是
    `type: directory` + `autoUpdate: false` —— **目录型 marketplace，
    宿主不会自动把源码同步到安装态**。

    而 `plugins/installed_plugins.json` 里全部 239 条 `installPath`
    都指向 `plugins/cache/{mp}/{pkg}/{ver}/` —— 宿主运行时**实际加载
    的是 cache，不是源码**。

    ⇒ 源码改了、commit 了、push 了，专家团跑的**仍是旧代码**。

更隐蔽的一层：**版本号相同也会漏**。
    宿主按 `plugin.json` 的 `version` 判定「是否需要更新」。
    若源码改内容但没升版本号 → 宿主判定「无需更新」→ cache 永远停在旧快照。

    本轮清理实测（2026-11-04）：smart-textbook-team 的
    cache 2.5.0 与源码 2.5.0 **版本号相同**，但内容差 20 个文件（缺失）
    + 32 个文件（陈旧）→ 专家团跑的是缺
    `scheduler.py` / `contract_check.py` / `merge_sections.py` 的旧代码。

    ⇒ **只比版本号不够，必须比内容。**

本脚本做什么
============
对每个「源码包 ↔ 安装态目录」做**内容级 sha256 全量比对**：

  · `SAME`           内容完全一致
  · `SRC_ONLY`       仅源码有（安装态**缺文件**）→ 运行时加载不到
  · `CACHE_ONLY`     仅安装态有（源码已删除）→ 可能是残留垃圾
  · `DIFF`           两边都有但内容不同 → 运行时跑的是旧代码

**只读检查器**：本脚本**不修改、不删除、不同步**安装态任何文件。
发现漂移只**报告**并给出修复提示；同步是独立动作，需显式授权。

排除元数据目录（这些不是包内容）：
    .git / .in_use（宿主运行时锁）/ .pytest_cache / __pycache__ / .DS_Store

退出码
======
  0  CONSISTENT   全部一致
  1  DRIFT        存在漂移（至少一个包不一致）
  2  INPUT_ERROR  参数或环境错误

用法
====
  # 检查 my-experts 下所有包（插件根自动探测：$WORKBUDDY_PLUGINS_ROOT → 宿主安装根候选）
  python3 scripts/install_state_check.py

  # 显式指定插件根
  python3 scripts/install_state_check.py --plugins-root <插件根>

  # 只检查某几个包
  python3 scripts/install_state_check.py --pkg smart-textbook-team --pkg viral-evo-lab

  # 限定 marketplace
  python3 scripts/install_state_check.py --marketplace my-experts

  # 机器可读
  python3 scripts/install_state_check.py --json

  # 只看自上次快照以来的变化（需先 --snapshot 存基线）
  python3 scripts/install_state_check.py --snapshot 运行态/install-state.json
  python3 scripts/install_state_check.py --snapshot 运行态/install-state.json --changed-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# 排除的目录名（元数据，不是包内容）
EXCLUDE_DIRS = {'.git', '.in_use', '.pytest_cache', '__pycache__', '.DS_Store'}

# 排除的文件名（元数据，不是包内容）
# .downloaded_at —— 宿主写入的「本次下载时间戳」。它**只存在于安装态**，
#   内容随每次安装变化，与包内容无关。若不排除：
#   ① 每个包都会恒定报「内容陈旧 1 项」→ 真漂移被噪声淹没；
#   ② cache_only 里全是它 → 误报「源码已删」。
#   ⇒ 一律排除。
EXCLUDE_FILES = {'.downloaded_at'}

# 默认 marketplace 目录名（可在 known_marketplaces.json 里查到真实 path）
DEFAULT_MARKETPLACES = ('my-experts', 'experts')

EXIT_CONSISTENT = 0
EXIT_DRIFT = 1
EXIT_INPUT_ERROR = 2

# 宿主安装根候选（WorkBuddy 落 .workbuddy，CodeBuddy 落 .codebuddy；
# 新机常只装后者——C-23 实测：写死 .workbuddy → 新机首跑即空路径）。
# 顺序：环境变量优先 → 候选根兜底。
INSTALL_ROOT_ENV = 'WORKBUDDY_PLUGINS_ROOT'
INSTALL_ROOT_CANDIDATES = ('.workbuddy', '.codebuddy')

# 一次安装态快照的文件指纹缓存：{path: sha256}
_FILE_HASH_CACHE: dict[str, str] = {}


def _sha256(path: Path) -> str:
    """文件 sha256（带缓存，避免同一文件算两次）。"""
    key = str(path)
    cached = _FILE_HASH_CACHE.get(key)
    if cached is not None:
        return cached
    h = hashlib.sha256()
    try:
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
    except OSError:
        h = hashlib.sha256()
    digest = h.hexdigest()
    _FILE_HASH_CACHE[key] = digest
    return digest


def collect_files(root: Path) -> dict[str, str]:
    """遍历目录 → {相对路径: sha256}，排除元数据目录。"""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in EXCLUDE_DIRS]
        for name in fn:
            if name in EXCLUDE_DIRS or name in EXCLUDE_FILES:
                continue
            p = Path(dp) / name
            try:
                rel = str(p.relative_to(root)).replace(os.sep, '/')
            except ValueError:
                continue
            out[rel] = _sha256(p)
    return out


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def read_installed_map(plugins_root: Path) -> dict[str, dict]:
    """从 installed_plugins.json 提取 {pkg_name: {installPath, version}}。

    只取 my-experts / experts 两个目录型 marketplace 的条目
    （官方 marketplace 的 cache 由宿主自己管，不需要查）。
    """
    data = _read_json(plugins_root / 'installed_plugins.json')
    out: dict[str, dict] = {}
    for key, val in (data.get('plugins') or {}).items():
        entries = val if isinstance(val, list) else [val]
        for e in entries:
            if not isinstance(e, dict):
                continue
            ip = e.get('installPath')
            if not ip:
                continue
            for mp in DEFAULT_MARKETPLACES:
                marker = f'/{mp}/'
                if marker not in ip:
                    continue
                pkg = ip.split(marker, 1)[1].split('/')[0]
                out[f'{mp}/{pkg}'] = {
                    'installPath': ip,
                    'version': e.get('version'),
                    'key': key,
                }
    return out


def find_source_dir(plugins_root: Path, mp: str, pkg: str) -> Path | None:
    """定位源码目录。

    优先读 known_marketplaces.json 里登记的真实 path（directory 型
    marketplace 的 path 未必是 `marketplaces/{mp}`）；读不到则回落默认布局。
    """
    km = _read_json(plugins_root / 'known_marketplaces.json')
    mps = km.get('marketplaces') or km
    entry = mps.get(mp) if isinstance(mps, dict) else None
    if isinstance(entry, dict):
        src = entry.get('source')
        path = src.get('path') if isinstance(src, dict) else None
        if path:
            cand = Path(path).expanduser() / 'plugins' / pkg
            if cand.is_dir():
                return cand
    cand = plugins_root / 'marketplaces' / mp / 'plugins' / pkg
    return cand if cand.is_dir() else None


def compare_pair(src: Path, cache: Path) -> dict:
    """比对单个包的源码态与安装态。"""
    s = collect_files(src)
    c = collect_files(cache)
    src_only = sorted(set(s) - set(c))
    cache_only = sorted(set(c) - set(s))
    diff = sorted(k for k in set(s) & set(c) if s[k] != c[k])
    same = len(set(s) & set(c)) - len(diff)
    consistent = not (src_only or cache_only or diff)
    return {
        'src_root': str(src),
        'cache_root': str(cache),
        'src_file_count': len(s),
        'cache_file_count': len(c),
        'same_count': same,
        'src_only': src_only,
        'cache_only': cache_only,
        'diff': diff,
        'consistent': consistent,
        'status': 'SAME' if consistent else 'DRIFT',
    }


def build_report(plugins_root: Path, marketplaces: tuple[str, ...],
                 only_pkgs: list[str] | None) -> dict:
    """生成全量一致性报告。"""
    installed = read_installed_map(plugins_root)
    packages: list[dict] = []
    for key, info in sorted(installed.items()):
        mp, pkg = key.split('/', 1)
        if mp not in marketplaces:
            continue
        if only_pkgs and pkg not in only_pkgs:
            continue
        src = find_source_dir(plugins_root, mp, pkg)
        cache = Path(info['installPath']).expanduser()
        if src is None:
            packages.append({
                'marketplace': mp, 'package': pkg,
                'installPath': info['installPath'],
                'version': info['version'],
                'status': 'SOURCE_MISSING',
                'consistent': False,
                'detail': '源码目录不存在（marketplace 已移除该包？安装态成孤儿）',
            })
            continue
        if not cache.is_dir():
            packages.append({
                'marketplace': mp, 'package': pkg,
                'installPath': info['installPath'],
                'version': info['version'],
                'status': 'CACHE_MISSING',
                'consistent': False,
                'detail': '安装态目录不存在（宿主可能未真正安装）',
            })
            continue
        r = compare_pair(src, cache)
        r.update({'marketplace': mp, 'package': pkg,
                  'version': info['version'],
                  'installPath': info['installPath']})
        packages.append(r)
    drift = [p for p in packages if not p.get('consistent')]
    return {
        'plugins_root': str(plugins_root),
        'total': len(packages),
        'consistent': len(packages) - len(drift),
        'drift': len(drift),
        'status': 'CONSISTENT' if not drift else 'DRIFT',
        'packages': packages,
    }


def render(report: dict, changed_only: bool) -> str:
    """人读报告。"""
    lines = []
    lines.append(f"安装态一致性检查：{report['plugins_root']}")
    lines.append(f"共 {report['total']} 个包，一致 {report['consistent']}，"
                 f"漂移 {report['drift']} → **{report['status']}**")
    lines.append('')
    for p in report['packages']:
        if changed_only and p.get('consistent'):
            continue
        mp, pkg = p['marketplace'], p['package']
        if p['status'] in ('SOURCE_MISSING', 'CACHE_MISSING'):
            lines.append(f"✗ {mp}/{pkg}  [{p['status']}]  {p.get('detail','')}")
            lines.append(f"    installPath: {p['installPath']}")
            continue
        if p['consistent']:
            lines.append(f"✓ {mp}/{pkg}  v{p.get('version','?')}  "
                         f"（{p['src_file_count']} 文件全一致）")
            continue
        lines.append(f"✗ {mp}/{pkg}  v{p.get('version','?')}  **漂移**")
        lines.append(f"    源码 {p['src_file_count']} 文件 / 安装态 "
                     f"{p['cache_file_count']} 文件")
        if p['src_only']:
            lines.append(f"    安装态缺失 {len(p['src_only'])} 项"
                         f"（运行时加载不到）：")
            for x in p['src_only'][:12]:
                lines.append(f'       + {x}')
            if len(p['src_only']) > 12:
                lines.append(f'       … 另有 {len(p["src_only"]) - 12} 项')
        if p['diff']:
            lines.append(f"    内容陈旧 {len(p['diff'])} 项"
                         f"（运行时跑的是旧代码）：")
            for x in p['diff'][:12]:
                lines.append(f'       ~ {x}')
            if len(p['diff']) > 12:
                lines.append(f'       … 另有 {len(p["diff"]) - 12} 项')
        if p['cache_only']:
            lines.append(f"    安装态多出 {len(p['cache_only'])} 项"
                         f"（源码已删，可能是残留）：")
            for x in p['cache_only'][:8]:
                lines.append(f'       - {x}')
            if len(p['cache_only']) > 8:
                lines.append(f'       … 另有 {len(p["cache_only"]) - 8} 项')
    if report['drift']:
        lines.append('')
        lines.append('修复提示（本脚本只读，不自动改文件）：')
        lines.append('  1) 先确认源码侧是权威版本（git log / tag）')
        lines.append('  2) 同步安装态：把源码内容复制到 installPath，'
                     '保留 .in_use/ 与 .downloaded_at')
        lines.append('  3) 同步后重跑本脚本确认 → 0 漂移')
        lines.append('  ⚠ directory 型 marketplace（autoUpdate:false）'
                     '不会自动同步，须每次升版后手动执行')
    return '\n'.join(lines)


def snapshot_path(report: dict, plugins_root: Path) -> Path:
    return plugins_root / 'install-state.json'


def save_snapshot(report: dict, path: Path) -> None:
    """存基线快照（供 --changed-only 对比）。"""
    snap = {
        'ts': _now_iso(),
        'plugins_root': report['plugins_root'],
        'packages': {
            f"{p['marketplace']}/{p['package']}": {
                'status': p.get('status'),
                'src_only': p.get('src_only', []),
                'diff': p.get('diff', []),
                'cache_only': p.get('cache_only', []),
            } for p in report['packages']
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                    encoding='utf-8')


def default_plugins_root() -> Path | None:
    """默认插件根：环境变量优先 → 宿主安装根候选兜底。

    刻意**不写死**任何宿主点目录（宿主各产品各有自己的点目录名）——
    ① check_domain_neutral 门禁禁止硬编码宿主点目录；
    ② 多机/非默认安装位（.codebuddy）必须可用。
    """
    env = os.environ.get(INSTALL_ROOT_ENV)
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    home = Path.home()
    for name in INSTALL_ROOT_CANDIDATES:
        p = home / name / 'plugins'
        if p.is_dir():
            return p.resolve()
    return None


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def diff_against_snapshot(report: dict, snap_path: Path) -> list[dict]:
    """与快照对比，只报变化过的包。"""
    snap = _read_json(snap_path)
    if not snap:
        return []
    old = snap.get('packages') or {}
    changed = []
    for p in report['packages']:
        key = f"{p['marketplace']}/{p['package']}"
        o = old.get(key)
        cur = {
            'status': p.get('status'),
            'src_only': p.get('src_only', []),
            'diff': p.get('diff', []),
            'cache_only': p.get('cache_only', []),
        }
        if o is None:
            changed.append({'package': key, 'change': 'NEW',
                            'detail': '快照中无此包（新增安装）'})
        elif o != cur:
            changed.append({'package': key, 'change': 'MODIFIED',
                            'detail': '漂移状态较上次快照发生变化',
                            'before': o.get('status'),
                            'after': cur.get('status')})
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(
        description='install_state_check — 安装态(cache)与源码态(marketplaces)内容一致性检查（只读）')
    ap.add_argument('--plugins-root', default=None,
                    help='插件根目录（默认自动探测：$WORKBUDDY_PLUGINS_ROOT → 宿主安装根候选）')
    ap.add_argument('--marketplace', action='append', default=None,
                    choices=list(DEFAULT_MARKETPLACES),
                    help='限定 marketplace（可重复；默认 my-experts + experts）')
    ap.add_argument('--pkg', action='append', default=None,
                    help='只检查指定包（可重复）')
    ap.add_argument('--snapshot', default=None,
                    help='快照文件路径：给定则读取旧快照做变化对比，'
                         '并在其上更新写入')
    ap.add_argument('--changed-only', action='store_true',
                    help='只输出与快照相比发生变化的包')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    args = ap.parse_args()

    plugins_root = (Path(args.plugins_root).expanduser().resolve()
                    if args.plugins_root else default_plugins_root())
    if plugins_root is None:
        print(f'ERROR  未找到插件根：请显式传 --plugins-root，'
              f'或设置环境变量 {INSTALL_ROOT_ENV}', file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not plugins_root.is_dir():
        print(f'ERROR  插件根不存在: {plugins_root}', file=sys.stderr)
        return EXIT_INPUT_ERROR

    marketplaces = tuple(args.marketplace) if args.marketplace else DEFAULT_MARKETPLACES
    report = build_report(plugins_root, marketplaces, args.pkg)

    snap = Path(args.snapshot).expanduser() if args.snapshot else None
    changed: list[dict] = []
    if snap:
        if snap.is_file():
            changed = diff_against_snapshot(report, snap)
        save_snapshot(report, snap)

    if args.json:
        out = dict(report)
        out['changed'] = changed
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.changed_only))
        if changed:
            print('')
            print('与上次快照的变化：')
            for c in changed:
                print(f"  [{c['change']}] {c['package']}  {c['detail']}")

    return EXIT_CONSISTENT if report['status'] == 'CONSISTENT' else EXIT_DRIFT


if __name__ == '__main__':
    sys.exit(main())
