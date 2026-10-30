#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_manuscript.py — 大学教材书稿构建器（md 源 → docx 交付）

==============================================================================
为什么有这个脚本（2026-10-29 实测背景）
------------------------------------------------------------------------------
team-lead.md Phase ASSEMBLE 曾写「按 CHANGELOG 工具链 scripts/build_chapter.py
模板，可选生成 docx」。实测：
  - scripts/ 无 build_chapter.py
  - CHANGELOG/README/AGENTS/CONTRIBUTING 全文 grep docx|pandoc|build_chapter = 0 命中
  - git 全历史 --diff-filter=AD 查 *build_chapter* = 0 结果
即引用了不存在的文件并虚构了出处。本脚本用真实实现兑现该承诺。

设计原则（对齐 manuscript-delivery skill）
------------------------------------------------------------------------------
1. **md 是源，docx 是一次性派生产物**——禁止手改 docx，改则回 md 重建
2. **双轨图表**：md 保留可渲染源码；docx 嵌栅格化 PNG
3. **栅格化三级降级**，绝不静默丢图（mmdc → npx → 占位框 + 报告）
4. **零硬编码**：路径/字体/字号全部可配（--config 或内置默认常量集中在 CONFIG 区）

用法
------------------------------------------------------------------------------
  # 从已装配的交付 md 构建 docx
  python3 scripts/build_manuscript.py --work-root "$WORK_ROOT" --chapter ch01

  # 从 章节/ 目录先装配 md，再构建 docx
  python3 scripts/build_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 --assemble

  # 只做干跑（不落盘产物，打印计划）
  python3 scripts/build_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 --dry-run

  # 指定版式模板（覆写内置默认，pandoc --reference-doc）
  python3 scripts/build_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 \
      --reference-doc /path/to/template.docx

退出码
------------------------------------------------------------------------------
  0 成功（含带降级告警的成功）
  2 输入缺失（交付 md 找不到且未给 --assemble）
  3 依赖缺失（pandoc 或 python-docx 不可用）—— 硬失败，不静默降级
  4 构建失败（pandoc 返回非 0 / 产物不可读）
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ──────────────────────────────────────────────────────────── CONFIG（可覆写）
# 版式默认（对应 manuscript-delivery skill §3.1；--reference-doc 优先于本区）
TYPESET = {
    "body_font": "宋体",
    "body_size_pt": 12,
    "line_spacing": 1.5,
    "first_line_indent_pt": 24,      # = 2 字符（12pt × 2）
    "h1_font": "黑体", "h1_size_pt": 16,
    "h2_font": "黑体", "h2_size_pt": 14,
    "h3_font": "黑体", "h3_size_pt": 12,
    "caption_size_pt": 10.5,
    "page_margins_cm": {"top": 2.54, "bottom": 2.54, "left": 3.17, "right": 3.17},
}
# 栅格化参数
RASTER = {"width": 1024, "height": 768, "background": "white", "timeout_sec": 120}
# 图位 / 题注 / 代码块 正则
RE_FIGURE_SLOT = re.compile(r"\[图\s*(\d+)-(\d+)：([^\]]*)\]")
# 题注行：允许带 `[` 前缀（图位占位与题注被合并进同一段落时 pandoc 会保留方括号）
RE_CAPTION = re.compile(r"^\s*\[?(图|表)\s*\d+-\d+")
RE_FENCE = re.compile(r"```(mermaid|svg)\s*\n(.*?)```", re.S)
# 注：Markdown 表格不栅格化——pandoc 会转成 docx 原生表格（可编辑、可选中）。
# （原 RE_TABLE_FENCE 常量从未被使用，属死代码，已删除）


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}", file=sys.stderr)


# ──────────────────────────────────────────────────────────── 依赖检查
def check_deps() -> dict:
    """返回依赖可用情况。pandoc/python-docx 缺失 = 硬失败；mmdc 缺失 = 可降级。"""
    deps = {
        "pandoc": shutil.which("pandoc"),
        "mmdc": shutil.which("mmdc"),
        "npx": shutil.which("npx"),
        "python_docx": None,
    }
    try:
        import docx  # noqa: F401
        deps["python_docx"] = "ok"
    except ImportError:
        deps["python_docx"] = None
    return deps


