#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_profile_loader.py — profile §7 判据执行体共享加载器（B3，ADR-02）

三脚本共用（assemble_sections / check_cross_chapter / compute_metrics），
消灭「同一概念多处定义」的 C-05 病灶。三级查找：
  ① {WORK_ROOT}/学科标准/profile-overrides.md（每本书的覆盖，首选）
  ② references/profiles/{discipline}.md §7（学科默认）
  ③ 无 → 返回空列表（调用方各自兜底：触发词兜底通用百分比，矛盾指标兜底 N/A）
"""
from __future__ import annotations

import re
from pathlib import Path


def read_discipline(work_root: Path, chapter: str | None = None) -> str:
    """从 draft frontmatter 读「学科profile」，缺省回落 veterinary（默认 profile）。

    chapter 给定时只读该章 draft；为空时扫各章取首个命中（跨章场景学科应一致）。
    """
    drafts: list[Path] = []
    if chapter:
        d = work_root / "章节" / chapter / "draft.md"
        if d.is_file():
            drafts = [d]
    else:
        ch_dir = work_root / "章节"
        if ch_dir.is_dir():
            drafts = [c / "draft.md" for c in sorted(ch_dir.glob("ch*"))
                      if (c / "draft.md").is_file()]
    for d in drafts:
        m = re.search(r"^学科profile\s*:\s*(\S+)\s*$", d.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip()
    return "veterinary"


def load_section7(work_root: Path, discipline: str, key: str) -> list[str]:
    """读 profile §7 的 key（number_triggers / conflict_metrics）→ 词列表。

    三级查找：WORK_ROOT 学科标准覆盖 > profile §7；两者皆无返回 []（调用方兜底）。
    """
    text = ""
    local = work_root / "学科标准" / "profile-overrides.md"
    if local.is_file():
        text = local.read_text(encoding="utf-8")
    else:
        expert_dir = Path(__file__).resolve().parent.parent
        profile = expert_dir / "references" / "profiles" / f"{discipline}.md"
        if profile.is_file():
            text = profile.read_text(encoding="utf-8")
    m = re.search(rf"{re.escape(key)}\s*[:：]\s*(.+)", text)
    if not m:
        return []
    return [w.strip() for w in re.split(r"[、，,]", m.group(1)) if w.strip()]


def load_term_table(work_root: Path, discipline: str) -> list[dict]:
    """读 profile §5.1 术语表五列表 → [{std, aliases[], forbidden[]}]。

    三级查找：{WORK_ROOT}/学科标准/术语表.md > profile §5.1；两者皆无返回 []。
    精确锚定「标准写法」表头，避免误消费 profile §5.2 章节结构表。
    """
    text = ""
    local = work_root / "学科标准" / "术语表.md"
    if local.is_file():
        text = local.read_text(encoding="utf-8")
    else:
        expert_dir = Path(__file__).resolve().parent.parent
        profile = expert_dir / "references" / "profiles" / f"{discipline}.md"
        if profile.is_file():
            text = profile.read_text(encoding="utf-8")
    if not text:
        return []
    m = re.search(r'\|[^\n]*标准写法[^\n]*\|\s*\n\|[^\n]*---[^\n]*\|\s*\n((?:\|[^\n]*\|\s*\n)+)', text)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or not cells[0]:
            continue
        rows.append({
            "std": cells[0],
            "aliases": [a.strip() for a in re.split(r"[、，,]", cells[1])
                        if a.strip() and a.strip() not in ("—", "-", "")],
            "forbidden": [a.strip() for a in re.split(r"[、，,]", cells[2])
                          if a.strip() and a.strip() not in ("—", "-", "")],
        })
    return rows
