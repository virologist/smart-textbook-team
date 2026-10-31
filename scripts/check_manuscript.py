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
  4.0 frontmatter 七项必填
  4.1 md 标题层级无跳级（# 后直接 ###）
  4.2 图/表题注编号连续，且与图位一一对应
  4.3 交叉引用目标可解析（[见 §1.2] / [见图 1-3]）
  4.4 参考文献编号连续 + 基本格式合规
  4.5 docx 可打开 + 标题层级完整
  4.6 md 与 docx 图数一致（docx 媒体数 == 栅格化成功数）
  4.7 净字数 ±5%（以 count_net_words.py 脚本值为准）
  4.8 习题位编号连续 / 4.9 思政融入点存在
  4.10 数据图 notebook（assets/{图号}.ipynb 存在且 cell 结构合规；v1.1.0 补实现）
  4.11 术语一致性（对照 terminology-table.md：禁用写法零出现/别名并存/首见；v1.1.0 补实现）
  4.12 溯源表（存在 + [实] 条数==溯源行数；v1.1.0 补实现）
  4.13 修订态完整性（4.13a 标记成对合法 / 4.13b md==docx 修订数 / 4.13c 校稿结论；v1.1.0 新增）
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
# 多行模式说明：凡用 `^…$` 且需逐行判定的正则，一律带 re.M。
# 缺省时 `^`/`$` 只匹配整串首尾 → 判据静默失效（曾致 4.1「无任何标题」误报）。
RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
RE_FIGURE_SLOT = re.compile(r"\[图\s*(\d+)-(\d+)：([^\]]*)\]")
RE_TABLE_SLOT = re.compile(r"\[表\s*(\d+)-(\d+)：([^\]]*)\]")
# 题注行：行首直接是「图/表」+ 编号。**不允许 `[` 前缀**——
# 否则图位行 `[图 1-1：标题]` 会被同时计为「图位」和「题注」，
# 造成重复计数 → 4.2b 误报断号（实测：断号处 [(1,1)]）。
# 图位由 RE_FIGURE_SLOT / RE_TABLE_SLOT 单独识别，两者互不重叠。
RE_CAPTION_LINE = re.compile(r"^\s*(图|表)\s*(\d+)-(\d+)", re.M)
RE_XREF_SEC = re.compile(r"\[见\s*§(\d+(?:\.\d+)*)\]")
RE_XREF_FIG = re.compile(r"\[见图\s*(\d+)-(\d+)\]")
RE_REF_ITEM = re.compile(r"^\[(\d+)\]\s+(.*)$", re.M)
RE_YEAR = re.compile(r"(1[89]\d{2}|20\d{2})")
RE_EXERCISE = re.compile(r"\[习题\s*(\d+)-(\d+)\]")
RE_IDEOLOGY = re.compile(r"\[思政·([^\]]+)\]")
# frontmatter 七项（书稿元数据，见 manuscript-delivery §1.2）
FM_REQUIRED = ["教材名", "章节号", "章节标题", "字数目标", "实际净字数", "版本", "学科profile"]
# ── v1.1.0 新增判据的正则 ──
# 修订标记（与 build_manuscript.RE_REVISION 同源；re.S 因回流后 pandoc 折行）
RE_REVISION = re.compile(
    r"\[(?P<text>[^\]]+)\]\{(?P<kind>\.insertion|\.deletion)\s+"
    r'author="(?P<author>[^"]*)"\s+date="(?P<date>[^"]*)"\}',
    re.S,
)
RE_PROOFREAD_SECTION = re.compile(r"^##\s+校稿结论\s*$", re.M)
RE_PROOFREAD_VERDICT = re.compile(r"^\s*[-*]?\s*\**\s*结论\**[:：]\s*(\S+)", re.M)
# 数据图位识别（非纯示意）：兼容「数据来源：」「数据来源=」「数据来源 =」三种官方写法
# （R5 红队：manuscript-delivery §2 官方示例用「数据来源=」，只认冒号会整类逃检）
RE_DATA_FIG_HINT = re.compile(r"数据来源\s*[:：=]\s*(?!纯示意)")


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
    """定位交付物。多命中 = 歧义，报错而非静默取第一个（2026-10-30 修复）。"""
    d = work_root / "交付"
    hits = sorted(d.glob(f"*_{chapter}.{suffix}")) if d.is_dir() else []
    if not hits:
        return None
    if len(hits) > 1:
        print(f"[ERROR] 交付目录下 *_{chapter}.{suffix} 命中 {len(hits)} 个："
              f"{[h.name for h in hits]}；请清理重名文件后重跑", file=sys.stderr)
        sys.exit(2)
    return hits[0]


