#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_gate_design.py 门禁 1 linter 测试（正向 + 负向）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_gate_design.py"
# 放 /tmp 而非 repo 内 .pytest-tmp：repo 扫描类门禁（学科中立/静态契约）会扫到
# 测试产物里的绝对路径而误报；同时避免污染仓库。
_BASE = Path("/tmp/stt_test_gate_design")


def _setup() -> Path:
    d = _BASE / f"run_{os.getpid()}_{len(os.listdir(_BASE)) if _BASE.exists() else 0}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def _run(text: str, base: Path) -> subprocess.CompletedProcess:
    p = base / "chapter_design.md"
    p.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), "--design", str(p)],
                          capture_output=True, text=True)


GOOD = """# 章节设计 ch01

## 知识域（scope）
禽流感病原学、流行病学、防控技术

## 教学时数
时数：4

## 知识块锚点
| 知识块 | 要点 |
| --- | --- |
| 病原 | AIV 分型 |
"""


def test_gate_design_pass():
    b = _setup()
    r = _run(GOOD, b)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_gate_design_fail_missing_scope():
    b = _setup()
    bad = GOOD.replace("## 知识域（scope）\n禽流感病原学、流行病学、防控技术\n", "")
    r = _run(bad, b)
    assert r.returncode == 1
    assert "G1.1" in r.stdout and "FAIL" in r.stdout


def test_gate_design_fail_hours_zero():
    b = _setup()
    bad = GOOD.replace("时数：4", "时数：0")
    r = _run(bad, b)
    assert r.returncode == 1
    assert "G1.2" in r.stdout


def test_gate_design_fail_no_anchor():
    b = _setup()
    bad = GOOD.replace("## 知识块锚点\n| 知识块 | 要点 |\n| --- | --- |\n| 病原 | AIV 分型 |\n", "")
    r = _run(bad, b)
    assert r.returncode == 1
    assert "G1.3" in r.stdout


def test_gate_design_missing_file():
    """反向例：输入缺失须 exit 2 且显式报「输入缺失」，不得伪装成「0 项未通过」。"""
    b = _setup()
    r = subprocess.run([sys.executable, str(SCRIPT), "--design", str(b / "nope.md")],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "输入缺失" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "0 项未通过" not in r.stdout, "判据没跑却被文字伪装成全过（静默吞错）"
    assert "全部通过" not in r.stdout
