#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_book.py — 全书层门禁（5.1–5.5，ADR-01 批次 B5）

==============================================================================
为什么需要：单章流程（check_manuscript 门禁 4）只看【本章】，
跨章七项（check_cross_chapter）只看【章与章之间】，两者都覆盖不到【整本书】：
  5.1 章清单完整 + 全书字数总和与用户目标偏差 ≤5%
  5.2 每章有知识域 + 依赖序无环
  5.3 每章 check_manuscript --strict 通过
  5.4 跨章七项（术语/数据矛盾/重复/难度递进/字数分配/图号连续/术语依赖图 ★M1）
  5.5 合稿 docx 可开 + 图数一致 + 字数达标

用法
------------------------------------------------------------------------------
  python3 scripts/check_book.py --work-root "$WORK_ROOT" [--strict] [--json]

退出码：0 全部门禁通过 | 1 --strict 下存在 FAIL | 2 book-spec.md 缺失
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import count_net_words
from check_cross_chapter import (
    load_chapters, load_book_spec,
    check_terms, check_data_conflicts, check_duplication,
    check_difficulty_progression, check_word_budget, check_figure_continuity,
    check_term_dependency_graph,
)
from _profile_loader import read_discipline, load_section7, load_term_table

BOOK_SPEC = "运行态/book-spec.md"
CHAPTER_MAP = "章节/_book/chapter-map.md"
# 唯一图位对：题注行 / 图位行 / 交叉引用会重复出现同一「图 X-Y」，
# 按出现次数计数会把 1 张图数成 3 张 → 必须按 (X, Y) 对去重，才能与 docx media 数对齐
RE_FIGURE = re.compile(r"图\s*(\d+)-\s*(\d+)")


def read_book_spec(work_root: Path) -> dict | None:
    """读 book-spec.md → {textbook, total_budget, chapters:[{id,word_budget,difficulty,domain}]}。"""
    spec = work_root / BOOK_SPEC
    if not spec.is_file():
        return None
    txt = spec.read_text(encoding="utf-8")
    m = re.search(r"^textbook:\s*(.+)$", txt, re.M)
    textbook = m.group(1).strip() if m else ""
    m = re.search(r"^total_word_budget:\s*(\d+)$", txt, re.M)
    total = int(m.group(1)) if m else 0
    return {"textbook": textbook, "total_budget": total,
            "chapters": load_book_spec(work_root)}


# ── 5.1 章清单完整 + 字数总和 ≤5% ─────────────────────────────────────────
def check_5_1_chapter_list(spec: dict, chapters: dict[str, str]) -> list[dict]:
    """章清单完整（声明章 == 磁盘章）+ 全书字数总和 vs total_word_budget ≤5%。"""
    issues = []
    ids = [r["id"] for r in spec["chapters"]]
    if not ids:
        issues.append({"type": "5.1 章清单", "term": "book-spec",
                       "detail": "book-spec.md 无章清单（chapters 为空）", "severity": "FAIL"})
        return issues
    missing = [c for c in ids if c not in chapters]
    orphan = [c for c in chapters if c not in ids]
    if missing:
        issues.append({"type": "5.1 章清单", "term": "book-spec",
                       "detail": f"声明的章缺 draft: {missing}", "severity": "FAIL"})
    if orphan:
        issues.append({"type": "5.1 章清单", "term": "book-spec",
                       "detail": f"有 draft 但未列入清单: {orphan}", "severity": "FAIL"})
    total = spec["total_budget"]
    if total:
        actual = sum(count_net_words.count_net_words(t)["net_final"]
                     for t in chapters.values())
        if actual:
            dev = abs(actual - total) / total
            if dev > 0.05:
                issues.append({
                    "type": "5.1 字数", "term": "book-spec",
                    "detail": f"全书实际 {actual} 字 vs 目标 {total} 字（偏差 {dev:.1%} > 5%）",
                    "severity": "FAIL"})
    return issues


