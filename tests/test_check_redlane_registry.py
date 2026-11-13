#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_redlane_registry.py 红道登记 / 版本各处声明自洽 测试（正向 + 负向）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
临时产物放 /tmp，避免污染 repo 扫描类门禁（学科中立 / 静态契约）。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_redlane_registry.py"
_BASE = Path("/tmp/stt_test_redlane")


def _make_pkg(version: str) -> Path:
    d = _BASE / f"pkg_{os.getpid()}_{len(os.listdir(_BASE)) if _BASE.exists() else 0}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    # 真实包布局：plugin.json 在 .claude-plugin/ 下，而非包根
    cp = d / ".claude-plugin"
    os.makedirs(cp, exist_ok=True)
    (cp / "plugin.json").write_text(f'{{ "name": "x", "version": "{version}" }}\n', encoding="utf-8")
    (d / "README.md").write_text(f"> 版本 {version} | 2026-11-10 | 作者 TZUVet\n", encoding="utf-8")
    (d / "install.sh").write_text(f'VERSION="{version}"\n', encoding="utf-8")
    # Windows 安装器同为版本声明源（审计补入；此前长期停在 2.8.0 且不在检查器视野内）
    (d / "install.ps1").write_text(f"$VERSION = '{version}'\n", encoding="utf-8")
    (d / "CHANGELOG.md").write_text(f"## [{version}] — 2026-11-10 test\n", encoding="utf-8")
    mk = d / ".claude-plugin" / "marketplace.json"
    mk.write_text(
        '{"metadata": {"version": "%s"}, "plugins": [{"version": "%s"}]}\n' % (version, version),
        encoding="utf-8")
    cbp = d / ".codebuddy-plugin"
    os.makedirs(cbp, exist_ok=True)
    (cbp / "plugin.json").write_text(f'{{ "name": "x", "version": "{version}" }}\n', encoding="utf-8")
    return d


def _bump_all(d: Path, v: str) -> None:
    """全部版本声明源同步抬到 v（CHANGELOG 不动）——用于隔离证明 R6 独立生效。"""
    (d / ".claude-plugin" / "plugin.json").write_text(
        f'{{ "name": "x", "version": "{v}" }}\n', encoding="utf-8")
    (d / ".codebuddy-plugin" / "plugin.json").write_text(
        f'{{ "name": "x", "version": "{v}" }}\n', encoding="utf-8")
    (d / ".claude-plugin" / "marketplace.json").write_text(
        '{"metadata": {"version": "%s"}, "plugins": [{"version": "%s"}]}\n' % (v, v), encoding="utf-8")
    (d / "README.md").write_text(f"> 版本 {v} | 2026-11-10 | 作者 TZUVet\n", encoding="utf-8")
    (d / "install.sh").write_text(f'VERSION="{v}"\n', encoding="utf-8")
    (d / "install.ps1").write_text(f"$VERSION = '{v}'\n", encoding="utf-8")


def _run(d: Path):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(d)],
                          capture_output=True, text=True)


def test_redlane_pass_on_fake_pkg():
    r = _run(_make_pkg("2.13.0"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "R6" in r.stdout and "PASS" in r.stdout
    assert "install.ps1" in r.stdout, "新版本源必须确实被纳入检查"


def test_redlane_fail_version_bumped_no_changelog():
    """全部版本源同步抬升但不登记 CHANGELOG → 仅 R6 FAIL，R1-R5 必须仍 PASS。"""
    d = _make_pkg("2.13.0")
    _bump_all(d, "9.9.9")
    r = _run(d)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[PASS] R1-R5" in r.stdout, "R1-R5 应仍自洽，否则本用例无法隔离证明 R6 生效"
    assert "R6" in r.stdout and "FAIL" in r.stdout
    assert "未登记" in r.stdout


def test_redlane_empty_root_exits_2_not_fake_pass():
    """空目录：判据没跑必须 exit 2 显式报错，绝不能打印 [PASS] R1-R5（空集恒真回归）。"""
    d = _BASE / f"empty_{os.getpid()}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    r = _run(d)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[PASS]" not in r.stdout, "空集恒真假绿复发"
    assert "缺失" in (r.stdout + r.stderr)


def test_redlane_missing_core_exits_2():
    d = _make_pkg("2.13.0")
    (d / "README.md").unlink()
    r = _run(d)
    assert r.returncode == 2
    assert "README.md" in (r.stdout + r.stderr)


def test_redlane_install_ps1_drift_is_caught():
    """只漂移 Windows 安装器版本 → R1-R5 必须 FAIL（新增门禁的正向证据）。"""
    d = _make_pkg("2.13.0")
    (d / "install.ps1").write_text("$VERSION = '2.8.0'\n", encoding="utf-8")
    r = _run(d)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL] R1-R5" in r.stdout
    assert "install.ps1" in r.stdout
