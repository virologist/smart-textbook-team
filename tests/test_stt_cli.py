#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stt.py 统一 CLI 入口测试（env / verify / gate / 参数契约）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
临时产物放 /tmp，避免污染 repo 扫描类门禁（学科中立 / 静态契约）。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

STT = Path(__file__).resolve().parent.parent / "scripts" / "stt.py"
PKG = Path(__file__).resolve().parent.parent
_BASE = Path("/tmp/stt_test_stt_cli")

_CONSISTENCY_SCRIPTS = (
    "check_doc_consistency.py",
    "check_phase_consistency.py",
    "check_skill_frontmatter.py",
    "check_redlane_registry.py",
)


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
    # 不只信 rc：断言四个检查器都确实被执行（防「空跑也算通过」）
    for s in _CONSISTENCY_SCRIPTS:
        assert s in r.stdout, f"verify 未执行 {s}"


def test_stt_gate_consistency_matches_verify():
    """consistency 与 verify 收敛到同一执行体后，两者检查器集合必须一致。"""
    a = subprocess.run([sys.executable, str(STT), "verify", "--root", str(PKG)],
                       capture_output=True, text=True)
    b = subprocess.run([sys.executable, str(STT), "gate", "--phase", "consistency", "--root", str(PKG)],
                       capture_output=True, text=True)
    assert a.returncode == b.returncode == 0, a.stdout + b.stdout
    for s in _CONSISTENCY_SCRIPTS:
        assert s in a.stdout and s in b.stdout


def test_stt_gate_help_exposes_new_flags():
    r = subprocess.run([sys.executable, str(STT), "gate", "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "--no-strict" in r.stdout
    assert "--affected-from" in r.stdout


def test_stt_gate_cross_accepts_affected_from():
    """team-lead 文档示例用的 --affected-from 必须是 CLI 认识的参数。"""
    b = _setup()
    r = subprocess.run([sys.executable, str(STT), "gate", "--phase", "cross",
                       "--work-root", str(b), "--affected-from", "ch01"],
                       capture_output=True, text=True)
    assert "unrecognized arguments" not in (r.stdout + r.stderr), r.stdout + r.stderr
    assert r.returncode != 2, "参数解析失败（exit 2）"


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
