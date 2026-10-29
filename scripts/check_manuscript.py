#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_manuscript.py — 大学教材书稿校验器（门禁 4）

==============================================================================
校验交付书稿的 md（源）与 docx（交付）两套产物是否合规。
判据来源：skills/manuscript-delivery/SKILL.md §4「校验项（门禁 4）」。

用法
------------------------------------------------------------------------------
  python3 scripts/check_manuscript.py --work-root "$WORK_ROOT" --chapter ch01
  python3 scripts/check_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 --strict
  python3 scripts/check_manuscript.py --work-root "$WORK_ROOT" --chapter ch01 --json

退出码
------------------------------------------------------------------------------
  0 全部通过（可能有 WARN）
  1 --strict 下存在 FAIL（或 --require-raster 下存在未栅格化图表）
  2 输入缺失（交付 md 或 docx 找不到）

判据
------------------------------------------------------------------------------
  4.1 md 标题层级无跳级（# 后直接 ###）
  4.2 图/表题注编号连续，且与图位一一对应
  4.3 交叉引用目标可解析（[见 §1.2] / [见图 1-3]）
  4.4 参考文献编号连续 + 基本格式合规
  4.5 docx 可打开 + 标题层级完整
  4.6 md 与 docx 图数一致（docx 媒体数 == 栅格化成功数）
  4.7 净字数 ±5%（以 count_net_words.py 脚本值为准）
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from count_net_words import count_net_words  # 复用既有 SSOT，禁止自行重算
except ImportError:  # pragma: no cover
    count_net_words = None

# 必须 re.M：`^…$` 缺省只匹配整串首尾，标题行将永不命中
RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
RE_FIGURE_SLOT = re.compile(r"\[图\s*(\d+)-(\d+)：([^\]]*)\]")
RE_CAPTION_LINE = re.compile(r"^\s*(图|表)\s*(\d+)-(\d+)\s")
RE_XREF_SEC = re.compile(r"\[见\s*§(\d+(?:\.\d+)*)\]")
RE_XREF_FIG = re.compile(r"\[见图\s*(\d+)-(\d+)\]")
RE_REF_ITEM = re.compile(r"^\[(\d+)\]\s+(.*)$")
RE_YEAR = re.compile(r"(1[89]\d{2}|20\d{2})")


class Result:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, cid: str, desc: str, ok: bool, detail: str = "", level: str = "FAIL"):
        self.items.append({"id": cid, "desc": desc, "ok": bool(ok),
                           "detail": detail, "level": level if not ok else "PASS"})

    def warn(self, cid: str, desc: str, detail: str = ""):
        self.add(cid, desc, False, detail, level="WARN")

    @property
    def failures(self):
        return [i for i in self.items if i["level"] == "FAIL"]

    @property
    def warns(self):
        return [i for i in self.items if i["level"] == "WARN"]


def find_delivery(work_root: Path, chapter: str, suffix: str) -> Path | None:
    d = work_root / "交付"
    if not d.is_dir():
        return None
    hits = sorted(d.glob(f"*_{chapter}.{suffix}"))
    return hits[0] if hits else None


# ── 4.1 标题层级
def check_headings(text: str, r: Result):
    levels = [len(m.group(1)) for m in RE_HEADING.finditer(text)]
    jumps = [(i, levels[i - 1], lv) for i, lv in enumerate(levels)
             if i > 0 and lv - levels[i - 1] > 1]
    if not levels:
        r.add("4.1", "md 存在标题层级", False, "文件无任何标题")
        return
    r.add("4.1", "md 标题层级无跳级（相邻层级差 ≤1）", not jumps,
          f"跳级位置（序号, 上层, 本层）: {jumps}")