# ──────────────────────────────────────────────────────────── 装配（可选）
def find_delivery_md(work_root: Path, chapter: str) -> Path:
    """定位交付 md。多命中属于**歧义**，必须报错而非静默取第一个
    （2026-10-30 修复：同名前缀多个文件时会悄悄选错章节稿）。"""
    d = work_root / "交付"
    hits = sorted(d.glob(f"*_{chapter}.md")) if d.is_dir() else []
    if not hits:
        return None
    if len(hits) > 1:
        log(f"交付目录下 *_{chapter}.md 命中 {len(hits)} 个，无法判定目标章节稿："
            f"{[h.name for h in hits]}", "ERROR")
        log("请清理重名文件（如旧版 教材_ch01_v1.md）或改用明确的 --chapter 名称", "ERROR")
        sys.exit(2)
    return hits[0]


def _split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        return m.group(1), text[m.end():]
    return "", text


def assemble_md(work_root: Path, chapter: str, textbook: str) -> Path:
    """从 章节/{ch##}/draft.md + figures/*.md 装配出交付 md。

    装配是确定性的：书稿 frontmatter + draft 正文 + 按文件名排序的图表块。不做内容改写。

    **frontmatter 生成（2026-10-30 补）**：交付书稿必须携带七项元数据
    （manuscript-delivery §1.2，校验判据 4.0）。此前装配器直接把 draft 原文搬过去，
    draft 若没写 frontmatter，交付稿就没有 → 4.0 恒 FAIL。
    现按「draft 已有值优先，缺失项推导/取默认」生成；推导不出的（字数目标）
    置 0 并 WARN，不编造。
    """
    ch_dir = work_root / "章节" / chapter
    draft = ch_dir / "draft.md"
    if not draft.is_file():
        log(f"装配失败：{draft} 不存在", "ERROR")
        sys.exit(2)

    fm_src, body = _split_frontmatter(draft.read_text(encoding="utf-8"))
    existing = dict(re.findall(r"^([^\s:#]+)\s*:\s*(.*)$", fm_src, re.M))

    m_title = re.search(r"^#\s+(.*)$", body, re.M)
    title = (m_title.group(1).strip() if m_title else "")

    net = 0
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from count_net_words import count_net_words
        net = count_net_words(body).get("net_final", 0)
    except Exception as e:
        log(f"净字数计算失败（置 0）：{e}", "WARN")

    fm = {
        "教材名": existing.get("教材名") or textbook,
        "章节号": existing.get("章节号") or chapter,
        "章节标题": existing.get("章节标题") or title,
        "字数目标": existing.get("字数目标") or "0",
        "实际净字数": str(net),
        "版本": existing.get("版本") or "R3",
        "学科profile": existing.get("学科profile") or "veterinary",
    }
    if not existing:
        log("draft 无 frontmatter → 已按推导值生成书稿元数据", "WARN")
    if fm["字数目标"] == "0":
        log("字数目标缺失（置 0）——请在 draft frontmatter 或设计文件中给出，"
            "否则门禁 4.7 无法判定字数达标", "WARN")
    if fm["学科profile"] == "veterinary" and "学科profile" not in existing:
        log("学科 profile 未声明 → 回落默认 veterinary（换专业请在 frontmatter 显式声明）",
            "WARN")

    fig_dir = ch_dir / "figures"
    blocks = [f.read_text(encoding="utf-8") for f in sorted(fig_dir.glob("*.md"))] \
        if fig_dir.is_dir() else []

    out_dir = work_root / "交付"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{textbook}_{chapter}.md"

    head = "---\n" + "\n".join(f"{k}: {v}" for k, v in fm.items()) + "\n---\n"
    parts = [head, body.strip()]
    if blocks:
        parts.append("\n\n---\n\n## 本章图表\n")
        parts.extend(blocks)
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    log(f"装配完成：{out}（frontmatter 七项 + 正文 + {len(blocks)} 个图表块）")
    return out


