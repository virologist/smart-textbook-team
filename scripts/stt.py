#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stt.py — 智能教材编写天团 统一 CLI 入口（改造批次，2026-11-10）

==============================================================================
消除 team-lead 中重复 5 遍的 EXPERT_DIR 兜底逻辑 + 分散的门禁调用 + 手抄 spawn
装配长串命令。本 CLI 从自身 __file__ 派生专家包根（比 `for r in .workbuddy
.codebuddy` 兜底循环更稳，且不依赖 cwd / 环境变量），对外暴露收敛子命令：

  stt env                          打印解析到的包根与关键路径（诊断用）
  stt gate  --phase <P> ...        按相位调用对应门禁脚本
                                   支持：design / retrieve / produce /
                                         proofread / cross / consistency
  stt spawn --member <id> ...      封装 assemble_spawn_prompt.py（成员人设注入）
  stt net-words --target <n> <f>   封装 count_net_words.py（门禁 3.2）
  stt verify [--root <pkg>]        跑全量静态契约 + 门禁一致性 + 红道登记

设计原则：
  · 薄封装：本 CLI 只负责「解析包根 + 派发」，不重写既有脚本逻辑，零回归风险。
  · 包根解析：PKG = dirname(__file__) 的父目录；EXPERT_DIR 环境变量可覆盖。
    这比 team-lead 里 `for r in "$HOME/.workbuddy" "$HOME/.codebuddy"` 兜底循环
    更稳——脚本被哪种方式调用都能定位到自己所在包。
  · 退出码：0 全通过（可含 WARN）/ 1 存在 FAIL / 2 输入缺失或判据自身失效。

用法示例：
  python3 "$EXPERT_DIR/scripts/stt.py" env
  python3 scripts/stt.py gate --phase design --work-root "$WORK_ROOT" --chapter ch01
  python3 scripts/stt.py gate --phase proofread --work-root "$WORK_ROOT" --chapter ch01 --strict
  python3 scripts/stt.py spawn --member subject-writer --task-id ch01-PRODUCE-R1 \
      --task-file 章节/ch01/task_pkg.md --run-dir 运行态/.harness-runs/ch01-PRODUCE-R1 --check-task-package
  python3 scripts/stt.py verify --root .
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(_HERE)  # scripts/ 的父目录 = 专家包根


def resolve_expert_dir() -> str:
    """包根解析：环境变量优先，否则用脚本自身所在包的父目录。"""
    return os.environ.get("EXPERT_DIR") or PKG


def _script(name: str) -> str:
    return os.path.join(_HERE, name)


def _run(script: str, args: list[str], expert_dir: str | None = None) -> int:
    """运行一个同包脚本，透传 stdout/stderr，返回其退出码。"""
    cmd = [sys.executable, _script(script), *args]
    env = dict(os.environ)
    if expert_dir:
        env["EXPERT_DIR"] = expert_dir
    return subprocess.call(cmd, env=env)


def _chapter_dir(work_root: str, chapter: str) -> str:
    return os.path.join(work_root, "章节", chapter)


# ── 各相位门禁的脚本映射（SSOT：team-lead 全局路径约定 + pipeline 门禁定义）──
# design   → check_gate_design.py    （门禁 1：知识域均有检索计划 / 时数≥1 / 含知识块锚点）
# retrieve → check_gate_retrieval.py （门禁 2：覆盖率/冲突率/时效性）
# produce  → count_net_words.py      （门禁 3.2：净字数 ±5%）
# proofread→ check_manuscript.py     （门禁 4：书稿交付校验 --strict）
# cross    → check_cross_chapter.py  （跨章 6 项）
# consistency → 静态契约 + 相位 + skill frontmatter + 红道登记（聚合）


