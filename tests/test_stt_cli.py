#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stt.py 统一 CLI 入口测试（env / verify / gate design）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

STT = Path(__file__).resolve().parent.parent / "scripts" / "stt.py"
PKG = Path(__file__).resolve().parent.parent
# 放 /tmp 而非 repo 内 .pytest-tmp：repo 扫描类门禁（学科中立/静态契约）会扫到
# 测试产物里的绝对路径而误报；同时避免污染仓库。
_BASE = Path("/tmp/stt_test_stt_cli")


def _setup() -> Path:
    d = _BASE / f"run_{os.getpid()}_{len(os.listdir(_BASE)) if _BASE.exists() else 0}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def test_stt_env():
    r = subprocess.run([sys.executable, str(STT), "env"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "EXPERT_DIR" in r.stdout


def test_stt_verify_on_package():
    r = subprocess.run([sys.executable, str(STT), "verify", "--root", str(PKG)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_stt_gate_design_pass():
    b = _setup()
    d = b / "章节" / "ch01"
    os.makedirs(d, exist_ok=True)
    (d / "chapter_design.md").write_text(
        "# 设计\n\n## 知识域\nscope\n\n时数：3\n\n## 知识块锚点\nx\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(STT), "gate", "--phase", "design",
                       "--work-root", str(b), "--chapter", "ch01"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_stt_gate_design_fail():
    b = _setup()
    d = b / "章节" / "ch01"
    os.makedirs(d, exist_ok=True)
    (d / "chapter_design.md").write_text("# 设计\n\n无知识域声明\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(STT), "gate", "--phase", "design",
                       "--work-root", str(b), "--chapter", "ch01"],
                       capture_output=True, text=True)
    assert r.returncode == 1


def test_stt_unknown_phase():
    r = subprocess.run([sys.executable, str(STT), "gate", "--phase", "nope"],
                       capture_output=True, text=True)
    assert r.returncode == 2