# ── 4.0 frontmatter 七项必填
def check_frontmatter(text: str, r: Result):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        r.add("4.0", "md 含 frontmatter（书稿元数据）", False,
              "文件未以 --- frontmatter 开头")
        return
    fm = m.group(1)
    missing = [k for k in FM_REQUIRED
               if not re.search(rf"^{re.escape(k)}\s*:", fm, re.M)]
    r.add("4.0", f"frontmatter 七项齐全（{'/'.join(FM_REQUIRED)}）",
          not missing, f"缺: {missing}")


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
def _seq_gaps(nums: list[int]) -> list[tuple]:
    gaps = []
    for i, v in enumerate(nums):
        if i > 0 and v != nums[i - 1] + 1:
            gaps.append((nums[i - 1], v))
    return gaps


def _nums(pairs: list[str]) -> list[int]:
    out = []
    for s in pairs:
        try:
            out.append(int(s.split("-")[1]))
        except (IndexError, ValueError):
            pass
    return out


def check_captions(text: str, r: Result):
    """图 + 表双向校验（2026-10-30：原实现只查图，表题注与 [表 X-Y] 完全未覆盖）。"""
    for kind, slot_re in (("图", RE_FIGURE_SLOT), ("表", RE_TABLE_SLOT)):
        slots = [f"{a}-{b}" for a, b, _ in slot_re.findall(text)]
        caps = [f"{m.group(2)}-{m.group(3)}"
                for m in RE_CAPTION_LINE.finditer(text) if m.group(1) == kind]
        if not slots and not caps:
            r.add(f"4.2-{kind}", f"{kind}：无 {kind}位（N/A）", True)
            continue
        missing_cap = [s for s in slots if s not in caps]
        r.add(f"4.2a-{kind}", f"每个{kind}位都有对应{kind}题注",
              not missing_cap, f"缺题注的{kind}位: {missing_cap}")
        gaps = _seq_gaps(_nums(caps))
        r.add(f"4.2b-{kind}", f"{kind}题注编号连续（步长 1，无跳号）",
              not gaps, f"断号处: {gaps}")


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


# ── 4.8 习题位 / 思政融入点（落实 manuscript-delivery §1.3 的标记要求）
def check_exercise_ideology(text: str, r: Result):
    exs = [f"{a}-{b}" for a, b in RE_EXERCISE.findall(text)]
    if exs:
        gaps = _seq_gaps(_nums(exs))
        r.add("4.8", f"习题位编号连续（{len(exs)} 个）", not gaps, f"断号处: {gaps}")
    else:
        r.warn("4.8", "存在习题位", "本章无 [习题 X-Y] 标记（教材通常需要）")
    ide = RE_IDEOLOGY.findall(text)
    if ide:
        r.add("4.9", f"思政融入点已标注（{len(ide)} 处）", True)
    else:
        r.warn("4.9", "存在思政融入点标记", "无 [思政·主题] 标记（教材通常要求 2-3% 占比）")


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


