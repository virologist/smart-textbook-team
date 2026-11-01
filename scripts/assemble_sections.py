#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assemble_sections.py — 节级正文拼接器（E4 落地：pipeline §3.6 步骤③的工具支撑）

==============================================================================
为什么有这个脚本（2026-10-31 E4 实测缺口）
------------------------------------------------------------------------------
pipeline §3.6 规定「>8000 字章节强制按节推进：sections/{节号}.md → 拼接为 draft.md，
拼接必须记录来源节号」。但此前：
  - scripts/ 无任何拼接工具（build_manuscript.py 只直读 draft.md）
  - 「来源节号」记录格式未定义
  - 拼接人（subject-writer）手工 cat → 漏节/错序不可审计
本脚本兑现步骤③：确定性拼接 + 逐节自检前置校验 + 拼接清单落盘（返修定位锚）。

用法
------------------------------------------------------------------------------
  # 基本拼接（按 chapter_design §C 节序，或 --order 显式指定）
  python3 scripts/assemble_sections.py --work-root "$WORK_ROOT" --chapter ch01

  # 显式节序（默认按 chapter_design §C 解析；解析失败时必须给 --order）
  python3 scripts/assemble_sections.py --work-root "$WORK_ROOT" --chapter ch01 \
      --order 1.1,1.2,1.3

退出码
------------------------------------------------------------------------------
  0 成功（draft.md + 拼接清单落盘）
  1 节级自检未过（缺节/标签缺失/编号断裂——禁止把带缺陷的节拼成整章）
  2 输入缺失
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _profile_loader import read_discipline, load_section7

RE_SECTION_FILE = re.compile(r"^(\d+(?:\.\d+)?)\.md$")
RE_DATA_TAG = re.compile(r"\[(?:实|估|引|待核实)")
RE_FIG_SLOT = re.compile(r"\[图\s*\d+-\d+[：：]")
# 通用数值信号（兜底）：任何「数字+百分比」陈述都算数值陈述、必须带数据标签。
# 学科触发词另从 profile §7 加载（B3，ADR-02）——旧实现把 11 个兽医指标写死，
# 非兽医学科（计算机/法学）的数值陈述恒绿（C-05 病灶）。
RE_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*[%％]")


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}", file=sys.stderr)


def parse_design_order(design_path: Path) -> list[str]:
    """从 chapter_design §C 解析节序（「节号」列）；失败返回空表。"""
    text = design_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*C[\.、．]?\s*[^\n]*\n(?:(?!^## ).)*", text, re.S | re.M)
    seg = m.group(0) if m else text
    order: list[str] = []
    for line in seg.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and re.fullmatch(r"\d+(?:\.\d+)+", cells[0]):
            order.append(cells[0])
    return order


def self_check_section(path: Path, sec_no: str, triggers: list[str] | None = None) -> list[str]:
    """节级自查（pipeline §3.6 步骤②：门禁 3.1/3.4 的节内子集）。返回问题列表。"""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return [f"{sec_no}: 空文件"]
    # 标签完整率：数值触发词陈述必须带标签（简化口径：触发词所在行无任一标签即报）。
    # 触发 = 学科触发词（profile §7）命中 或 通用百分比数值信号命中。
    triggers = triggers or []
    for i, line in enumerate(text.splitlines(), 1):
        hit = any(t and t in line for t in triggers) or bool(RE_PERCENT.search(line))
        if hit and not RE_DATA_TAG.search(line):
            problems.append(f"{sec_no} 行{i}: 数值触发词陈述缺 [实]/[估]/[引]/[待核实] 标签")
    # 图表位编号一致性：图位章号无须在此校验（整章门禁 3.4 管），但格式须合法
    for m in re.finditer(r"\[图\s*([^\]：:]{1,8})[：:]", text):
        if not re.fullmatch(r"\d+-\d+", m.group(1).strip()):
            problems.append(f"{sec_no}: 图位编号格式非法: [{m.group(1)}]")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="节级正文拼接器（pipeline §3.6 步骤③）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--chapter", required=True, help="如 ch01")
    ap.add_argument("--order", default=None,
                    help="逗号分隔节序（缺省从 chapter_design §C 解析）")
    ap.add_argument("--skip-check", action="store_true",
                    help="跳过节级自查（仅限主理人显式豁免并记录 interventions）")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    ch_dir = work_root / "章节" / args.chapter
    sec_dir = ch_dir / "sections"
    if not sec_dir.is_dir():
        log(f"sections/ 不存在：{sec_dir}（无节级文件，无需拼接；整章推进模式直接用 draft.md）")
        return 0

    sec_files = sorted(sec_dir.glob("*.md"))
    if not sec_files:
        log(f"sections/ 为空：{sec_dir}", "ERROR")
        return 2

    # 节序：显式 > 设计解析 > 文件名自然序
    order: list[str] = []
    if args.order:
        order = [s.strip() for s in args.order.split(",") if s.strip()]
    else:
        design = ch_dir / "chapter_design.md"
        if design.is_file():
            order = parse_design_order(design)
    file_map = {RE_SECTION_FILE.match(f.name).group(1): f
                for f in sec_files if RE_SECTION_FILE.match(f.name)}
    if order:
        missing_on_disk = [s for s in order if s not in file_map]
        if missing_on_disk:
            log(f"节序中有 {len(missing_on_disk)} 节缺文件: {missing_on_disk}", "ERROR")
            return 1
        extra = [s for s in file_map if s not in order]
        if extra:
            log(f"磁盘上有节不在设计节序中（将被忽略，请确认）: {extra}", "WARN")
        ordered = [file_map[s] for s in order]
        order_used = order
    else:
        ordered = sec_files
        order_used = [RE_SECTION_FILE.match(f.name).group(1) for f in sec_files]
        log("未指定 --order 且设计解析失败 → 按文件名自然序拼接（建议显式给序）", "WARN")

    # 节级自查（步骤②前置——不过审不得拼接）
    if not args.skip_check:
        _discipline = read_discipline(work_root, args.chapter)
        _triggers = load_section7(work_root, _discipline, "number_triggers")
        all_problems: list[str] = []
        for f, s in zip(ordered, order_used):
            all_problems.extend(self_check_section(f, s, _triggers))
        if all_problems:
            log(f"节级自查未过（{len(all_problems)} 项）——禁止拼接，回 writer 修节：", "ERROR")
            for p in all_problems[:20]:
                log(f"  ✗ {p}", "ERROR")
            return 1

    # 拼接：frontmatter（draft 若已有则保留）+ 各节全文 + 拼接清单
    parts: list[str] = []
    for f in ordered:
        body = f.read_text(encoding="utf-8").strip()
        # 各节若自带 frontmatter，剥离（只保留 draft 级一份）
        fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", body, re.S)
        if fm:
            body = body[fm.end():]
        parts.append(body)
    draft = ch_dir / "draft.md"
    head = ""
    if draft.is_file():
        old = draft.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", old, re.S)
        if m:
            head = f"---\n{m.group(1)}\n---\n\n"
    draft.write_text(head + "\n\n".join(parts) + "\n", encoding="utf-8")

    # 拼接清单（返修定位锚：来源节号 → draft 内位置序）
    manifest = {
        "chapter": args.chapter,
        "assembled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "order": order_used,
        "sections": [{"节号": s, "文件": f"sections/{f.name}"} for s, f in zip(order_used, ordered)],
        "self_check": "passed" if not args.skip_check else "skipped(主理人豁免)",
    }
    (ch_dir / "拼接清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"拼接完成：{draft}（{len(ordered)} 节，顺序 {order_used}；清单：拼接清单.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
