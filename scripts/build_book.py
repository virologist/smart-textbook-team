#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_book.py — 全书装配器（章 → 书，ADR-01 批次 B5）

==============================================================================
为什么有这个脚本
------------------------------------------------------------------------------
单章链（build_manuscript.py）产出 交付/{教材名}_{ch##}.md/.docx，一本多章的教材
没有人负责合成「一本书」：目录是散的、图号是章内序、参考文献各章各编各的号。
本脚本把 book-spec.md 声明的各章交付 md 合成：
  交付/{教材名}_合稿.md     ← 全书 md（单一 frontmatter，图号重排为全书序）
  交付/{教材名}.docx        ← 全书 docx（TOC 域 + 单节连续页码 + 参考文献合并重编号）

装配是确定性的：只搬移、拼接、重编号，不做任何内容改写。

关键设计（与 build_manuscript.py 同原则）
------------------------------------------------------------------------------
1. **md 是源，docx 是派生产物**——合稿 md 可独立交付，docx 是它的渲染态
2. **单 pandoc 调用**（不经分节）：单 sectPr → 页码天然连续不分节重启
3. **参考文献全书合并**：各章 [n] 引用按「首次出现顺序」全书重编号，
   同一条目跨章复用只保留一份（判据：去重键 = 去序号后的条目串）
4. **图号重排为全书序**：`图 {章}-{序}` → `图 {全书序}`（题注行 + 图位行 + 交叉引用同步）

用法
------------------------------------------------------------------------------
  python3 scripts/build_book.py --work-root "$WORK_ROOT"
  python3 scripts/build_book.py --work-root "$WORK_ROOT" --dry-run
  python3 scripts/build_book.py --work-root "$WORK_ROOT" --reference-doc tpl.docx

退出码
------------------------------------------------------------------------------
  0 成功
  2 输入缺失（book-spec.md / 章交付 md 缺失）
  3 依赖缺失（pandoc / python-docx）—— 硬失败，不静默降级
  4 构建失败（pandoc 返回非 0 / 产物不可读）
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_book import read_book_spec  # book-spec 解析单一来源（B5c）
from build_manuscript import (         # 版式与 pandoc 参数复用单章 SSOT
    TYPESET, FINGERPRINT_KEY, check_deps, run_pandoc, postprocess_docx, log,
)


# ──────────────────────────────────────────────────── 合并前处理：图号重排
RE_FIG_ANY = re.compile(r"(?P<kind>图|表)\s*(?P<ch>\d+)-\s*(?P<seq>\d+)")


def build_figure_maps(bodies: list[str]) -> tuple[dict, dict]:
    """扫描全部章正文，按**全书出现顺序**给每张图分配全书序号（1 起连续）。

    key 必须是 (章序号, 图号前缀, 序号) 三元组，不能只用 (前缀, 序)——
    「图 1-1」的前缀 1 是**章号**，ch01 与 ch02 各自的 1-1 是不同物理图，
    只用 (1,1) 会撞 key → 两章的图被当成同一张（实测 ch02 图未重排）。
    章身份按 bodies 的列表下标（即 book-spec 声明顺序）注入。
    """
    fig_map: dict[tuple, int] = {}
    tab_map: dict[tuple, int] = {}
    for ch_idx, body in enumerate(bodies, 1):
        for m in RE_FIG_ANY.finditer(body):
            kind = m.group("kind")
            key = (ch_idx, m.group("ch"), m.group("seq"))
            target = fig_map if kind == "图" else tab_map
            if key not in target:
                target[key] = len(target) + 1
    return fig_map, tab_map


def renumber_figures(body: str, fig_map: dict[tuple, int],
                     tab_map: dict[tuple, int], ch_idx: int) -> str:
    """把「图 {章}-{序}」整体重映射为全书序号（题注/图位/交叉引用一并用同一映射，
    保证三处必然一致——分开映射才会漂移）。"""
    def sub(m: re.Match) -> str:
        mapping = fig_map if m.group("kind") == "图" else tab_map
        key = (ch_idx, m.group("ch"), m.group("seq"))
        new = mapping.get(key)
        if new is None:
            return m.group(0)  # 映射表没有的（如文字里的历史年份「图 2-1」误报）保持原样
        return f"{m.group('kind')} {new}"

    return RE_FIG_ANY.sub(sub, body)


# ──────────────────────────────────────────────── 合并前处理：参考文献合并
RE_REF_ITEM = re.compile(r"^\[(\d+)\]\s+(.+)$", re.M)
RE_REF_CITE = re.compile(r"\[(\d+(?:\s*[,，]\s*\d+)*)\]")


def merge_references(bodies: list[str]) -> tuple[list[str], list[dict]]:
    """各章参考文献去重合并 + 全书重编号。

    返回 (合并后的条目列表, 每章的映射 [{ch_local → book_global}])。
    去重键：去掉行首 [n] 后的条目串（strip 后全文比对）——同一文献两章编号
    不同但内容相同（PMID/题名一致）是常态，必须只保留一份。
    """
    pool: list[str] = []          # 全书条目（去序号串）
    pool_index: dict[str, int] = {}
    maps: list[dict[int, int]] = []
    for body in bodies:
        m = list(RE_REF_ITEM.finditer(body))
        if not m:
            maps.append({})
            continue
        local2global: dict[int, int] = {}
        for mm in m:
            local_no = int(mm.group(1))
            entry = mm.group(2).strip()
            if entry not in pool_index:
                pool_index[entry] = len(pool) + 1
                pool.append(entry)
            local2global[local_no] = pool_index[entry]
        maps.append(local2global)

    # 正文引用 [n] / [n,m] 同步重编号（在各自章内完成，避免跨章串号）
    remapped: list[str] = []
    for body, local2global in zip(bodies, maps):
        def sub(mm: re.Match) -> str:
            nums = [n.strip() for n in re.split(r"[,，]", mm.group(1))]
            news = [str(local2global.get(int(n), int(n))) for n in nums]
            return "[" + ",".join(news) + "]"
        remapped.append(RE_REF_CITE.sub(sub, body))
    return pool, maps


def remap_ref_items(body: str, local2global: dict[int, int]) -> str:
    """把章内「参考文献」节的条目行 [local] 重编号为全书号（只动行首 [n]）。"""
    def sub(m: re.Match) -> str:
        new = local2global.get(int(m.group(1)))
        return f"[{new}]" if new else m.group(0)
    return RE_REF_ITEM.sub(sub, body)


# ──────────────────────────────────────────────────────────── 主装配
def merge_chapters(work_root: Path, spec: dict) -> tuple[str, dict]:
    """把各章交付 md 合成全书 md。返回 (全书 md 文本, 报告数据)。"""
    parts = []
    fig_map = tab_map = None
    merged_refs: list[str] = []
    per_ch = []

    # 第一遍：取正文、建映射
    raw_bodies: list[str] = []
    for row in spec["chapters"]:
        ch = row["id"]
        hits = sorted((work_root / "交付").glob(f"*_{ch}.md")) if (work_root / "交付").is_dir() else []
        if not hits:
            log(f"章 {ch} 无交付 md（交付/*_{ch}.md）——先跑单章 build --assemble", "ERROR")
            sys.exit(2)
        text = hits[0].read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        raw_bodies.append(body.strip())

    fig_map, tab_map = build_figure_maps(raw_bodies)
    merged_refs, ref_maps = merge_references(raw_bodies)

    # 第二遍：图号重排 + 引用重编号 + 参考文献 trimmed（只留条目行，合并到全书节）
    for ch_idx, (row, body, ref_map) in enumerate(
            zip(spec["chapters"], raw_bodies, ref_maps), 1):
        ch = row["id"]
        body = renumber_figures(body, fig_map, tab_map, ch_idx)
        body = remap_ref_items(body, ref_map)
        body = strip_ref_section(body)   # 章级参考文献节删除（全书统一放末尾）
        parts.append(body)
        per_ch.append({"chapter": ch, "net_chars": len(re.findall(r"[\u4e00-\u9fff]", body))})

    head = (f"---\n教材名: {spec['textbook']}\n类型: 全书合稿\n"
            f"章数: {len(spec['chapters'])}\n"
            f"总字数目标: {spec['total_budget']}\n---\n\n")
    merged = (head
              + "\n\n".join(f"<!-- ═══ {r['id']} ═══ -->\n\n" + p for r, p in zip(spec['chapters'], parts))
              + "\n\n## 参考文献\n\n"
              + "\n".join(f"[{i}] {e}" for i, e in enumerate(merged_refs, 1)) + "\n")

    report = {
        "chapters": [r["id"] for r in spec["chapters"]],
        "figure_map": {f"ch{ci}-{c}-{s}": n for (ci, c, s), n in fig_map.items()},
        "table_map": {f"ch{ci}-{c}-{s}": n for (ci, c, s), n in tab_map.items()},
        "merged_refs": len(merged_refs),
        "per_chapter": per_ch,
    }
    return merged, report


def split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        return m.group(1), text[m.end():]
    return "", text


def strip_ref_section(body: str) -> str:
    """删除章内「## 参考文献」节（含其后全部内容——参考文献是各章末节）。"""
    m = re.search(r"^##\s*参考文献\s*$", body, re.M)
    if m:
        return body[:m.start()].rstrip() + "\n"
    return body


# ──────────────────────────────────────────────────────────── docx 后处理
def insert_page_field(paragraph) -> None:
    """往段落插入 Word PAGE 域（页码）。

    为什么手工 OxmlElement：python-docx 的 CT_R **没有** add_fldChar/add_instrText
    方法（本机实测 hasattr=False）——build_manuscript.postprocess_docx 里的
    `run._r.add_fldChar("begin")` 其实一直在 AttributeError → 被 except 静默吞掉，
    单章 docx 的页码域从未真正写入过。此处用 OxmlElement 权威写法，且**不套
    try/except 吞错**——域写不进去必须当场炸，不能产出静默无页码的合稿。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    fld_b = OxmlElement("w:fldChar"); fld_b.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_e = OxmlElement("w:fldChar"); fld_e.set(qn("w:fldCharType"), "end")
    run._r.append(fld_b)
    run._r.append(instr)
    run._r.append(fld_e)


def postprocess_book_docx(docx_path: Path, textbook: str) -> bool:
    """合稿 docx 后处理：页眉=教材名；页脚=PAGE 域（单节 → 全书连续页码）。

    版式（字体/字号/行距/题注居中）复用单章 postprocess_docx；此处只补
    「全书页眉 + 页码域」——build_manuscript 的 postprocess 签名要章标题，
    直接复用会把最后一章标题写到全书页眉，故单独实现（差异仅页眉文本）。
    """
    try:
        from docx import Document
        from docx.shared import Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        log("python-docx 不可用，跳过合稿后处理", "WARN")
        return True
    doc = Document(str(docx_path))
    m = TYPESET["page_margins_cm"]
    for sec in doc.sections:
        sec.top_margin = Cm(m["top"])
        sec.bottom_margin = Cm(m["bottom"])
        sec.left_margin = Cm(m["left"])
        sec.right_margin = Cm(m["right"])
        try:
            hp = sec.header.paragraphs[0]
            hp.text = textbook
            hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        except (IndexError, AttributeError):
            pass
        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        insert_page_field(fp)
    doc.core_properties.comments = f"{FINGERPRINT_KEY}=book-merged"
    doc.save(str(docx_path))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="全书装配器（章 → 书）")
    ap.add_argument("--work-root", required=True, help="WORK_ROOT 路径")
    ap.add_argument("--reference-doc", default=None, help="pandoc 版式模板（覆写内置默认）")
    ap.add_argument("--format", default="md,docx", help="构建格式，逗号分隔（默认 md,docx）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不落盘产物")
    ap.add_argument("--report", default=None, help="装配报告 JSON 落盘路径")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    if not work_root.is_dir():
        log(f"WORK_ROOT 不存在：{work_root}", "ERROR")
        return 2

    spec = read_book_spec(work_root)
    if spec is None:
        log(f"未找到 {work_root / '运行态/book-spec.md'}——先 `progress.py book init`", "ERROR")
        return 2

    if "docx" in args.format:
        deps = check_deps()
        if not deps["pandoc"] or not deps["python_docx"]:
            log("硬依赖缺失（pandoc / python-docx）——不降级，直接失败"
                "（装法：brew install pandoc && pip install python-docx）", "ERROR")
            return 3

    merged_md, report = merge_chapters(work_root, spec)

    out_dir = work_root / "交付"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{spec['textbook']}_合稿.md"

    if args.dry_run:
        print(json.dumps({"planned_md": str(md_path), **report, "dry_run": True},
                         ensure_ascii=False, indent=2))
        return 0

    md_path.write_text(merged_md, encoding="utf-8")
    log(f"合稿 md：{md_path}（{report['merged_refs']} 条全书参考文献）")

    if "docx" in args.format:
        # 单 pandoc 调用（--toc → TOC 域；单 sectPr → 页码连续不分节重启）
        docx_path = out_dir / f"{spec['textbook']}.docx"
        if not run_pandoc(md_path, docx_path, args.reference_doc):
            return 4
        if not postprocess_book_docx(docx_path, spec["textbook"]):
            return 4
        report["docx"] = str(docx_path)
        report["docx_bytes"] = docx_path.stat().st_size
        log(f"合稿 docx：{docx_path}（{report['docx_bytes']} 字节）")

    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        log(f"装配报告：{args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