# ──────────────────────────────────────────────────────────── 图表栅格化
def write_source_assets(text: str, chapter: str, asset_dir: Path) -> list[dict]:
    """把 md 中的 mermaid/svg 代码块落盘为源码文件，返回资产清单。

    **配对策略：按位置就近匹配，不是按下标顺序配对**（2026-10-30 修复）。
    旧实现用 `zip(slots, fences)` 按下标配——只要某图位前置了额外代码块
    （如表格/示例），后续全部错位，会把第 2 张图的源码挂到 `图 1-1` 名下。
    教材插错图属于硬伤，且此类错位不会报错，只会静默产出错误的书稿。

    新策略：每个图位取其**之后、下一个图位之前**的第一个未被占用的代码块。
    匹配不上的两侧（无源码的图位 / 无图位的代码块）分别落盘并 WARN，绝不静默。
    """
    slot_ms = list(RE_FIGURE_SLOT.finditer(text))
    fence_ms = list(RE_FENCE.finditer(text))
    asset_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict] = []

    used: set[int] = set()
    orphan_slots: list[str] = []

    for i, sm in enumerate(slot_ms):
        ch_no, seq, title = sm.group(1), sm.group(2), sm.group(3)
        stem = f"{ch_no}-{seq}"
        # 搜索窗口：本图位之后 → 下一个图位之前（没有下一个则到文末）
        window_end = slot_ms[i + 1].start() if i + 1 < len(slot_ms) else len(text)
        pick = None
        for j, fm in enumerate(fence_ms):
            if j in used:
                continue
            if sm.end() <= fm.start() < window_end:
                pick = j
                break
        if pick is None:
            orphan_slots.append(stem)
            continue
        used.add(pick)
        fm = fence_ms[pick]
        kind, code = fm.group(1), fm.group(2)
        ext = "mmd" if kind == "mermaid" else "svg"
        src = asset_dir / f"{stem}.{ext}"
        src.write_text(code.strip() + "\n", encoding="utf-8")
        assets.append({"stem": stem, "kind": kind, "src": str(src),
                       "title": title, "png": None, "raster": None,
                       "fence_start": fm.start()})

    # 未匹配到任何图位的代码块：仍落盘（不丢内容），但显式告警
    orphan_fences = [j for j in range(len(fence_ms)) if j not in used]
    for n, j in enumerate(orphan_fences, 1):
        kind, code = fence_ms[j].group(1), fence_ms[j].group(2)
        ext = "mmd" if kind == "mermaid" else "svg"
        stem = f"{chapter}-orphan{n:02d}"
        src = asset_dir / f"{stem}.{ext}"
        src.write_text(code.strip() + "\n", encoding="utf-8")
        assets.append({"stem": stem, "kind": kind, "src": str(src),
                       "title": "", "png": None, "raster": None, "orphan": True,
                       "fence_start": fence_ms[j].start()})

    if orphan_slots:
        log(f"⚠️  {len(orphan_slots)} 个图位在其后未找到图表源码（docx 中将只有题注、无图）："
            f"{orphan_slots} ——请检查 draft 是否漏贴代码块", "WARN")
    if orphan_fences:
        log(f"⚠️  {len(orphan_fences)} 个图表代码块未归属任何图位（已落盘为 "
            f"{chapter}-orphanNN，docx 中按独立图处理）", "WARN")
    if assets:
        log(f"图表源码落盘 {len(assets)} 个 → {asset_dir}")
    return assets


