#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_m_batch_gates.py — ★M 批次门禁回归（v2.11.3/v2.11.4）

覆盖：M4 notes 机械落点（BOOK_ 域/章域 落盘·反查·清空幂等）
     + M5 跨文件引用一致性（正向 0 死链 + 负向改节名必拦）
退出码：0 全过 | 1 有失败项
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKS: list[tuple[str, bool]] = []


def ck(name: str, ok: bool) -> None:
    CHECKS.append((name, ok))
    print(f"  {'✓' if ok else '✗'} [{name}]")


def _progress_cli(wr: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "progress.py"),
         "--work-root", str(wr), *args], capture_output=True, text=True)


def t_m4_notes() -> None:
    """M4：--notes 落盘 → show 反查 → 空串清空（幂等）。"""
    with tempfile.TemporaryDirectory(prefix="stt-m4-") as td:
        wr = Path(td)
        r = _progress_cli(wr, "book", "init", "--textbook", "T",
                          "--chapters", "ch01", "--audience", "职业本科")
        ck("M4.0 book init", r.returncode == 0)
        r = _progress_cli(wr, "init", "--chapter", "ch01",
                          "--textbook", "T", "--audience", "职业本科")
        ck("M4.0b 章 init", r.returncode == 0)
        r = _progress_cli(wr, "update", "--phase", "CHAPTER_SCHEDULE",
                          "--status", "DONE", "--summary", "样章通过",
                          "--notes", "sample-chapter-approved")
        ck("M4.1 notes 落盘 exit 0", r.returncode == 0)
        pf = wr / "运行态" / "progress.md"
        text = pf.read_text(encoding="utf-8")
        ck("M4.2 notes 行存在",
           "- notes[CHAPTER_SCHEDULE]: sample-chapter-approved" in text)
        r = _progress_cli(wr, "show")
        ck("M4.3 show 反查", "sample-chapter-approved" in r.stdout)
        r = _progress_cli(wr, "update", "--phase", "CHAPTER_SCHEDULE",
                          "--status", "IN_PROGRESS", "--summary", "重开", "--notes", "")
        ck("M4.4 空串清空 exit 0", r.returncode == 0)
        ck("M4.5 清空后无残留",
           "notes[CHAPTER_SCHEDULE]" not in pf.read_text(encoding="utf-8"))


def t_m5_cross_refs() -> None:
    """M5：包根 0 死链 + 改节名负向必拦（真改+还原）。"""
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_cross_refs.py"),
                        "--root", str(REPO)], capture_output=True, text=True)
    ck("M5.1 正向 0 死链", r.returncode == 0)
    target = REPO / "skills" / "textbook-pipeline-workflow" / "SKILL.md"
    orig = target.read_text(encoding="utf-8")
    try:
        target.write_text(orig.replace(
            "## 节级并行与恢复协议（B4，2026-11-04）",
            "## 节级并行与恢复协议V2（B4，2026-11-04）"), encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(REPO / "scripts" / "check_cross_refs.py"),
                             "--root", str(REPO)], capture_output=True, text=True)
        ck("M5.2 负向改节名必拦", r2.returncode == 1)
    finally:
        target.write_text(orig, encoding="utf-8")
    r3 = subprocess.run([sys.executable, str(REPO / "scripts" / "check_cross_refs.py"),
                         "--root", str(REPO)], capture_output=True, text=True)
    ck("M5.3 还原后复绿", r3.returncode == 0)


def main() -> int:
    print("=" * 62)
    print("★M 批次门禁回归（M4 notes + M5 引用一致性）")
    print("=" * 62)
    t_m4_notes()
    t_m5_cross_refs()
    n = sum(1 for _, ok in CHECKS if not ok)
    print("-" * 62)
    print(f"检查项 {len(CHECKS)} | 通过 {len(CHECKS) - n} | 失败 {n}")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
