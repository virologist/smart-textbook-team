#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py — 本地全量回归统一入口

本地覆盖：① pytest tests/ 全量（独立 --basetemp，并校验「收集数 == passed+skipped」，
          防漏收新测试却报全绿）② 静态契约评测（282 计分项）
          ③ 相位/文档/中立/挂载/引用/用例/frontmatter/清单同步/红道登记 十道机械门禁

判据集说明（诚实声明）：CI harness-gate.yml 另有大量端到端 step，且只单跑 2 个
pytest 文件；本文件与 CI 判据集**不完全同源**（已知待收敛项）。本文件全绿不等于
CI 全绿，反之亦然；发布前仍须看远端 CI 结论。

用法：python3 tests/run_all.py [--fast]   # --fast 跳过 pytest（仅十门禁+契约）
退出码：0 全绿 | 1 任一失败
"""
from __future__ import annotations

import argparse
import re
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
    # 红道登记 R1-R6：此前仅 stt.py verify 间接调用，本地 STEP 与 CI 都无直接门禁
    ("红道登记", [sys.executable, "scripts/check_redlane_registry.py", "--root", str(REPO)]),
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
    print("本地全量回归（10 机械门禁 + 静态契约 + pytest 全量；判据集与 CI 不完全同源）")
    print("=" * 62)
    ok = True
    for name, cmd in STEPS:
        ok &= run(name, cmd)
    if not args.fast:
        with tempfile.TemporaryDirectory(prefix="stt-runall-c-") as bt_c, \
             tempfile.TemporaryDirectory(prefix="stt-runall-r-") as bt_r:
            base = [sys.executable, "-m", "pytest", str(REPO / "tests"), "-q", "--disable-warnings"]
            c = subprocess.run(base + ["--collect-only", "--basetemp", bt_c],
                               cwd=REPO, capture_output=True, text=True)
            m = re.search(r"(\d+) tests? collected", c.stdout)
            collected = int(m.group(1)) if m else sum(1 for x in c.stdout.splitlines() if "::" in x)
            r = subprocess.run(base + ["--basetemp", bt_r],
                               cwd=REPO, capture_output=True, text=True)
            pm = re.search(r"(\d+) passed", r.stdout)
            sm = re.search(r"(\d+) skipped", r.stdout)
            passed = int(pm.group(1)) if pm else 0
            skipped = int(sm.group(1)) if sm else 0
            # 防「0 收集 / 漏收新测试仍全绿」：收集数须与 passed+skipped 自洽
            consistent = collected > 0 and r.returncode == 0 and (passed + skipped) == collected
            tail = (r.stdout or "").strip().splitlines()
            print(f"  {'✓' if consistent else '✗'} [pytest 全量] "
                  f"collected={collected} passed={passed} skipped={skipped} | "
                  f"{tail[-1] if tail else ''}")
            ok &= consistent
    print("-" * 62)
    print("全绿" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