# ── 4.2 题注编号连续 + 与图位一一对应
def check_captions(text: str, r: Result):
    slots = [(f"{a}-{b}", t.strip()) for a, b, t in RE_FIGURE_SLOT.findall(text)]
    caps = []
    for line in text.splitlines():
        m = RE_CAPTION_LINE.match(line)
        if m and m.group(1) == "图":
            caps.append(f"{m.group(2)}-{m.group(3)}")

    # 图位与图题注一一对应
    missing_cap = [s for s, _ in slots if s not in caps]
    r.add("4.2a", "每个图位都有对应图题注", not missing_cap, f"缺题注的图位: {missing_cap}")

    # 序号连续（按章内序号递增，步长为 1）
    seqs = []
    for s in caps:
        try:
            seqs.append(int(s.split("-")[1]))
        except (IndexError, ValueError):
            pass
    gaps = []
    for i, v in enumerate(seqs):
        if i > 0 and v != seqs[i - 1] + 1:
            gaps.append((seqs[i - 1], v))
    r.add("4.2b", "图题注编号连续（步长 1，无跳号）", not gaps, f"断号处: {gaps}")


# ── 4.3 交叉引用可解析
def check_xrefs(text: str, r: Result):
    headings = [m.group(2).strip() for m in RE_HEADING.finditer(text)]
    # 收集形如 "1.2 xxx" / "1.2.3 xxx" 的节号
    sec_nums = set()
    for h in headings:
        m = re.match(r"^(\d+(?:\.\d+)+)\s", h)
        if m:
            sec_nums.add(m.group(1))
    fig_nums = {f"{a}-{b}" for a, b, _ in RE_FIGURE_SLOT.findall(text)}

    bad_sec = [s for s in RE_XREF_SEC.findall(text) if s not in sec_nums]
    bad_fig = [f"{a}-{b}" for a, b in RE_XREF_FIG.findall(text) if f"{a}-{b}" not in fig_nums]
    r.add("4.3a", "交叉引用 [见 §X.Y] 目标节号真实存在", not bad_sec,
          f"悬空引用: {bad_sec}（现有节号: {sorted(sec_nums)}）")
    r.add("4.3b", "交叉引用 [见图 X-Y] 目标图号真实存在", not bad_fig,
          f"悬空引用: {bad_fig}（现有图号: {sorted(fig_nums)}）")


# ── 4.4 参考文献
def check_refs(text: str, r: Result):
    m = re.search(r"^##\s*参考文献\s*$", text, re.M)
    if not m:
        r.warn("4.4", "存在参考文献节", "未找到 '## 参考文献' 标题")
        return
    tail = text[m.end():]
    nums, bad_year = [], []
    for line in tail.splitlines():
        mm = RE_REF_ITEM.match(line.strip())
        if mm:
            nums.append(int(mm.group(1)))
            if not RE_YEAR.search(mm.group(2)):
                bad_year.append(mm.group(1))
    if not nums:
        r.warn("4.4", "参考文献条目非空", "参考文献节无任何 [n] 条目")
        return
    seq_ok = nums == list(range(1, len(nums) + 1))
    r.add("4.4a", "参考文献编号从 1 连续递增", seq_ok, f"实际编号: {nums}")
    r.add("4.4b", "每条参考文献含出版年份（GB/T 7714 基本合规）", not bad_year,
          f"缺年份条目: {bad_year}")


# ── 4.5 docx 可打开 + 标题层级
def check_docx(docx_path: Path, r: Result) -> int:
    """返回 docx 内嵌媒体数（图片数）；打不开返回 -1。"""
    if not docx_path.is_file():
        r.add("4.5", "docx 产物存在", False, f"未找到: {docx_path}")
        return -1
    try:
        import docx as _docx  # noqa: F401
    except ImportError:
        r.warn("4.5", "python-docx 可用（docx 深度校验依赖）",
               "未安装 python-docx，跳过 4.5/4.6 深度校验")
        return -1

    try:
        with zipfile.ZipFile(docx_path) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
    except zipfile.BadZipFile:
        r.add("4.5a", "docx 是合法 zip（可被 Word 打开）", False, "BadZipFile")
        return -1
    r.add("4.5a", "docx 是合法 zip（可被 Word 打开）", True)

    try:
        from docx import Document
        d = Document(str(docx_path))
        h1 = sum(1 for p in d.paragraphs if p.style.name == "Heading 1")
        h2 = sum(1 for p in d.paragraphs if p.style.name == "Heading 2")
        r.add("4.5b", "docx 含 Heading 1（章标题）", h1 >= 1, f"H1 数量={h1}")
        r.add("4.5c", "docx 含 Heading 2（节标题）", h2 >= 1, f"H2 数量={h2}")
    except Exception as e:
        r.add("4.5b", "docx 可被 python-docx 解析", False, str(e)[:200])
    return len(media)