def rasterize(assets: list[dict], asset_dir: Path, deps: dict) -> list[dict]:
    """三级降级栅格化：mmdc → npx mermaid-cli → 保留源码（占位框）。"""
    failed = []
    for a in assets:
        png = asset_dir / f"{a['stem']}.png"
        # SVG 不走 mmdc（mmdc 只吃 .mmd）。SVG 本身是矢量格式，
        # 直接交由 pandoc 嵌入 docx——Word 支持 SVG，且优于二次栅格化。
        # （旧实现把 svg 也送进 mmdc，必然 exit 1 → 无谓触发降级占位）
        if a["kind"] == "svg":
            a["png"] = a["src"]
            a["raster"] = "ok-vector"
            continue
        cmd = None
        if deps.get("mmdc"):
            # 宽度/高度参数部分 mmdc 版本不支持（unknown option '-w'）→ 失败即重试
            # 无尺寸参数的最简命令（尺寸由 mermaid 默认视图决定）。降级纪律同 §2.1。
            base = ["mmdc", "-i", a["src"], "-o", str(png), "-b", RASTER["background"]]
            with_size = base + ["-w", str(RASTER["width"]), "-H", str(RASTER["height"])]
            cmd = ("with-fallback", with_size, base)
        elif deps.get("npx"):
            base = ["npx", "-y", "@mermaid-js/mermaid-cli", "-i", a["src"],
                    "-o", str(png), "-b", RASTER["background"]]
            cmd = ("with-fallback",
                   base + ["-w", str(RASTER["width"]), "-H", str(RASTER["height"])],
                   base)

        if cmd is None:
            a["raster"] = "no-tool"
            failed.append(a["stem"])
            continue

        try:
            # 参数容错（E-3）：带尺寸参数失败时重试一次最简命令（部分 mmdc 版本
            # 不支持 -w/-H，报 unknown option）。两次都失败才算失败。
            if isinstance(cmd, tuple) and cmd[0] == "with-fallback":
                r = subprocess.run(cmd[1], capture_output=True, text=True,
                                   timeout=RASTER["timeout_sec"])
                if r.returncode != 0 or not png.is_file():
                    log(f"带尺寸参数失败（{(r.stderr or '').strip()[:80]}），重试最简命令", "WARN")
                    r = subprocess.run(cmd[2], capture_output=True, text=True,
                                       timeout=RASTER["timeout_sec"])
            else:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=RASTER["timeout_sec"])
            if r.returncode == 0 and png.is_file():
                a["png"] = str(png)
                a["raster"] = "ok"
            else:
                a["raster"] = "failed"
                failed.append(a["stem"])
                log(f"栅格化失败 {a['stem']}（exit {r.returncode}）："
                    f"{(r.stderr or '').strip()[:200]}", "WARN")
        except subprocess.TimeoutExpired:
            a["raster"] = "timeout"
            failed.append(a["stem"])
            log(f"栅格化超时 {a['stem']}（>{RASTER['timeout_sec']}s）", "WARN")
        except OSError as e:
            a["raster"] = "error"
            failed.append(a["stem"])
            log(f"栅格化异常 {a['stem']}：{e}", "WARN")

    ok = sum(1 for a in assets if a["raster"] == "ok")
    log(f"栅格化结果：成功 {ok} / {len(assets)}；未栅格化 {len(failed)}"
        + (f" → {failed}" if failed else ""))
    return assets


# ──────────────────────────────────────────────────────────── 生成 docx 用 md
def build_intermediate_md(text: str, assets: list[dict]) -> str:
    """把代码块替换为图片引用或占位框，产出 pandoc 输入（docx 专用中间稿）。

    两处与交付 md 的**有意差异**（md 是源，docx 是渲染态）：
      1. Mermaid/SVG 代码块 → 图片引用 或 降级占位框
      2. 图位占位标记 `[图 X-Y：...]` → **移除**
         理由：该标记是写作期内部标记（指示"此处放图"）。docx 里图已插入，
         保留会让读者看到 `[图 1-1：xxx]` 与题注 `图 1-1 xxx` 重复两遍。
         md 中保留（供校验与溯源），docx 中移除。

    **替换复用落盘侧的配对结果（E-1 修复，2026-10-30）**：旧实现在这里用
    `zip(reversed(assets), reversed(fences))` **按下标**重新配对——落盘侧明明已按
    位置就近匹配，替换侧却又按下标对一次，orphan 代码块存在时两者必然错位
    （图 1-1 的位置被塞进 orphan 图）。现改为：assets 里记录其源码在原文中的
    偏移（`fence_start`），替换直接按偏移定位，两侧永不分歧。
    """
    # 按 fence_start 建立偏移 → 资产映射（orphan 资产也带自己的偏移）
    by_start = {a["fence_start"]: a for a in assets if "fence_start" in a}
    out = text
    # 逆序替换，避免位移影响后续匹配
    for m in sorted(RE_FENCE.finditer(text), key=lambda x: -x.start()):
        a = by_start.get(m.start())
        if a is None:
            # 无主代码块（理论上落盘侧已全部处理；防御性保留原样）
            log(f"⚠️  偏移 {m.start()} 的代码块未匹配到资产，docx 中保留源码", "WARN")
            continue
        if a.get("png"):
            repl = f"![]({a['png']})"
        else:
            repl = (f"> **［图 {a['stem']}：栅格化工具不可用，"
                    f"矢量源码见交付 md 源文件］**\n>\n> 源码文件：`{a['src']}`")
        out = out[:m.start()] + repl + out[m.end():]

    # 移除图位占位标记（docx 渲染态不需要；md 源仍保留）
    out = RE_FIGURE_SLOT.sub("", out)
    # 清理因移除产生的连续空行（>2 行 → 2 行）
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