# ── 4.10 数据图 notebook（v1.1.0 补实现：此前仅规范声称、脚本零实现）
def check_data_figure_notebooks(text: str, work_root: Path, chapter: str, r: Result):
    """每个数据图位（数据来源非「纯示意」）必须配 assets/{图号}.ipynb，且 cell 结构合规。

    cell 契约（scientific-figure §1③）：≥4 cell，且含 markdown 说明 cell +
    原始数据 cell + 绘图代码 cell；「可执行」由 nbconvert 外部验证，这里查结构与数据内联。
    """
    import zipfile as _zf
    slots = RE_FIGURE_SLOT.findall(text)
    if not slots:
        r.add("4.10", "数据图 notebook 校验（本章无图位，N/A）", True)
        return
    # 逐图位判断是否数据图：图位标记块内「数据来源」非「纯示意」即数据图
    data_slots = []
    for m in re.finditer(r"\[图\s*(\d+)-(\d+)：([^\]]*)\][^\n]*", text):
        seg = text[m.start():m.start() + 400]
        if RE_DATA_FIG_HINT.search(seg):
            data_slots.append(f"{m.group(1)}-{m.group(2)}")
    if not data_slots:
        r.add("4.10", "数据图 notebook 校验（无数据图位，全部纯示意/概念图，N/A）", True)
        return
    asset_dir = work_root / "章节" / chapter / "figures" / "assets"
    missing, bad_struct = [], []
    for stem in data_slots:
        nb = asset_dir / f"{stem}.ipynb"
        if not nb.is_file():
            missing.append(stem)
            continue
        try:
            nb_json = json.loads(nb.read_text(encoding="utf-8"))
            cells = nb_json.get("cells", [])
            n_md = sum(1 for c in cells if c.get("cell_type") == "markdown")
            n_code = sum(1 if c.get("cell_type") == "code" else 0 for c in cells)
            # 结构：≥1 markdown（图说明）+ ≥2 code（数据 cell + 绘图/导出 cell）
            if len(cells) < 3 or n_md < 1 or n_code < 2:
                bad_struct.append(f"{stem}(cells={len(cells)},md={n_md},code={n_code})")
            else:
                # 数据内联抽查：code cell 须含**字面数据结构**（= 后跟 [/{ 或纯数字列表）。
                # R5 红队：旧正则 `\[.*\d.*\]` 会被 str(source) 的 repr 括号 + 文件名数字
                # 误命中（`pd.read_csv('data.csv'); savefig('1-1.png')` → 假 PASS）。
                # 现按 cell 原始行逐行判：命中 `= [数字...]` / `= {` / 裸数字序列 才算内联。
                has_inline = False
                for c in cells:
                    if c.get("cell_type") != "code":
                        continue
                    src = c.get("source", "")
                    lines = src if isinstance(src, list) else str(src).splitlines(True)
                    for ln in lines:
                        s = ln.strip()
                        if re.search(r"=\s*[\[{]", s) or re.search(r"=\s*[\d.]+(\s*,|$)", s) \
                           or re.match(r"^[\d.\s,]+$", s):
                            has_inline = True
                            break
                    if has_inline:
                        break
                if not has_inline:
                    bad_struct.append(f"{stem}(数据未内联——须 cell2 字面数据，禁仅 import 外部文件)")
        except Exception as e:
            bad_struct.append(f"{stem}(ipynb 解析失败: {type(e).__name__})")
    r.add("4.10", f"数据图 notebook 齐备且结构合规（数据图 {len(data_slots)} 个）",
          not missing and not bad_struct,
          (f"缺 notebook: {missing}" if missing else "") +
          (f"；结构不合规: {bad_struct}" if bad_struct else ""))