# ── 5.2 每章有知识域 + 依赖序无环 ─────────────────────────────────────────
def _read_chapter_map(work_root: Path) -> list[dict]:
    """读 章节/_book/chapter-map.md → [{id, domain, depends:[...]}]。无文件返回 []。

    表格式（BOOK_SPEC 产物，主理人手填）：
      | 章 | 知识域 | 成员 | 依赖章 |
      兼容 3 列（章 | 知识域 | 依赖章）。
    """
    cmap = work_root / CHAPTER_MAP
    if not cmap.is_file():
        return []
    rows = []
    for line in cmap.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("章", "章节", ""):
            continue
        dep_cell = cells[3] if len(cells) >= 4 else cells[2]
        deps = [d.strip() for d in re.split(r"[、，,]", dep_cell)
                if d.strip() and d.strip() not in ("—", "-", "无", "")]
        rows.append({"id": cells[0], "domain": cells[1], "depends": deps})
    return rows


def _has_cycle(edges: dict[str, list[str]], nodes: list[str]) -> bool:
    """DFS 三色判环。edges: {章: [依赖章...]}，边 u→v 表示 u 依赖 v。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    for vs in edges.values():
        for v in vs:
            color.setdefault(v, WHITE)

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in edges.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    for n in list(color):
        if color[n] == WHITE and dfs(n):
            return True
    return False


def check_5_2_domain_deps(spec: dict, work_root: Path) -> list[dict]:
    """5.2 每章有知识域 + 依赖序无环。

    知识域来自 book-spec 的 domain 字段；依赖序来自 chapter-map.md 依赖章列。
    chapter-map 缺失且所有 domain 为空 → N/A（BOOK_SPEC 未执行，不阻塞）。
    一旦任一 domain 已填或 chapter-map 存在 → 全部章必须有 domain 且依赖无环。
    """
    issues = []
    rows = spec["chapters"]
    cmap = _read_chapter_map(work_root)
    any_domain = any((r["domain"] or "").strip() for r in rows)
    if not cmap and not any_domain:
        return []  # N/A：BOOK_SPEC 未执行

    for r in rows:
        if not (r["domain"] or "").strip():
            issues.append({"type": "5.2 知识域", "term": r["id"],
                           "detail": f"{r['id']} 缺知识域（book-spec domain 为空）",
                           "severity": "FAIL"})

    if cmap:
        edges = {row["id"]: row["depends"] for row in cmap}
        if _has_cycle(edges, [r["id"] for r in rows]):
            issues.append({"type": "5.2 依赖序", "term": "chapter-map",
                           "detail": "依赖序存在环（章节依赖构成循环）", "severity": "FAIL"})
    return issues


# ── 5.3 每章 check_manuscript --strict ────────────────────────────────────
def check_5_3_per_chapter(work_root: Path, chapters: list[str]) -> list[dict]:
    """每章 check_manuscript --strict 必须 exit 0（复用单章门禁 4，判据共源）。"""
    issues = []
    script = Path(__file__).resolve().parent / "check_manuscript.py"
    for ch in sorted(chapters):
        proc = subprocess.run(
            [sys.executable, str(script), "--work-root", str(work_root),
             "--chapter", ch, "--strict"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            last = tail[-1] if tail else f"exit {proc.returncode}"
            issues.append({"type": "5.3 单章门禁", "term": ch,
                           "detail": f"{ch} check_manuscript --strict 未通过（{last}）",
                           "severity": "FAIL"})
    return issues


# ── 5.4 跨章七项（★M1 v2.11.3：补第 7 项，口径对齐 book-orchestration SKILL.md）──
def check_5_4_cross_chapter(work_root: Path, chapters: dict[str, str]) -> list[dict]:
    """跨章七项（复用 check_cross_chapter 的 7 个检查函数，判据共源）。

    ★M1 修复：此前只调 6 项，漏 check_term_dependency_graph（术语 imports ⊆ 上游
    exports 依赖闭包）——与 book-orchestration/SKILL.md「5.4 跨章七项」声明漂移。
    """
    _disc = read_discipline(work_root)
    _metrics = load_section7(work_root, _disc, "conflict_metrics")
    _terms = load_term_table(work_root, _disc)
    _spec = load_book_spec(work_root)
    dep_issues, _meta = check_term_dependency_graph(chapters)
    return (check_terms(chapters, _terms)
            + check_data_conflicts(chapters, _metrics)
            + check_duplication(chapters)
            + check_difficulty_progression(_spec)
            + check_word_budget(work_root, _spec, chapters)
            + check_figure_continuity(chapters)
            + dep_issues)


# ── 5.5 合稿可开 + 图数一致 + 字数达标 ────────────────────────────────────
def check_5_5_deliverable(work_root: Path, spec: dict,
                          chapters: dict[str, str]) -> list[dict]:
    """合稿 docx 可开 + 图数一致 + 字数达标；docx 未生成 → N/A（BOOK_DELIVER 未执行）。

    字数口径（装机实证 2026-11-01）：合稿 md 直数 ≠ 各章净字数和——合稿删了各章
    「参考文献」节、追加了全书参考文献节，两端都有漂移。字数守恒的正确锚是
    **各章交付 md 净字数之和 vs total_budget**（与 5.3 同源、与 5.1 各章预算闭环）；
    合稿 md 只验「可开 + 图数」，不再重复比字数。
    """
    issues = []
    textbook = spec["textbook"] or "教材"
    docx = work_root / "交付" / f"{textbook}.docx"
    if not docx.is_file():
        return []
    media = -1
    try:
        with zipfile.ZipFile(docx) as z:
            media = len([n for n in z.namelist() if n.startswith("word/media/")])
    except zipfile.BadZipFile:
        issues.append({"type": "5.5 合稿可开", "term": docx.name,
                       "detail": "合稿 docx 非法（BadZipFile，无法被 Word 打开）",
                       "severity": "FAIL"})
        return issues

    total_fig = len({(m.group(1), m.group(2))
                     for t in chapters.values()
                     for m in RE_FIGURE.finditer(t)})
    if media != total_fig:
        issues.append({"type": "5.5 图数一致", "term": docx.name,
                       "detail": f"合稿 docx 图数 {media} != 各章图位之和 {total_fig}",
                       "severity": "FAIL"})

    total = spec["total_budget"]
    if total:
        actual = sum(count_net_words.count_net_words(t)["net_final"]
                     for t in chapters.values())
        if actual:
            dev = abs(actual - total) / total
            if dev > 0.05:
                issues.append({"type": "5.5 字数达标", "term": "各章合计",
                               "detail": f"各章净字数和 {actual} 字 vs 全书目标 {total} 字"
                                         f"（偏差 {dev:.1%} > 5%）",
                               "severity": "FAIL"})
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="全书层门禁（5.1–5.5）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--strict", action="store_true", help="存在 FAIL 即 exit 1")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    spec = read_book_spec(work_root)
    if spec is None:
        print(f"[ERROR] 未找到 book-spec.md：{work_root / BOOK_SPEC} "
              f"（先 `progress.py book init`）", file=sys.stderr)
        return 2

    chapters = load_chapters(work_root)
    ids = [r["id"] for r in spec["chapters"]]

    issues = (check_5_1_chapter_list(spec, chapters)
              + check_5_2_domain_deps(spec, work_root)
              + check_5_3_per_chapter(work_root, ids)
              + check_5_4_cross_chapter(work_root, chapters)
              + check_5_5_deliverable(work_root, spec, chapters))

    if args.json:
        print(json.dumps({"textbook": spec["textbook"], "chapters": ids,
                          "issues": issues}, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"全书门禁 | {spec['textbook']}（{len(ids)} 章）")
        print("=" * 62)
        if not issues:
            print("  ✓ 5.1–5.5 全部门禁通过")
        for i in issues:
            mark = "✗" if i["severity"] == "FAIL" else "⚠"
            print(f"  {mark} [{i['type']}] {i['term']}")
            print(f"      → {i['detail']}")
        n_fail = sum(1 for i in issues if i["severity"] == "FAIL")
        print("-" * 62)
        print(f"FAIL {n_fail} | WARN {len(issues) - n_fail}")
        print("=" * 62)

    if args.strict and any(i["severity"] == "FAIL" for i in issues):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
