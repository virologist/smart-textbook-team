#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_gate_retrieval.py 门禁 2 linter 测试（正向 + 负向）

注：本环境 pytest 自带 tmp_path 被沙箱 broker 拦截，故自建临时目录（os.makedirs 可用）。
"""
from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_gate_retrieval.py"
# 放 /tmp 而非 repo 内 .pytest-tmp：repo 扫描类门禁（学科中立/静态契约）会扫到
# 测试产物里的绝对路径而误报；同时避免污染仓库。
_BASE = Path("/tmp/stt_test_gate_retrieval")
DESIGN = "# 章节设计\n\n## 知识域\nscope\n\n时数：2\n\n## 知识块锚点\nx\n"


def _setup() -> Path:
    d = _BASE / f"run_{os.getpid()}_{len(os.listdir(_BASE)) if _BASE.exists() else 0}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def _run(retrieval_text: str, base: Path) -> subprocess.CompletedProcess:
    rd = base / "retrieval"
    os.makedirs(rd, exist_ok=True)
    (rd / "RETRIEVED.md").write_text(retrieval_text, encoding="utf-8")
    (base / "chapter_design.md").write_text(DESIGN, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), "--design", str(base / "chapter_design.md"),
                          "--retrieval-dir", str(rd)], capture_output=True, text=True)


GOOD = """# 检索产物
AIV H5N1 在 2023 年发病率上升 [实]。
2022 年病死率为 30% [实]。
2021 年免疫程序覆盖率为 80% [估]。
"""


def test_gate_retrieval_pass():
    b = _setup()
    r = _run(GOOD, b)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_gate_retrieval_fail_low_coverage():
    b = _setup()
    bad = ("AIV H5N1 发病率很高。\n"
           "2022 年病死率约三成。\n")
    r = _run(bad, b)
    assert r.returncode == 1
    assert "G2.1" in r.stdout and "FAIL" in r.stdout


def test_gate_retrieval_fail_old_timeline():
    b = _setup()
    bad = ("1995 年发病率上升 [实]。\n"
           "1988 年病死率为 30% [实]。\n")
    r = _run(bad, b)
    assert r.returncode == 1
    assert "G2.2" in r.stdout


def test_gate_retrieval_warn_conflict():
    b = _setup()
    text = ("2023 年发病率上升 [实]。\n"
            "研究 A 与 研究 B 结论冲突 [待核实]。\n")
    r = _run(text, b)
    assert "G2.3" in r.stdout and "WARN" in r.stdout


def test_gate_retrieval_missing_dir():
    b = _setup()
    r = subprocess.run([sys.executable, str(SCRIPT), "--design", str(b / "d.md"),
                       "--retrieval-dir", str(b / "nope")],
                      capture_output=True, text=True)
    assert r.returncode == 2