# ── 4.11 术语一致性（v1.1.0 补实现；E3 修复解析三缺陷）
def _parse_term_rows(table_path: Path) -> tuple[list[tuple[str, str, list[str]]], str]:
    """解析 terminology-table.md §2 表格 → [(标准写法, 别名, [禁用写法...]), ...]，含出处说明。

    E3 修复三重缺陷：
    ① 只取「## 2. 表格式」到下一个 `## ` 之间的表格（旧版全文 grep 把 §1/§3 的
       三列表、文档示例行全部当条目消费）；
    ② 解析行内 `\\|` 转义（表格自己 §2 声明的约定，旧版 `[^|]+` 直接错位）；
    ③ 表头/分隔行严格按「标准写法」列头识别，不再靠枚举排除。
    """
    text = table_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*2\..*?(?=\n##\s|\Z)", text, re.S)
    seg = m.group(0) if m else text
    rows: list[tuple[str, str, list[str]]] = []
    header_seen = False
    for line in seg.splitlines():
        if not line.strip().startswith("|"):
            continue
        # 先按未转义的 | 切列（\| 视为字面量占位 \x00 后还原）
        safe = line.replace("\\|", "\x00")
        cells = [c.strip().replace("\x00", "|") for c in safe.strip("|").split("|")]
        if len(cells) < 5 or set(cells[0]) <= {"-", ":", " "}:
            continue
        if cells[0] == "标准写法":      # 表头行
            header_seen = True
            continue
        if not header_seen:
            continue                    # 表头前的任何行（规范说明等）不消费
        std, alias, banned = cells[0], cells[1], cells[2]
        if not std or std == "—":
            continue
        banned_list = [b.strip() for b in banned.replace("，", "、").split("、")
                       if b.strip() and b.strip() != "—"]
        rows.append((std, alias, banned_list))
    if not header_seen:
        return rows, "未找到 §2 表头行（「| 标准写法 |…」）——表结构异常"
    return rows, ""


def check_terminology(text: str, r: Result):
    """禁用写法零出现 + 同章内标准写法与别名不并存 + 表内标准写法唯一（4.11d）。

    E3 修复：词界匹配（"AI" 不得命中 "AIV"——英文缩写禁用词用 \\b 词界，
    中文词用原样子串）；示例行/判据表行不再被消费。
    """
    table_path = Path(__file__).resolve().parent.parent / "references" / "terminology-table.md"
    if not table_path.is_file():
        r.add("4.11", "术语一致性校验（terminology-table.md 缺失，N/A）", True,
              "表文件缺失，判据无法执行——建表后此判据生效")
        return
    rows, err = _parse_term_rows(table_path)
    if err and not rows:
        r.add("4.11", "术语一致性校验（表结构异常，N/A）", True, err)
        return
    if not rows:
        r.add("4.11", "术语一致性校验（术语表无有效条目，N/A）", True,
              "terminology-table.md 未填条目——按 §5 维护约定每章 DELIVER 后追加")
        return
    bad_banned, bad_coexist = [], []
    for std, alias, banned_list in rows:
        for b in banned_list:
            if not b:
                continue
            # 词界匹配：纯 ASCII 词用 \b（AI 不命中 AIV/E.coli 的 coli），
            # 含中文的词用原样子串（中文无词界概念）
            if re.fullmatch(r"[A-Za-z0-9 .\-]+", b):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(b)}(?![A-Za-z0-9])", text):
                    bad_banned.append(b)
            elif b in text:
                bad_banned.append(b)
        if alias and alias != "—" and std in text and alias in text:
            bad_coexist.append(f"{std} vs {alias}")
    dup = len(rows) - len({s for s, _, _ in rows})
    ok = not bad_banned and not bad_coexist and dup == 0
    detail = (f"禁用写法出现: {bad_banned} " if bad_banned else "") + \
             (f"标准写法与别名并存: {bad_coexist}" if bad_coexist else "") + \
             (f"表内标准写法重复 {dup} 行（4.11d）" if dup else "")
    r.add("4.11", f"术语一致性（对照 {len(rows)} 条术语）", ok, detail or "全部通过")