# ──────────────────────────────────────────────────────────── pandoc 构建
def run_pandoc(md_path: Path, docx_path: Path, reference_doc: str | None) -> bool:
    cmd = ["pandoc", str(md_path), "-f", "markdown", "-t", "docx",
           "-o", str(docx_path), "--toc", "--toc-depth=3"]
    if reference_doc:
        cmd += [f"--reference-doc={reference_doc}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"pandoc 失败（exit {r.returncode}）：{(r.stderr or '').strip()[:400]}", "ERROR")
        return False
    return docx_path.is_file()


# ──────────────────────────────────────────────────────────── docx 后处理
def postprocess_docx(docx_path: Path, chapter_title: str) -> bool:
    """python-docx 后处理：中文字体 / 字号 / 行距 / 缩进 / 题注居中 / 页眉页脚。"""
    try:
        from docx import Document
        from docx.shared import Pt, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
    except ImportError:
        log("python-docx 不可用，跳过后处理（docx 仍可用 pandoc 默认样式）", "WARN")
        return True

    def set_font(style, name: str, size: float, bold: bool | None = None):
        style.font.name = name
        style.font.size = Pt(size)
        if bold is not None:
            style.font.bold = bold
        # 中文字体必须设 eastAsia，否则 Word 里回落成西文字体
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.get_or_add_rFonts()
        rfonts.set(qn("w:eastAsia"), name)

    try:
        doc = Document(str(docx_path))
    except Exception as e:
        log(f"docx 打开失败：{e}", "ERROR")
        return False

    # 正文
    try:
        normal = doc.styles["Normal"]
        set_font(normal, TYPESET["body_font"], TYPESET["body_size_pt"])
        pf = normal.paragraph_format
        pf.line_spacing = TYPESET["line_spacing"]
        pf.first_line_indent = Pt(TYPESET["first_line_indent_pt"])
    except KeyError:
        pass

    # 标题
    for style_name, font, size in (
        ("Heading 1", TYPESET["h1_font"], TYPESET["h1_size_pt"]),
        ("Heading 2", TYPESET["h2_font"], TYPESET["h2_size_pt"]),
        ("Heading 3", TYPESET["h3_font"], TYPESET["h3_size_pt"]),
    ):
        try:
            set_font(doc.styles[style_name], font, size, bold=True)
        except KeyError:
            pass

    # 题注居中 + 五号
    for p in doc.paragraphs:
        if RE_CAPTION.match(p.text.strip()):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.font.size = Pt(TYPESET["caption_size_pt"])

    # 页边距
    m = TYPESET["page_margins_cm"]
    for sec in doc.sections:
        sec.top_margin = Cm(m["top"])
        sec.bottom_margin = Cm(m["bottom"])
        sec.left_margin = Cm(m["left"])
        sec.right_margin = Cm(m["right"])
        # 页眉：章标题；页脚：页码
        try:
            hp = sec.header.paragraphs[0]
            hp.text = chapter_title or ""
            hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        except (IndexError, AttributeError):
            pass
        try:
            fp = sec.footer.paragraphs[0]
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # 插入 PAGE 域（Word 打开时自动更新）
            run = fp.add_run()
            fld_begin = run._r.add_fldChar("begin")
            instr = run._r.add_instrText("PAGE")
            fld_end = run._r.add_fldChar("end")
        except (IndexError, AttributeError):
            pass

    doc.save(str(docx_path))
    return True


# ──────────────────────────────────────────────────────────── main
def main() -> int:
    ap = argparse.ArgumentParser(description="大学教材书稿构建器（md 源 → docx 交付）")
    ap.add_argument("--work-root", required=True, help="WORK_ROOT 路径")
    ap.add_argument("--chapter", required=True, help="如 ch01")
    ap.add_argument("--textbook", default="教材", help="教材名（--assemble 时用于产物命名）")
    ap.add_argument("--assemble", action="store_true",
                    help="交付 md 不存在时，从 章节/{ch##}/ 装配")
    ap.add_argument("--format", default="md,docx", help="构建格式，逗号分隔（默认 md,docx）")
    ap.add_argument("--reference-doc", default=None, help="pandoc 版式模板（覆写内置默认）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不落盘产物")
    ap.add_argument("--report", default=None, help="构建报告 JSON 落盘路径")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    if not work_root.is_dir():
        log(f"WORK_ROOT 不存在：{work_root}", "ERROR")
        return 2

    chapter = args.chapter
    chapter_dir = work_root / "章节" / chapter
    asset_dir = chapter_dir / "figures" / "assets"

    # 依赖
    deps = check_deps()
    log(f"依赖检查：pandoc={deps['pandoc'] or 'MISSING'} "
        f"python-docx={deps['python_docx'] or 'MISSING'} "
        f"mmdc={deps['mmdc'] or 'MISSING'} npx={deps['npx'] or 'MISSING'}")
    if not deps["pandoc"] or not deps["python_docx"]:
        log("硬依赖缺失（pandoc / python-docx）——不降级，直接失败"
            "（装法：brew install pandoc && pip install python-docx）", "ERROR")
        return 3

    # 输入
    md_path = find_delivery_md(work_root, chapter)
    if md_path is None:
        if not args.assemble:
            log(f"未找到 交付/*_{chapter}.md；加 --assemble 可从 章节/{chapter}/ 装配", "ERROR")
            return 2
        md_path = assemble_md(work_root, chapter, args.textbook)
    log(f"输入 md：{md_path}")

    text = md_path.read_text(encoding="utf-8")
    slots = RE_FIGURE_SLOT.findall(text)
    log(f"扫描到图位 {len(slots)} 个")

    if args.dry_run:
        print(json.dumps({
            "input_md": str(md_path),
            "figure_slots": [f"{c}-{s}" for c, s, _ in slots],
            "planned_assets_dir": str(asset_dir),
            "planned_docx": str(md_path.with_suffix(".docx")),
            "deps": deps,
            "dry_run": True,
        }, ensure_ascii=False, indent=2))
        return 0

    # 图表：落盘源码 → 栅格化
    assets = write_source_assets(text, chapter, asset_dir)
    if assets:
        assets = rasterize(assets, asset_dir, deps)

    report = {
        "chapter": chapter,
        "input_md": str(md_path),
        "figure_slots": len(slots),
        "assets": assets,
        "rasterized": sum(1 for a in assets if a.get("raster") == "ok"),
        "not_rasterized": [a["stem"] for a in assets if a.get("raster") != "ok"],
    }

    # docx
    if "docx" in args.format:
        inter_md = build_intermediate_md(text, assets)
        tmp_dir = Path(tempfile.mkdtemp(prefix="build_manuscript_"))
        tmp_md = tmp_dir / f"{md_path.stem}__docx_src.md"
        tmp_md.write_text(inter_md, encoding="utf-8")

        docx_path = md_path.with_suffix(".docx")
        if not run_pandoc(tmp_md, docx_path, args.reference_doc):
            return 4

        # 章标题取第一个 # 行
        m = re.search(r"^#\s+(.+)$", text, re.M)
        chapter_title = m.group(1).strip() if m else ""
        if not postprocess_docx(docx_path, chapter_title):
            return 4

        report["docx"] = str(docx_path)
        report["docx_bytes"] = docx_path.stat().st_size
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log(f"docx 构建完成：{docx_path}（{report['docx_bytes']} 字节）")

    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        log(f"构建报告：{args.report}")

    if report["not_rasterized"]:
        log(f"⚠️  {len(report['not_rasterized'])} 个图表未栅格化（已保留源码 + 占位框，"
            f"质量报告必须显式列出）：{report['not_rasterized']}", "WARN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
