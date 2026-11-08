#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_cross_refs.py — 跨 skill 章节号/节名引用一致性拦截（★M5 v2.11.4）

==============================================================================
为什么需要（八轮审计 E2 增量 [实]）：包内 ≥11 条「口径 SSOT =
`skills/{other}/SKILL.md` §节名」跨文件引用，此前零机械护栏——被引用节
一旦改名/删除，引用方静默变成死链（协议层口径失去单一事实源）。

判据（结构与格式校验，确定性规则，符合分工宪法）：
  扫描 skills/ agents/ references/ 下 .md，提取两类引用：
  ①节名引用  `skills/{name}/SKILL.md` §{节名}     → 被引文件须存在含该节名
    的 `^## …{节名}…` 或 `^### …{节名}…` 标题（子串匹配，容忍标题带批次后缀）
  ②编号引用  `skills/{name}/SKILL.md` §{N}[.{M}]  → 被引文件须存在
    `^## {N}.` 或 `^### {N}.{M}` 开头标题
豁免：SKILL_CHANGELOG.md（历史流水）、vendor/、引用自身文件。

退出码：0 全部可解析 | 1 存在死链 | 2 用法错误
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCAN_DIRS = ("skills", "agents", "references")
SELF = "scripts/check_cross_refs.py"
SKIP_FILES = {"SKILL_CHANGELOG.md"}
# 引用形态：`skills/{name}/SKILL.md` §{目标}（目标 = 节名或编号，截到句读/反引号/行尾）
REF_RE = re.compile(
    r"`((?:\./)?skills/[A-Za-z0-9-]+/SKILL\.md)`\s*§\s*([0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fffA-Za-z][^，。；\n`]{1,28})"
)
# 括注剥离：「§搭接并行协议（升级 C）」→ 目标 = 搭接并行协议（括注是引用方批注，非被引节名）
PAREN_NOTE_RE = re.compile(r"[（(][^）)]*[）)]\s*$")
HEADING_RE = re.compile(r"^(#{2,4})\s*(.+?)\s*$", re.M)


def _headings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [m.group(2) for m in HEADING_RE.finditer(text)]


def _resolve(ref_file: str, root: Path) -> Path | None:
    p = root / ref_file.lstrip("./")
    return p if p.is_file() else None


def _target_exists(target: str, heads: list[str]) -> bool:
    # 编号引用：§3.7 → 标题编号段等于目标（「1. 消息信封」命中 §1；
    # 「3.7 ★G3…」命中 §3.7；编号段 = 首个 token 去掉尾部「.」）
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", target):
        for h in heads:
            tok = h.split()[0] if h.split() else ""
            if tok.rstrip(".") == target:
                return True
        return False
    # 节名引用：剥掉标题括注后**前缀整段比对**（「§搭接并行协议」命中
    # 「搭接并行协议（B3…）」；「节级并行与恢复协议V2」≠「节级并行与恢复协议」
    # ——子串匹配会把改名后的节误判为存在，反向例实测抓出后收紧）
    strip = re.compile(r"[（(].*?$")
    for h in heads:
        if strip.sub("", h).strip() == target:
            return True
    return False


def check(root: Path) -> tuple[list[dict], int]:
    refs, dead = [], 0
    cache: dict[str, list[str]] = {}
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            if rel == SELF or p.name in SKIP_FILES:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in REF_RE.finditer(text):
                ref_file, target = m.group(1), PAREN_NOTE_RE.sub("",
                                                                 m.group(2).strip()).strip()
                tp = _resolve(ref_file, root)
                if tp is None:
                    refs.append({"src": rel, "ref": f"{ref_file} §{target}",
                                 "ok": False, "why": "被引文件不存在"})
                    dead += 1
                    continue
                key = str(tp)
                if key not in cache:
                    cache[key] = _headings(tp)
                ok = _target_exists(target, cache[key])
                refs.append({"src": rel, "ref": f"{ref_file} §{target}",
                             "ok": ok, "why": "" if ok else "被引节名/编号不存在（死链）"})
                if not ok:
                    dead += 1
    return refs, dead


def main() -> int:
    ap = argparse.ArgumentParser(description="跨 skill 章节号/节名引用一致性门禁（只报不修）")
    ap.add_argument("--root", default=".", help="专家包根目录")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).expanduser()
    refs, dead = check(root)
    if args.json:
        print(json.dumps({"refs": len(refs), "dead": dead, "items": refs},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"跨文件引用一致性 | 扫描 {len(refs)} 条 §引用")
        print("=" * 62)
        for r in refs:
            if not r["ok"]:
                print(f"  ✗ [{r['src']}] {r['ref']}")
                print(f"      → {r['why']}")
        print("-" * 62)
        print(f"引用 {len(refs)} | 死链 {dead}")
        print("=" * 62)
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
