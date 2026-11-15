#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_declaration.py — check_declaration.py 反向例（A4b，2026-11-16）

病灶：checked==0（扫描声明 0 条）时脚本仍输出 TECH_DEBT=0 并 exit 0——
「判据没跑算通过」的假绿，与 check_phase_consistency「扫到 0 处拒绝判 PASS」
口径冲突。修复后：checked==0 显式 exit 2；真实包 checked>0 仍 exit 0。

运行：python3 -m pytest tests/test_check_declaration.py -q
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PKG_ROOT / 'scripts' / 'check_declaration.py'


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), '--root', str(root)],
                          capture_output=True, text=True)


def test_check_declaration_zero_scanned_rejects_pass():
    """空包根 → checked==0 → 必须 exit 2，不得以 TECH_DEBT=0 放行。"""
    d = tempfile.mkdtemp(prefix='stt_decl_zero_')
    try:
        r = _run(Path(d))
        assert r.returncode == 2, f"checked==0 必须 exit 2: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        assert '扫描声明 0 条' in r.stderr, r.stderr
        assert 'TECH_DEBT=0' not in r.stdout, "不得以 TECH_DEBT=0 伪装为通过"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_check_declaration_real_package_still_passes():
    """真实包（checked>0）行为不变：exit 0 且 TECH_DEBT=0。"""
    r = _run(PKG_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'TECH_DEBT=0' in r.stdout


if __name__ == '__main__':
    sys.exit(subprocess.run([sys.executable, '-m', 'pytest', __file__, '-q']).returncode)
