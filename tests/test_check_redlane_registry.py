#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_redlane_registry.py 红道登记 / 版本各处声明自洽 测试（正向 + 负向）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_redlane_registry.py"
# 放 /tmp 而非 repo 内 .pytest-tmp：repo 扫描类门禁（学科中立/静态契约）会扫到
# 测试产物里的绝对路径而误报；同时避免污染仓库。
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
    (d / "CHANGELOG.md").write_text(f"## [{version}] — 2026-11-10 test\n", encoding="utf-8")
    mk = d / ".claude-plugin" / "marketplace.json"
    (mk).write_text(
        '{"metadata": {"version": "%s"}, "plugins": [{"version": "%s"}]}\n' % (version, version),
        encoding="utf-8")
    # .codebuddy-plugin 在真实包中也存在，补全以贴近现实
    cbp = d / ".codebuddy-plugin"
    os.makedirs(cbp, exist_ok=True)
    (cbp / "plugin.json").write_text(f'{{ "name": "x", "version": "{version}" }}\n', encoding="utf-8")
    return d


def test_redlane_pass_on_fake_pkg():
    d = _make_pkg("2.13.0")
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "R6" in r.stdout and "PASS" in r.stdout


def test_redlane_fail_version_bumped_no_changelog():
    # 抬高真实权威版本（.claude-plugin/plugin.json 与 marketplace.json 同步到 9.9.9），
    # 但不登记 CHANGELOG → R1-R5 仍自洽、R6 必 FAIL（红道登记缺口）。
    d = _make_pkg("2.13.0")
    (d / ".claude-plugin" / "plugin.json").write_text('{ "name": "x", "version": "9.9.9" }\n', encoding="utf-8")
    (d / ".claude-plugin" / "marketplace.json").write_text(
        '{"metadata": {"version": "9.9.9"}, "plugins": [{"version": "9.9.9"}]}\n', encoding="utf-8")
    (d / ".codebuddy-plugin" / "plugin.json").write_text('{ "name": "x", "version": "9.9.9" }\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "R6" in r.stdout and "FAIL" in r.stdout
    assert "未登记" in r.stdout
