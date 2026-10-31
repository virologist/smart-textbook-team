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
# ── 审稿修订标记（v1.1.0 方案甲：md 承载修订语义 → pandoc 渲染 Word 真修订）──
# 插入/删除 span：[文本]{.insertion author="X" date="D"} / [文本]{.deletion author="X" date="D"}
# re.S：回流后 pandoc 会把长 span 折行（author 与 date 可能分行），须跨行匹配
RE_REVISION = re.compile(
    r"\[(?P<text>[^\]]+)\]\{(?P<kind>\.insertion|\.deletion)\s+"
    r'author="(?P<author>[^"]*)"\s+date="(?P<date>[^"]*)"\}',
    re.S,
)
# 校稿结论节（PROOFREAD 三件套的落点，ASSEMBLE 转写）
RE_PROOFREAD_SECTION = re.compile(r"^##\s+校稿结论\s*$", re.M)
# 构建指纹（R5 红队修复 b2「无修订标记的静默篡改」盲区）：
# 正文 hash 写入 docx 核心属性 → check_manuscript 4.13d 比对，
# 改 docx 任何内容（改字/删段）不回流 → 指纹不一致 FAIL——修订数比对拦不住的盲区由它兜底
FINGERPRINT_KEY = "STT_MANUSCRIPT_FINGERPRINT"


def manuscript_fingerprint(text: str) -> str:
    """交付 md 正文（去 frontmatter）的 sha256 前 16 位——docx 指纹锚。"""
    import hashlib
    _, body = _split_frontmatter(text)
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:16]


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