# ── 4.12 溯源表（v1.1.0 补实现）
def check_provenance(text: str, work_root: Path, chapter: str, md_path: Path, r: Result):
    """溯源表存在 + [实] 处数 == 溯源行数。由 build --assemble 自动生成后应恒一致。"""
    n_shi = len(re.findall(r"\[实[·\]]", text))
    # 交付目录下的溯源表（文件名含「溯源」且含章号）
    hits = [p for p in (work_root / "交付").glob(f"*{chapter}*溯源*.md")] \
        if (work_root / "交付").is_dir() else []
    if n_shi == 0:
        r.add("4.12", "溯源表校验（正文无 [实] 条目，N/A）", True)
        return
    if not hits:
        r.add("4.12", f"溯源表存在（正文 [实] {n_shi} 处需溯源）", False,
              "交付/ 下未找到溯源表——build --assemble 会自动生成，或回 examiner 补 R3 日志")
        return
    prov = hits[0].read_text(encoding="utf-8")
    n_rows = len([l for l in prov.splitlines()
                  if l.strip().startswith("|") and not l.strip().startswith("|--")
                  and not l.strip().startswith("| 序")])
    # E3（红队 H4 修复）：SKILL §4.1 判据③「标识符在参考文献中存在」此前零实现——
    # 溯源行可写 FAKE-DOI-999 而行数对齐全绿。现机械核验：溯源行「标识符/来源」列的
    # PMID/DOI/ISBN 或中文源名须能在正文「参考文献」节或溯源表自身的核验状态中对应。
    refs_sec = re.split(r"^##\s*参考文献\s*$", text, flags=re.M)
    refs_body = refs_sec[1] if len(refs_sec) > 1 else ""
    bad_ident: list[str] = []
    for line in prov.splitlines():
        s = line.strip()
        if not s.startswith("|") or s.startswith("|--") or s.startswith("| 序"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 5:
            continue
        ident = cells[3]  # 序|正文位置|陈述要点|标识符/来源|核验状态 → 第3列=标识符（0起）
        if ident in ("—", "", "待核实"):
            continue
        # 提取标识符中的可检索锚（PMID 数字 / DOI 串 / ISBN / 中文源名词）
        anchors = re.findall(r"PMID[:：]?\s*(\d{5,9})|(10\.\d{4,5}/\S+)|(ISBN[^\s|,，]*)|([\u4e00-\u9fff]{2,12}(?:版|典|法|标准|公告|指南|手册))", ident)
        flat = [a for tup in anchors for a in tup if a]
        if not flat:
            # 无法提取锚的来源名：整串进参考文献模糊匹配
            flat = [ident]
        ok_row = any(a in refs_body for a in flat)
        if not ok_row:
            bad_ident.append(ident[:40])
    # R5 红队：SKILL §4.1 契约是「==」（少行/多行都不放行）
    line_ok = n_rows == n_shi
    ident_ok = not bad_ident
    r.add("4.12", f"溯源表行数({n_rows}) == 正文 [实] 处数({n_shi})",
          line_ok,
          f"溯源表 {hits[0].name}；差 {abs(n_rows - n_shi)} 行"
          + ("（多行）" if n_rows > n_shi else "（缺行）") if not line_ok else "")
    r.add("4.12b", f"溯源行标识符在参考文献中存在（{len(bad_ident)} 条异常）",
          ident_ok,
          f"参考文献节找不到对应条目: {bad_ident}" if bad_ident else "全部可对应")


# ── 4.13 修订态完整性（v1.1.0 新增：方案甲的机械守护）
def check_revision_state(text: str, work_root: Path, chapter: str,
                         docx_path: Path | None, r: Result):
    """4.13a 修订标记成对且 author/date 合法；4.13b md==docx 修订数；4.13c 校稿结论存在。"""
    marks = RE_REVISION.findall(text)
    n_ins = sum(1 for _, kind, _, _ in marks if kind == ".insertion")
    n_del = sum(1 for _, kind, _, _ in marks if kind == ".deletion")
    # 4.13a 成对性（R5 红队 #3 语义对齐）：**替换必须删+插成对**；§1.5 允许「整章一致的
    # 纯插入/纯删除」（如整段新增审稿意见）——判据：非替换性的单侧标记整章一致即放行。
    # 实现：若插删均 >0 则必须等量（= 替换场景）；若只有单侧则放行（= 整章纯插/纯删）。
    has_marks = bool(marks)
    mixed = n_ins > 0 and n_del > 0
    paired = (n_ins == n_del) if mixed else True
    bad_author = [a for _, _, a, _ in marks if not a.strip()]
    bad_date = [d for _, _, _, d in marks if not re.match(r"\d{4}-\d{2}-\d{2}", d)]
    r.add("4.13a", f"修订标记成对且 author/date 合法（插{n_ins}/删{n_del}）",
          paired and not bad_author and not bad_date,
          ("" if paired else f"替换场景插删不等（插{n_ins}/删{n_del}）——替换须删+插成对；"
                           f"纯插入/纯删除场景不得与另一侧混用 ") +
          (f"author 空: {bad_author} " if bad_author else "") +
          (f"date 非法: {bad_date}" if bad_date else ""))
    # 4.13b：md 标记数 == docx w:ins+w:del 数（docx 存在且 python-docx/zip 可读时）
    if docx_path is None:
        r.warn("4.13b", "md 与 docx 修订数一致", "docx 缺失，4.5d/4.6d 已另行 FAIL")
    else:
        try:
            with zipfile.ZipFile(docx_path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
            n_docx = len(re.findall(r"<w:ins ", xml)) + len(re.findall(r"<w:del ", xml))
            r.add("4.13b", f"md 修订标记({len(marks)}) == docx 修订数({n_docx})",
                  len(marks) == n_docx,
                  "不一致 = md 与 docx 分叉（改而不回流），须重建或回流")
        except Exception as e:
            r.warn("4.13b", "md 与 docx 修订数一致", f"docx 读取失败: {type(e).__name__}")
    # 4.13c：校稿结论节存在且含结论判定
    if RE_PROOFREAD_SECTION.search(text):
        m = RE_PROOFREAD_VERDICT.search(text)
        r.add("4.13c", "校稿结论节存在且含结论", bool(m),
              "" if m else "有「## 校稿结论」节但缺「结论:」行")
    else:
        r.add("4.13c", "校稿结论节存在且含结论", False,
              "交付 md 缺「## 校稿结论」——PROOFREAD 三件套未转写（build --assemble 自动补）")


def _docx_fingerprint(docx_path: Path) -> str | None:
    """读 docx 核心属性里的构建指纹（STT_MANUSCRIPT_FINGERPRINT=...）；无则 None。"""
    try:
        from docx import Document
        cp = Document(str(docx_path)).core_properties.comments or ""
        if "STT_MANUSCRIPT_FINGERPRINT=" in cp:
            return cp.split("STT_MANUSCRIPT_FINGERPRINT=")[1].split()[0].strip()
    except Exception:
        return None
    return None


# ── 4.13d 构建指纹（R5 红队 b2/b3：拦「无修订标记的静默篡改」与审阅版法外区）
def check_fingerprint(text: str, work_root: Path, chapter: str, r: Result):
    """双向锚定：属性内指纹（构建时文本 hash） vs 校验时**重算**的 docx 文本 hash。

    改文本不回流 → 重算值 ≠ 属性 → FAIL；换旧 docx（无属性）→ FAIL；
    篡改属性 → 仍与现文本不匹配 → FAIL。快照式指纹（不重算）拦不住就地改字，已废弃。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from build_manuscript import FINGERPRINT_KEY, docx_text_fingerprint
    except ImportError:
        r.warn("4.13d", "构建指纹校验（依赖 build_manuscript）", "导入失败，跳过")
        return
    deliver_p = find_delivery(work_root, chapter, "docx")
    review_p = next(iter(sorted((work_root / "交付").glob(f"*{chapter}*_审阅.docx"))), None) \
        if (work_root / "交付").is_dir() else None
    for label, p in (("交付", deliver_p), ("审阅版", review_p)):
        if p is None:
            continue  # 缺产物由 4.5d/4.13b 口径另行报告
        fp_attr = _docx_fingerprint(p)
        if not fp_attr:
            r.add(f"4.13d-{label}", f"{label} docx 含构建指纹", False,
                  f"{p.name} 无 {FINGERPRINT_KEY}（旧版/外来产物，须用 build_manuscript 重建）")
            continue
        fp_now = docx_text_fingerprint(p)
        r.add(f"4.13d-{label}", f"{label} docx 文本完整（现算 hash == 属性指纹）",
              fp_now == fp_attr,
              f"属性={fp_attr} 现算={fp_now} —— docx 在构建后被改动且未回流/重建（铁律违规）")


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
    check_frontmatter(text, r)
    check_headings(text, r)
    check_captions(text, r)
    check_xrefs(text, r)
    check_refs(text, r)
    check_exercise_ideology(text, r)
    check_words(md_path, args.target, r)
    # v1.1.0 四条新判据（此前仅规范声称、脚本零实现）
    check_data_figure_notebooks(text, work_root, args.chapter, r)
    check_terminology(text, r)
    check_provenance(text, work_root, args.chapter, md_path, r)
    docx_path_pre = find_delivery(work_root, args.chapter, "docx")
    check_revision_state(text, work_root, args.chapter, docx_path_pre, r)
    check_fingerprint(text, work_root, args.chapter, r)

    docx_path = find_delivery(work_root, args.chapter, "docx")
    media = check_docx(docx_path, r) if docx_path else -1
    if docx_path is None:
        # ── D-5 修复（2026-10-30 批次 B）─────────────────────────────────
        # 旧实现：docx 缺失时只记一条 WARN 并整段跳过 4.6 → `--strict` 仍 exit 0，
        # 即「docx 交付物根本没生成」被判通过（实测 FAIL 1 但 exit 0）。
        # 交付形态铁律是 md+docx 双格式，docx 缺失 = 交付物不完整 = 必须 FAIL。
        # 判据 ID 用 4.5d / 4.6d（docx-missing 专属），避免与正常分支的
        # 4.5 / 4.6a / 4.6b 同 ID 重复出现（重复 ID 会让报告出现两条同名判据）。
        r.add("4.5d", "docx 产物存在（交付形态 md+docx 双格式，缺一即不完整）", False,
              f"未找到 docx：{work_root / '交付'}/*_{args.chapter}.docx")
        r.add("4.6d", "docx 图数一致性可校验", False,
              "docx 缺失，无法校验图数一致性（4.6a/4.6b 不可评估）")

    # 4.6 图数一致：docx 媒体数 == 本次可嵌入图数
    # 关键（2026-10-30 修复）：assets/ 可能残留**上一章的陈旧资产**（如 9-9.png），
    # 直接数 PNG 个数会把陈旧资产算进来，导致 4.6a 误判为「一致」而实际缺图。
    # 判据改为：只统计 stem 属于**本章图位集合**的资产。
    #
    # ── D-11 修复（2026-10-30 批次 B）─────────────────────────────────
    # 旧实现只数 *.png，但 build_manuscript 对 SVG 记 raster="ok-vector"（矢量直嵌），
    # docx media 会 +1 而 png 数为 0 → **SVG 图一进交付必判 4.6a FAIL**（假红）。
    # 现口径改为「本章图位集合下所有可嵌入图（png + svg）」，与 build 侧对齐。
    asset_dir = work_root / "章节" / args.chapter / "figures" / "assets"
    slot_stems = {f"{a}-{b}" for a, b, _ in RE_FIGURE_SLOT.findall(text)}
    n_slots = len(slot_stems)
    pngs, svgs = [], []
    if asset_dir.is_dir():
        for p in sorted(asset_dir.glob("*.png")):
            if p.stem in slot_stems:
                pngs.append(p)
        for p in sorted(asset_dir.glob("*.svg")):
            if p.stem in slot_stems:
                svgs.append(p)
        stale = [p.name for p in sorted(asset_dir.iterdir())
                 if p.is_file() and p.suffix in (".png", ".svg") and p.stem not in slot_stems]
        if stale:
            r.warn("4.6c", "assets/ 无不属于本章的陈旧资产",
                   f"残留: {stale}（已忽略，不计入图数；建议清理）")
    n_png = len(pngs)
    n_embed = len(pngs) + len(svgs)   # 可嵌入图总数（PNG 栅格图 + SVG 矢量图）

    if media >= 0:
        # D-11：口径与 build 侧对齐 —— 可嵌入图 = PNG(栅格) + SVG(矢量直嵌)
        r.add("4.6a", f"docx 内嵌图数({media}) == 可嵌入图数({n_embed})",
              media == n_embed,
              f"docx media={media} / png={n_png} + svg={len(svgs)} = {n_embed}")
    if n_embed < n_slots:
        lv = "FAIL" if args.require_raster else "WARN"
        r.add("4.6b", f"全部图表已栅格化（{n_embed}/{n_slots}）", False,
              f"未栅格化 {n_slots - n_embed} 个；交付时必须在质量报告显式列出", level=lv)

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
