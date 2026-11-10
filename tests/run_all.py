#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py — 本地全量回归统一入口（★M7 v2.11.4）

CI harness-gate 与本地回归的同一扇门（判据同源，防「本地绿 CI 红」再现）：
  ① pytest tests/ 全量（独立 --basetemp，防平台 shim tmpdir 冲突）
  ② 静态契约评测 tests/test_smart_textbook_team.py（main 式，282 计分项）
  ③ 相位/文档/中立/挂载/引用/用例/frontmatter 七道机械门禁

用法：python3 tests/run_all.py [--fast]   # --fast 跳过 pytest（仅七门禁+契约）
退出码：0 全绿 | 1 任一失败
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STEPS = [
    ("相位一致", [sys.executable, "scripts/check_phase_consistency.py", "--root", str(REPO)]),
    ("文档一致", [sys.executable, "scripts/check_doc_consistency.py", "--root", str(REPO)]),
    ("学科中立", [sys.executable, "scripts/check_domain_neutral.py", "--root", str(REPO)]),
    ("挂载校验", [sys.executable, "scripts/check_external_skills.py", "--work-root", str(REPO)]),
    ("引用一致", [sys.executable, "scripts/check_cross_refs.py", "--root", str(REPO)]),
    ("用例契约", [sys.executable, "scripts/check_test_prompts.py", "--root", str(REPO)]),
    ("frontmatter", [sys.executable, "scripts/check_skill_frontmatter.py", "--root", str(REPO)]),
    # M 门禁（跨平台清单同步 33 项）。v2.14.0 实测教训：本文件头注释自称「防本地绿
    # CI 红再现」，但漏收 test_manifest_sync.py，结果 team-lead.md 增容后 README 的
    # KB 声明漂移，本地 run_all 全绿、CI M10c 红——正是本文件承诺要防的事故。
    ("清单同步", [sys.executable, "tests/test_manifest_sync.py"]),
    ("静态契约", [sys.executable, "tests/test_smart_textbook_team.py"]),
]


def run(name: str, cmd: list[str]) -> bool:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    tail = (r.stdout or r.stderr).strip().splitlines()
    last = tail[-1] if tail else ""
    print(f"  {'✓' if r.returncode == 0 else '✗'} [{name}] rc={r.returncode} {last[:70]}")
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="跳过 pytest 全量")
    args = ap.parse_args()
    print("=" * 62)
    print("本地全量回归（判据同源 CI harness-gate）")
    print("=" * 62)
    ok = True
    for name, cmd in STEPS:
        ok &= run(name, cmd)
    if not args.fast:
        with tempfile.TemporaryDirectory(prefix="stt-runall-") as bt:
            r = subprocess.run([sys.executable, "-m", "pytest", str(REPO / "tests"),
                                "-q", "--basetemp", bt, "--disable-warnings"],
                               capture_output=True, text=True)
            tail = (r.stdout or "").strip().splitlines()
            print(f"  {'✓' if r.returncode == 0 else '✗'} [pytest 全量] {tail[-1] if tail else ''}")
            ok &= r.returncode == 0
    print("-" * 62)
    print("全绿" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