# ── 4.7 净字数
def check_words(md_path: Path, target: int | None, r: Result):
    if count_net_words is None:
        r.warn("4.7", "净字数校验（依赖 count_net_words.py）", "脚本不可用，跳过")
        return
    res = count_net_words(md_path.read_text(encoding="utf-8"))
    # 键名以 net_final 为准（count_net_words.py 的实际返回）；保留 net 兜底防改名断裂
    net = res.get("net_final", res.get("net", 0))
    if target is None:
        # 从 frontmatter 取字数目标
        m = re.search(r"^字数目标:\s*(\d+)", md_path.read_text(encoding="utf-8"), re.M)
        target = int(m.group(1)) if m else None
    if not target:
        r.warn("4.7", "净字数校验", f"未给定字数目标；实测净字数={net}")
        return
    dev = abs(net - target) / target
    r.add("4.7", f"净字数 {net} 在目标 {target} 的 ±5% 内（偏差 {dev:.1%}）",
          dev <= 0.05, f"实测 {net} / 目标 {target} / 偏差 {dev:.1%}")


def main() -> int:
    ap = argparse.ArgumentParser(description="大学教材书稿校验器（门禁 4）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--target", type=int, default=None, help="字数目标（缺省取 frontmatter）")
    ap.add_argument("--strict", action="store_true", help="存在 FAIL 即 exit 1")
    ap.add_argument("--require-raster", action="store_true",
                    help="未栅格化图表也判 FAIL（默认仅 WARN，因 mmdc 可能不可用）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    md_path = find_delivery(work_root, args.chapter, "md")
    if md_path is None:
        print(f"[ERROR] 未找到 交付/*_{args.chapter}.md", file=sys.stderr)
        return 2
    text = md_path.read_text(encoding="utf-8")

    r = Result()
    check_headings(text, r)
    check_captions(text, r)
    check_xrefs(text, r)
    check_refs(text, r)
    check_words(md_path, args.target, r)

    docx_path = find_delivery(work_root, args.chapter, "docx")
    media = check_docx(docx_path, r) if docx_path else -1
    if docx_path is None:
        r.warn("4.6", "docx 产物存在（图数一致性依赖）", "未构建 docx，跳过 4.6")

    # 4.6 图数一致：docx 媒体数 == 栅格化成功数
    asset_dir = work_root / "章节" / args.chapter / "figures" / "assets"
    n_slots = len(RE_FIGURE_SLOT.findall(text))
    if asset_dir.is_dir():
        pngs = sorted(asset_dir.glob("*.png"))
    else:
        pngs = []
    n_png = len(pngs)

    if media >= 0:
        r.add("4.6a", f"docx 内嵌图数({media}) == 栅格化成功数({n_png})",
              media == n_png, f"docx media={media} / png={n_png}")
    if n_png < n_slots:
        lv = "FAIL" if args.require_raster else "WARN"
        r.add("4.6b", f"全部图表已栅格化（{n_png}/{n_slots}）", False,
              f"未栅格化 {n_slots - n_png} 个；交付时必须在质量报告显式列出", level=lv)

    if args.json:
        print(json.dumps({"items": r.items,
                          "failures": len(r.failures),
                          "warns": len(r.warns)}, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"书稿校验（门禁 4）| {md_path.name}")
        print("=" * 62)
        for i in r.items:
            mark = "✓" if i["ok"] else ("⚠" if i["level"] == "WARN" else "✗")
            print(f"  {mark} [{i['id']}] {i['desc']}")
            if not i["ok"] and i["detail"]:
                print(f"        → {i['detail']}")
        print("-" * 62)
        print(f"FAIL {len(r.failures)} | WARN {len(r.warns)} | PASS "
              f"{sum(1 for i in r.items if i['ok'])}")
        print("=" * 62)

    if args.require_raster and any(i["id"] == "4.6b" and not i["ok"] for i in r.items):
        return 1
    return 1 if (args.strict and r.failures) else 0


if __name__ == "__main__":
    sys.exit(main())