def cmd_env(args: argparse.Namespace) -> int:
    ed = resolve_expert_dir()
    print(f"EXPERT_DIR (resolved) : {ed}")
    print(f"scripts dir          : {_HERE}")
    print(f"assemble_spawn_prompt: {'存在' if os.path.isfile(_script('assemble_spawn_prompt.py')) else '缺失'}")
    print(f"check_gate_design    : {'存在' if os.path.isfile(_script('check_gate_design.py')) else '缺失'}")
    print(f"check_gate_retrieval : {'存在' if os.path.isfile(_script('check_gate_retrieval.py')) else '缺失'}")
    print(f"check_redlane_registry: {'存在' if os.path.isfile(_script('check_redlane_registry.py')) else '缺失'}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    phase = args.phase.lower()
    ed = resolve_expert_dir()
    work_root = args.work_root
    chapter = args.chapter

    if phase in ("design", "specify"):
        if not work_root or not chapter:
            sys.stderr.write("[gate:design] 需要 --work-root 与 --chapter\n")
            return 2
        design = os.path.join(_chapter_dir(work_root, chapter), "chapter_design.md")
        return _run("check_gate_design.py", ["--design", design])

    if phase in ("retrieve", "retrieval"):
        if not work_root or not chapter:
            sys.stderr.write("[gate:retrieve] 需要 --work-root 与 --chapter\n")
            return 2
        retrieval_dir = os.path.join(work_root, "知识库", "retrieval")
        design = os.path.join(_chapter_dir(work_root, chapter), "chapter_design.md")
        extra = []
        if args.strict:
            extra.append("--strict")
        return _run("check_gate_retrieval.py",
                    ["--design", design, "--retrieval-dir", retrieval_dir, *extra])

    if phase == "produce":
        if not args.target or not args.file:
            sys.stderr.write("[gate:produce] 需要 --target <目标字数> 与 --file <draft.md>\n")
            return 2
        return _run("count_net_words.py", ["--target", str(args.target), args.file])

    if phase in ("proofread", "deliver"):
        if not work_root or not chapter:
            sys.stderr.write("[gate:proofread] 需要 --work-root 与 --chapter\n")
            return 2
        extra = ["--strict"] if args.strict else []
        return _run("check_manuscript.py",
                    ["--work-root", work_root, "--chapter", chapter, *extra])

    if phase == "cross":
        if not work_root or not chapter:
            sys.stderr.write("[gate:cross] 需要 --work-root 与 --chapter\n")
            return 2
        extra = ["--strict"] if args.strict else []
        return _run("check_cross_chapter.py",
                    ["--work-root", work_root, "--affected-from", chapter, *extra])

    if phase == "consistency":
        root = args.root or "."
        rc = 0
        for s, a in (
            ("check_doc_consistency.py", ["--root", root]),
            ("check_phase_consistency.py", ["--root", root]),
            ("check_skill_frontmatter.py", ["--root", root]),
            ("check_redlane_registry.py", ["--root", root]),
        ):
            print(f"\n=== {s} ===")
            c = _run(s, a)
            rc = rc or c
        return rc

    sys.stderr.write(f"[gate] 未知相位：{phase}（支持 design/retrieve/produce/proofread/cross/consistency）\n")
    return 2


def cmd_spawn(args: argparse.Namespace) -> int:
    """封装 assemble_spawn_prompt.py（其自身会解析联邦 shared-core / vendor 兜底）。"""
    base = ["--member", args.member, "--task-id", args.task_id, "--task-file", args.task_file]
    if args.run_dir:
        base += ["--run-dir", args.run_dir]
    if args.check_task_package:
        base += ["--check-task-package"]
    if args.out:
        base += ["--out", args.out]
    return _run("assemble_spawn_prompt.py", base)


def cmd_net_words(args: argparse.Namespace) -> int:
    return _run("count_net_words.py", ["--target", str(args.target), args.file])


def cmd_verify(args: argparse.Namespace) -> int:
    root = args.root or "."
    rc = 0
    for s, a in (
        ("check_doc_consistency.py", ["--root", root]),
        ("check_phase_consistency.py", ["--root", root]),
        ("check_skill_frontmatter.py", ["--root", root]),
        ("check_redlane_registry.py", ["--root", root]),
    ):
        print(f"\n=== {s} ===")
        c = _run(s, a)
        rc = rc or c
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stt", description="智能教材编写天团 统一 CLI 入口")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="打印解析到的包根与关键路径").set_defaults(func=cmd_env)

    g = sub.add_parser("gate", help="按相位调用对应门禁脚本")
    g.add_argument("--phase", required=True, help="design/retrieve/produce/proofread/cross/consistency")
    g.add_argument("--work-root", help="WORK_ROOT 工作根目录")
    g.add_argument("--chapter", help="章节号，如 ch01")
    g.add_argument("--target", type=int, help="produce 门禁的目标净字数")
    g.add_argument("--file", help="produce 门禁的 draft.md 路径（与 --work-root/--chapter 二选一）")
    g.add_argument("--strict", action="store_true", help="门禁按严格模式（存在 FAIL 即非零退出）")
    g.add_argument("--root", help="consistency 的包根（默认 .）")
    g.set_defaults(func=cmd_gate)

    s = sub.add_parser("spawn", help="封装 assemble_spawn_prompt.py（成员人设注入）")
    s.add_argument("--member", required=True)
    s.add_argument("--task-id", required=True)
    s.add_argument("--task-file", required=True)
    s.add_argument("--run-dir", default=None)
    s.add_argument("--check-task-package", action="store_true")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_spawn)

    n = sub.add_parser("net-words", help="封装 count_net_words.py（门禁 3.2）")
    n.add_argument("--target", type=int, required=True, help="目标净字数")
    n.add_argument("file", help="draft.md 路径")
    n.set_defaults(func=cmd_net_words)

    v = sub.add_parser("verify", help="跑全量静态契约 + 门禁一致性 + 红道登记")
    v.add_argument("--root", default=".", help="包根（默认 .）")
    v.set_defaults(func=cmd_verify)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