# ──────────────────────────────────────────────── 溯源表自动生成（v1.1.0）
def generate_provenance(work_root: Path, chapter: str, textbook: str, text: str) -> Path | None:
    """把 examiner R3 的 r3_verification_log.md 转写为溯源表（不改内容只转格式）。

    此前 §4.1 只在规范里写「ASSEMBLE 据此转写」但无人执行——溯源表从不落盘。
    判据 4.12 要求溯源表是交付必备件，故 --assemble 时自动生成；日志缺失 → WARN + None
    （由 check_manuscript 4.12 判 FAIL，不在这里静默放过）。
    """
    log_path = work_root / "章节" / chapter / "review" / "r3_verification_log.md"
    if not log_path.is_file():
        log(f"溯源表源缺失：{log_path}（examiner R3 未落盘核验日志）→ "
            "溯源表无法生成，交付时判据 4.12 将 FAIL", "WARN")
        return None

    n_shi = len(re.findall(r"\[实[·\]]", text))   # 正文 [实]/[实·xx] 出现处数
    rows = []
    n_skipped = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|--") or line.startswith("| 位置"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # R5 红队列错位修复：examiner 契约 4 列 = 位置|标识符|结果|动作；
        # 溯源 5 列 = 序|位置|陈述要点|标识符/来源|核验状态。
        # 语义映射：核验状态=动作列；陈述要点=结果列；「标识符/来源」=标识符列（不再是结果文案）。
        if len(cells) >= 4:
            pos, ident, result, action = cells[0], cells[1], cells[2], cells[3]
            rows.append([pos, result, ident, action])
        else:
            n_skipped += 1
    if n_skipped:
        log(f"r3 日志有 {n_skipped} 行格式异常（列数 <4）已跳过——建议回 examiner 修日志", "WARN")

    out = work_root / "交付" / f"{textbook}_{chapter}.溯源.md"
    lines = [
        f"# {textbook} {chapter} 溯源表",
        "",
        "> 由 `build_manuscript.py --assemble` 从 examiner R3 核验日志自动转写（不改内容只转格式）。",
        f"> 正文 `[实]` 处数：{n_shi} ｜ 溯源行数：{len(rows)} ｜ 二者应相等（判据 4.12）。",
        "",
        "| 序 | 正文位置 | 陈述要点 | 标识符/来源 | 核验状态 |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(rows, 1):
        lines.append("| " + " | ".join([str(i)] + c) + " |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"溯源表已生成：{out}（{len(rows)} 行）")
    return out


# ──────────────────────────────────────────── 校稿结论转写（v1.1.0 §4.2）
def append_proofread_conclusion(work_root: Path, chapter: str, md_path: Path) -> bool:
    """把 PROOFREAD 三件套（校对后稿+修订记录）的结论转写进交付 md 的「校稿结论」节。

    PROOFREAD 断链修复：此前「校对后稿」无人产出、校稿结论无落点。
    校对后稿缺失 → 不阻塞装配（PROOFREAD 可能尚未跑），但结论缺失会被 4.13c 拦在 DELIVER。
    """
    if RE_PROOFREAD_SECTION.search(md_path.read_text(encoding="utf-8")):
        log("交付 md 已含校稿结论节，跳过转写")
        return True

    rev_path = work_root / "章节" / chapter / "review" / "proofread_revisions.md"
    pr_path = work_root / "章节" / chapter / "review" / "proofread.md"
    n_ins = n_del = 0
    # R5 红队修复：兜底文本不能含「结论:」可解析形态——否则三件套缺失也被 4.13c 漂绿
    verdict, pending = "校稿未完成（PROOFREAD 三件套缺失，交付前必须补齐）", "—"
    if rev_path.is_file():
        rev_text = rev_path.read_text(encoding="utf-8")
        # 修订计数只认**修订标记语法**（与正文 §1.5 同源），不认表格叙述里的字面量
        n_ins = len(RE_REVISION.findall(rev_text))
        n_del = sum(1 for m in RE_REVISION.finditer(rev_text)
                    if m.group("kind") == ".deletion")
        m = re.search(r"^结论[:：]\s*(.+)$", rev_text, re.M)
        if m:
            verdict = m.group(1).strip()
        m2 = re.search(r"^遗留待办[:：]\s*(.+)$", rev_text, re.M)
        if m2:
            pending = m2.group(1).strip()
    src = pr_path.name if pr_path.is_file() else "（校对后稿未产出）"

    section = (
        "\n\n## 校稿结论\n\n"
        f"- **结论**：{verdict}\n"
        f"- **修订计数**：插入 {n_ins} 处 / 删除 {n_del} 处\n"
        f"- **校对后稿**：`章节/{chapter}/review/{src}`\n"
        f"- **遗留待办**：{pending}\n"
        f"- **生成方式**：ASSEMBLE 由 review/proofread_revisions.md 自动转写（判据 4.13c）\n"
    )
    with md_path.open("a", encoding="utf-8") as f:
        f.write(section)
    log(f"校稿结论已写入：{md_path.name}（插入 {n_ins} / 删除 {n_del}｜结论：{verdict}）")
    return True


def chapter_title_placeholder(text: str) -> str:
    """取第一个 # 行作章标题（与主构建分支同逻辑，抽出避免重复）。"""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


# ──────────────────────────────────────────── Word 审改回流（v1.1.0 §5.2）
def apply_revisions(work_root: Path, chapter: str, from_docx: Path,
                    mode: str = "accept") -> int:
    """把 Word 里审改后的 docx 回流为交付 md（防 md/docx 分叉）。

    mode: accept=接受全部修订（净稿语义）；reject=拒绝全部（保留原文）；
          all=保留修订标记（审稿意见入库 md 源）。逐字对齐 pandoc --track-changes 语义。
    """
    if not from_docx.is_file():
        log(f"回流源 docx 不存在：{from_docx}", "ERROR")
        return 2
    md_path = find_delivery_md(work_root, chapter)
    if md_path is None:
        log(f"未找到交付 md（交付/*_{chapter}.md），无法回流", "ERROR")
        return 2
    tmp_dir = Path(tempfile.mkdtemp(prefix="apply_revisions_"))
    tmp_md = tmp_dir / f"{md_path.stem}__backflow.md"
    cmd = ["pandoc", str(from_docx), "-f", "docx", "-t", "markdown",
           f"--track-changes={mode}", "-o", str(tmp_md)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"回流失败（pandoc exit {r.returncode}）：{(r.stderr or '')[:300]}", "ERROR")
        return 4
    # 回流文本替换交付 md 正文（保留 frontmatter——docx 里没有元数据）
    old_text = md_path.read_text(encoding="utf-8")
    fm, _ = _split_frontmatter(old_text)
    new_body = tmp_md.read_text(encoding="utf-8").strip()
    # 回流清洗（pandoc docx→md 的三类噪声）：
    # ① TOC 伪标题（pandoc --toc 生成的「Table of Contents」行——带不带属性块都清，
    #    R5 红队实测 3.13 输出无属性块，旧正则失效 → 净稿永久残留伪章标题）
    new_body = re.sub(r"^#\s*Table of Contents.*\n+", "", new_body, flags=re.M | re.I)
    # ② 转义方括号 \[实\] → [实]（docx 无 md 转义概念，pandoc 保守转义）
    new_body = new_body.replace("\\[", "[").replace("\\]", "]")
    # ③ 图位标记恢复（R5 红队高危：docx 渲染态已删 [图 X-Y：…] 占位行，回流以 docx 为准
    #    会把图位永久蒸发 → 4.10/4.6a 静默 N/A、图与题注关系丢失）。恢复：旧 md 有而回流稿
    #    缺失的图位行，按其题注行定位重新插入题注之前；无题注则附文末。
    old_body = _split_frontmatter(old_text)[1]
    restored = 0
    for sm in RE_FIGURE_SLOT.finditer(old_body):
        slot_line = sm.group(0)
        if slot_line in new_body:
            continue
        stem = f"{sm.group(1)}-{sm.group(2)}"
        cm = re.search(rf"^\s*图\s*{re.escape(stem)}\s+.*$", new_body, re.M)
        if cm:
            new_body = new_body[:cm.start()] + slot_line + "\n\n" + new_body[cm.start():]
        else:
            new_body = new_body.rstrip() + "\n\n" + slot_line + "\n"
        restored += 1
    if restored:
        log(f"回流恢复了 {restored} 个被 docx 渲染态删除的图位标记", "WARN")
    # ④ frontmatter 实际净字数重算（回流改变了正文）
    try:
        from count_net_words import count_net_words
        fm = re.sub(r"^实际净字数:.*$", f"实际净字数: {count_net_words(new_body).get('net_final', 0)}",
                    fm, flags=re.M)
    except Exception:
        pass
    md_path.write_text((f"---\n{fm}\n---\n\n{new_body}\n" if fm else new_body + "\n"),
                       encoding="utf-8")
    # 校稿结论节是内部 QA 元数据，docx 审阅版已剔除 → 回流后丢失，此处按 review/ 记录补写回
    append_proofread_conclusion(work_root, chapter, md_path)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    n_marks = len(RE_REVISION.findall(new_body))
    log(f"回流完成：{md_path}（mode={mode}，残留修订标记 {n_marks} 处）")
    log("⚠️  交付 docx 已过时，必须回 md 重建（改而不回流 = 铁律违规，判据 4.13b 拦截）", "WARN")
    return 0


# ──────────────────────────────────────────────────────────── docx 后处理
def docx_text_fingerprint(docx_path: Path) -> str:
    """docx **document.xml 原始字节**（含修订标记全部内容）的 hash——校验侧可重算。

    R5 教训：python-docx 的 paragraphs **看不到 w:ins/w:del 内的 run**（修订内文本
    对其不可见）——基于它的 hash 拦不住修订内文本篡改。document.xml 原始字节覆盖
    全部内容（正文+修订+属性引用），任何 XML 级改动都会改变 hash。
    """
    import hashlib
    import zipfile as _zf
    try:
        with _zf.ZipFile(str(docx_path)) as z:
            raw = z.read("word/document.xml")
        return hashlib.sha256(raw).hexdigest()[:16]
    except Exception:
        return ""


def postprocess_docx(docx_path: Path, chapter_title: str,
                     fingerprint: str | None = None) -> bool:
    """python-docx 后处理：中文字体 / 字号 / 行距 / 缩进 / 题注居中 / 页眉页脚。

    收尾时计算 **docx 渲染文本自身 hash** 写入核心属性（4.13d 双向锚）；
    fingerprint 参数（md 口径指纹）仍一并记录，供溯源。
    """
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

    # 双向锚（R5）：先 save 落定版式，再算**最终文本** hash 回写属性，再 save 一次
    doc.save(str(docx_path))
    text_fp = docx_text_fingerprint(docx_path)
    doc.core_properties.comments = (
        f"{FINGERPRINT_KEY}={text_fp}"
        + (f" md={fingerprint}" if fingerprint else "")
    )
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
    # ── v1.1.0 修订态交付链（方案甲）──
    ap.add_argument("--revisions", action="store_true",
                    help="构建审阅版 docx：md 修订标记 → Word 真修订态（交付/{教材名}_{ch##}_审阅.docx）")
    ap.add_argument("--apply-revisions", dest="apply_revisions", action="store_true",
                    help="Word 审改回流：读 --from-docx 的修订，按 --revision-mode 处理后覆写交付 md")
    ap.add_argument("--from-docx", default=None,
                    help="--apply-revisions 的回流源 docx（审稿人改过的文件）")
    ap.add_argument("--revision-mode", dest="revision_mode",
                    choices=["accept", "reject", "all"], default="accept",
                    help="回流时如何处理 Word 修订（默认 accept=接受全部 → 净稿）")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    if not work_root.is_dir():
        log(f"WORK_ROOT 不存在：{work_root}", "ERROR")
        return 2

    chapter = args.chapter

    # 回流模式：独立分支，不走构建管线
    if args.apply_revisions:
        if not args.from_docx:
            log("--apply-revisions 需要 --from-docx 指明回流源", "ERROR")
            return 2
        return apply_revisions(work_root, chapter,
                               Path(args.from_docx).expanduser(), args.revision_mode)
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
    elif args.assemble:
        # v1.1.0 语义补强：交付 md 已存在 + 显式 --assemble = 以章节/ 为源重装
        # （旧语义只在 md 缺失时装配，导致 PROOFREAD 三件套完成后旧交付 md 永不更新——
        #  校稿结论/溯源表/修订标记全部断链；「交付 md 是源」的正源是 章节/draft.md，
        #  交付 md 是装配产物，重装不丢用户内容——draft.md 才是唯一编辑入口）
        log(f"交付 md 已存在但显式 --assemble → 从 章节/{chapter}/ 重新装配覆盖")
        md_path = assemble_md(work_root, chapter, args.textbook)
    # 溯源表 + 校稿结论：装配路径都会补（md 已存在但缺结论时同样转写）
    cur = md_path.read_text(encoding="utf-8")
    generate_provenance(work_root, chapter, args.textbook, cur)
    append_proofread_conclusion(work_root, chapter, md_path)
    log(f"输入 md：{md_path}")

    text = md_path.read_text(encoding="utf-8")
    slots = RE_FIGURE_SLOT.findall(text)
    n_rev = len(RE_REVISION.findall(text))
    log(f"扫描到图位 {len(slots)} 个；修订标记 {n_rev} 处"
        f"（插入 {len([m for m in RE_REVISION.finditer(text) if m.group('kind') == '.insertion'])}"
        f" / 删除 {len([m for m in RE_REVISION.finditer(text) if m.group('kind') == '.deletion'])}）")

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
        "revision_marks": n_rev,
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
        # 指纹锚 = **交付 md 全文正文**（与 check_manuscript 4.13d 同口径，R5）——
        # docx 是它的渲染态；锚点唯一目的=检测 docx 被改而不回流，口径一致才能比对。
        # （此前用 inter_md 算 → check 侧用交付 md 复算必然不等 = 正向恒 FAIL）
        fp_main = manuscript_fingerprint(text)
        if not postprocess_docx(docx_path, chapter_title, fingerprint=fp_main):
            return 4

        report["docx"] = str(docx_path)
        report["docx_bytes"] = docx_path.stat().st_size
        report["docx_fingerprint"] = fp_main
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log(f"docx 构建完成：{docx_path}（{report['docx_bytes']} 字节，指纹 {fp_main}）")

    # 审阅版（v1.1.0 方案甲）：修订标记 → Word 真修订态
    if args.revisions and "docx" in args.format:
        inter_md = build_intermediate_md(text, assets)
        # 审阅版剔除校稿结论节（内部 QA 产物，不进审阅对象）
        inter_review = RE_PROOFREAD_SECTION.split(inter_md)[0].rstrip() + "\n"
        rev_dir = Path(tempfile.mkdtemp(prefix="build_revisions_"))
        rev_md = rev_dir / f"{md_path.stem}__review_src.md"
        rev_md.write_text(inter_review, encoding="utf-8")
        review_docx = md_path.with_name(f"{md_path.stem}_审阅.docx")
        if not run_pandoc(rev_md, review_docx, args.reference_doc):
            return 4
        # 审阅版指纹 = 交付 md 去校稿结论节（其渲染源即此形态，R5 口径与 check 侧一致）
        fp_review = manuscript_fingerprint(
            RE_PROOFREAD_SECTION.split(text)[0].rstrip() + "\n")
        if not postprocess_docx(review_docx, chapter_title_placeholder(text),
                                fingerprint=fp_review):
            return 4
        report["review_docx"] = str(review_docx)
        report["review_revision_marks"] = n_rev
        report["review_fingerprint"] = fp_review
        shutil.rmtree(rev_dir, ignore_errors=True)
        log(f"审阅版构建完成：{review_docx}（含 {n_rev} 处 Word 修订，指纹 {fp_review}）")

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
