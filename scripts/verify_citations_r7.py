#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_citations_r7.py — R7 全文级引用核验器（包内固化版，v1.0.0）

来源与固化理由
================
v1–v5 的迭代版核验器一直活在 /tmp（会话临时区）——/tmp 清理即丢失，
R7 复核是「门禁 4.12d 只校验格式不校验真伪」的唯一补位手段，属**主链路资产**，
须随包分发。本文件 = /tmp/l1b_r7_verify_v5.py（分层判定 + 词表统一）
+ /tmp/l1b_r7_export_claims_v4.py（引用单元提取）合并固化，逻辑未改，
仅做三处工程化调整：
  ① 路径参数化（--work-root/--chapter 替代写死的工作区路径）；
  ② 产物落 {WORK_ROOT}/章节/{ch##}/review/r7_result.json（替代 /tmp）；
  ③ 增 --self-test 自检（不联网，验证提取器/判定器的确定性部分）。

四轮迭代史（每轮由具体假阳性/假阴性证据驱动，详见两章 r7_verification_log.md）
================================================================================
v1 整句中文匹配 → 21/21 假阳性 → v2 领域实体词典；
v2 裸数字命中 → 33518122 假阴性 → v3 数值+单位邻近；
v3 rfind("。") 跨行吞并 → 3 处假阳性 → v4 引用单元提取；
v4 NUM 词表与摘要空格形态不一致 → 41352071 '80 %-100 %' 假阴性 → v5 词表统一+空格容错。

已知边界（如实声明，禁止当「判 death」用）
================================================================================
· THEME 白名单会产生「主题错配」假阳性（v4 实测 11 处误报，题名逐条证伪）——
  「不支持（主题错配）」判定须人工复核题名后才可采信；
· 摘要级文献的数值结论只能判「未在摘要出现」，不能判「文献不支持」。

退出码：0 完成 | 2 输入错误 | 3 网络全败（无任何文献取回）

用法
================================================================================
  python3 scripts/verify_citations_r7.py --work-root "$WORK_ROOT" --chapter ch_01
  python3 scripts/verify_citations_r7.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# ── ★L（v2.11.2）：判据数据外置——通用层零学科常量（ADR-02 收口）────────────
# 病灶：v2.10.2 固化 R7 时三词典（120/32/73 条）+ 数值单位表写死在通用层脚本，
#       v2.10.5 ★K 只把 §7b 的 5 条样例与 73 个 theme 对象下沉，主体词典仍留在
#       scripts/ → CI「学科中立性门禁」自 2026-11-04 起连续红灯（22 处 HARD 命中）。
# 修法：完整数据落 references/profiles/（门禁豁免的学科化数据源唯一合法落点），
#       本文件只保留加载与判定逻辑；默认 profile 语义不变，三条数值正则 pattern
#       与外置前逐字比对通过（回归断言见 tests/test_r7_entities_externalized.py）。
_PKG_ROOT = Path(__file__).resolve().parent.parent
_ENTITY_DATA = _PKG_ROOT / "references" / "profiles" / "r7-entities-veterinary.json"


def load_entity_data(path=None):
    """载入学科化判据数据；缺失/损坏一律显式报错，禁止静默回落空词典。"""
    p = Path(path) if path else _ENTITY_DATA
    if not p.is_file():
        raise FileNotFoundError(f"R7 判据数据文件缺失：{p}")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"R7 判据数据文件不可解析：{p}（{e}）") from e
    if d.get("schema") != "r7-entities/v1":
        raise ValueError(f"R7 判据数据文件 schema 不合法：{d.get('schema')!r}")
    missing = [k for k in ("entity_map", "generic_entities", "theme_entities",
                           "num_units") if k not in d]
    if missing:
        raise ValueError(f"R7 判据数据文件缺键：{missing}")
    units = d["num_units"]
    miss_u = [k for k in ("NUM_RE", "NUM_TIGHT", "NUM_CN", "num_hit")
              if k not in units]
    if miss_u:
        raise ValueError(f"R7 判据数据文件 num_units 缺键：{miss_u}")
    return d


_DATA = load_entity_data()
ENTITY_MAP = {k: list(v) for k, v in _DATA["entity_map"].items()}
GENERIC_ENTITIES = set(_DATA["generic_entities"])
THEME_ENTITIES = set(_DATA["theme_entities"])
_NUM_UNITS = _DATA["num_units"]


def _units_alt(key):
    """把单位词表拼成正则分支（re.escape 保证字面量，避免元字符注入）。"""
    return "|".join(re.escape(u) for u in _NUM_UNITS[key])


STOP_EN = {
    "the", "and", "for", "with", "this", "that", "from", "when", "will", "have",
    "been", "were", "which", "than", "their", "there", "these", "those", "such",
    "also", "more", "most", "other", "into", "about", "protein", "acid", "type",
    "level", "levels", "result", "results", "study", "studies", "data", "using",
    "showed", "show", "here", "both", "after", "before", "during", "between",
    "first", "second", "third", "same", "different", "several", "various",
    "however", "therefore", "because", "while", "where", "which", "these",
    "based", "overall", "these", "thus", "hence", "via", "per", "one", "two",
}
STOP_ZH = {
    "的", "是", "在", "和", "与", "或", "为", "可", "出现", "主要", "常", "更",
    "这", "那", "如果", "基本", "其中", "以及", "因为", "因此", "所以", "具有",
    "包括", "导致", "造成", "则", "但", "也", "都", "必须", "应", "需要", "不",
    "无", "重要", "关键", "核心特征", "确证", "确诊性", "依据", "同时", "进一步",
    "提示", "显示", "表明", "研究", "分析", "观察", "特点", "特征", "情况",
}

# 数值：必须带单位，且支持区间（单位词表来自判据数据文件，通用层零学科常量）
NUM_RE = re.compile(
    r"(\d+(?:\.\d+)?)"
    r"(?:\s*[~～\-—至]\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:" + _units_alt("NUM_RE") + r")"
)

# v5 修正：数值与单位之间允许空格（实测 41352071 摘要原文为 "80 %-100 % protection"
#          —— 百分号前有空格，v4 正则要求紧邻 ⇒ 假阴性「定量未获支撑」）
NUM_TIGHT = re.compile(
    r"(\d+(?:\.\d+)?)"
    r"(?:\s*[~～\-—至]\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:" + _units_alt("NUM_TIGHT") + r")"
)
# 中文计数型数值（"1568 例感染"）：数字 + 可选空格 + 中文计数词
NUM_CN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:" + _units_alt("NUM_CN") + r")"
)

SENT_END = "。！？"
ANCHOR_RE = re.compile(r"\[实\]\(PMID:\s*(\d+)\)")


# ───────────────────────── 主张提取（引用作用域） ─────────────────────────
def unit_of(lines, idx):
    """返回覆盖 idx 的引用单元 (start, end, text)"""
    i = idx
    while i > 0 and lines[i].strip() and not lines[i].lstrip().startswith(
            ("|", "#", ">", "<!--", "```")) and not re.match(r"^\s*(?:[-*+]\s|\d+\.\s)", lines[i]):
        i -= 1
    start = i
    j = idx
    while j + 1 < len(lines) and lines[j + 1].strip() and not lines[j + 1].lstrip().startswith(
            ("|", "#", ">", "<!--", "```")) and not re.match(r"^\s*(?:[-*+]\s|\d+\.\s)", lines[j + 1]):
        j += 1
    return start, j, "\n".join(lines[start:j + 1])


def strip_md(s):
    s = re.sub(r"\[实\]\(PMID:\s*\d+\)", "", s)
    s = re.sub(r"\[来源：[^\]]*\]", "", s)
    s = re.sub(r"\[实\]|\[估\]|\[引\]|\[待核实[^\]]*\]", "", s)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s, flags=re.S)
    s = re.sub(r"__(.+?)__", r"\1", s, flags=re.S)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = s.replace("|", " ")
    return re.sub(r"\s+", " ", s).strip()


def scope_for(unit_text, anchor_positions, k):
    """引用作用域：单锚点 → 整句；多锚点 → 紧邻分句"""
    a = anchor_positions[k]
    # 该锚点之前的文本
    before = unit_text[:a]
    # 剥掉锚点自身占位
    before_clean = strip_md(before)
    if len(anchor_positions) == 1:
        # 整句：从最后一个句界之后开始
        cut = -1
        for i in range(len(before_clean) - 1, -1, -1):
            if before_clean[i] in SENT_END:
                cut = i + 1
                break
        return before_clean[cut:] if cut >= 0 else before_clean
    # 多锚点：先切到上一个锚点之后，再取最后一个分句
    if k > 0:
        prev = anchor_positions[k - 1]
        seg_raw = unit_text[prev:a]
        seg = strip_md(seg_raw)
        # 去掉上一个锚点自身的残留（strip_md 已去锚点标记，但正文尾可能残留）
    else:
        seg = before_clean
    cut = -1
    for i in range(len(seg) - 1, -1, -1):
        if seg[i] in "；;，,——":
            cut = i + 1
            break
    return seg[cut:] if cut >= 0 else seg


def extract_all(draft_text):
    body = draft_text.split("## 参考文献")[0]
    lines = body.split("\n")
    rows = []
    for idx, line in enumerate(lines):
        if not ANCHOR_RE.search(line):
            continue
        s, e, utext = unit_of(lines, idx)
        pos = []
        for m in ANCHOR_RE.finditer(utext):
            pos.append(m.start())
        pmids = [m.group(1) for m in ANCHOR_RE.finditer(utext)]
        for k, (p, pm) in enumerate(zip(pos, pmids)):
            rows.append({
                "pmid": pm,
                "line": idx + 1,
                "unit_start": s + 1,
                "unit_end": e + 1,
                "n_anchors_in_unit": len(pos),
                "claim": scope_for(utext, pos, k),
                "raw_line": line.strip()[:400],
            })
    return rows


# ───────────────────────── 取数通道 ─────────────────────────
def fetch(url, retries=3, timeout=45):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:      # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{last}")


def esummary(pmid):
    url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
           f"?db=pubmed&id={pmid}&retmode=json")
    d = json.loads(fetch(url))
    res = d.get("result", {}).get(pmid)
    if not res:
        return None
    pmcid = next((a.get("value") for a in res.get("articleids", [])
                   if a.get("idtype") == "pmc"), None)
    return {"title": res.get("title", ""), "journal": res.get("fulljournalname", ""),
            "year": res.get("pubdate", ""), "pmcid": pmcid}


def pmc_fulltext(pmcid):
    xml = fetch(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                f"?db=pmc&id={pmcid}&retmode=xml")
    xml = re.sub(r"<ref-list.*?</ref-list>", " ", xml, flags=re.S)
    xml = re.sub(r"<[^>]+>", " ", xml)
    return re.sub(r"\s+", " ", xml)


def abstract_text(pmid):
    t = fetch(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
              f"?db=pubmed&id={pmid}&rettype=abstract&retmode=text")
    return re.sub(r"\s+", " ", t)


# ───────────────────────── 判定工具 ─────────────────────────
def hit_en(text, tok):
    pat = r"(?<![\w])" + re.escape(tok) + r"(s|es)?(?![\w])"
    return bool(re.search(pat, text.lower()))


def num_hit(body, num):
    r"""数值 + 单位邻近命中（R7 v3 引入，v4 扩展，v5 修正空格容错）

    v5 修正证据：41352071 摘要原文 "all vaccines provided 80 %-100 % protection from
    mortality" —— 百分号前有空格；v4 的 ``num+\s*%`` 实际能匹配，但 v4 的 NUM_RE
    抽取阶段把 "80 %-100 %" 切成 (80, 100)，随后 num_hit 用 ``(?<!\w.)80\s*%``
    需要百分号紧邻，而正文中文主张写的是「80%—100%」（无空格）——
    真因是**单位集合遗漏「%」与中文计数词**在 NUM_RE 与 num_hit 之间不一致。
    v5 统一：NUM_RE 与 num_hit 共用同一单位词表，且允许中间空格。
    """
    units = _NUM_UNITS["num_hit"]
    for u in units:
        pat = (r"(?<![\w.])" + re.escape(num)
               + r"(?:\s*[~～\-—至]\s*\d+(?:\.\d+)?)?"
               + r"\s*" + re.escape(u) + r"(?![\w])")
        if re.search(pat, body.lower()):
            return True
    return False


def entities_in(claim):
    """抽取主张内的领域实体（中文实体 + 英文实词）"""
    zh = [z for z in ENTITY_MAP if z in claim]
    en = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", claim)]
    en = [w for w in en if w not in STOP_EN and len(w) >= 3]
    # 去重保序
    seen, out = set(), []
    for x in zh + en:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return zh, out


# ── ★K（v2.10.5）：判据层学科化——profile §7b 覆盖默认判据数据 ──────────────
# 病灶（第六轮扫描 K1-K5）：三词典 100% 兽医域硬编码（120 词条 0 跨学科词）且不读
# profile——非兽医教材跑 R7 时实体命中恒不适用（判「全部缺实体」假阳性），
# 与 B3 已完成的判据层学科化（数值触发词/指标正则下沉 profile §7）同构违规。
# 修法与 B3 同源：profile `§7b` 声明 `entity_map`（中文名: 英文候选|候选）与
# `theme_entities`（白名单）——profile 有配置则**覆盖**内置默认；无则回落 + WARN。


def load_profile_entities(profile: str | None):
    """读 profile §7b → (entity_map 增补/覆盖 dict, theme_entities set, warn|None)。

    解析格式（§7b 列表行）：
      - 中文名: 候选|候选|候选          → entity_map 条目
      - theme_entities（…）：A, B, C   → 主题白名单整组替换
    profile 未给 → (None, None, WARN 文本)；§7b 缺失但 profile 是 veterinary →
    静默回落（默认数据即兽医域，语义等价）；非兽医学科缺 §7b → 显式 WARN
    （判据恒不适用，结果可能全是假阳性——不得静默）。
    """
    if not profile:
        return None, None, None
    p = _PKG_ROOT / 'references' / 'profiles' / f'{profile}.md'
    if not p.is_file():
        return None, None, f'profile 不存在：{p}（回落默认判据数据，判定可能失真）'
    text = p.read_text(encoding='utf-8')
    m = re.search(r'###\s*§?7b[\.．]?\s*R7 核验实体词典(.*?)(?=###|\Z)', text, re.S)
    if not m:
        if profile == 'veterinary':
            return None, None, None  # 内置默认即兽医域，语义等价，静默
        return (None, None,
                f'profile {profile} 缺 §7b 实体词典——实体/主题判据回落兽医默认，'
                f'非兽医学科将产生系统性假阳性（请补 §7b）')
    seg = m.group(1)
    emap: dict[str, list[str]] = {}
    themes: set[str] | None = None
    for line in seg.splitlines():
        s = line.strip()
        if s.startswith('-') and ':' in s and not s.startswith('- theme_entities'):
            body = s.lstrip('- ').strip()
            zh, _, cand = body.partition(':')
            zh, cand = zh.strip(), cand.strip()
            if zh and cand:
                emap[zh] = [c.strip() for c in cand.split('|') if c.strip()]
        elif s.startswith('- theme_entities'):
            after = s.split('：', 1)[-1] if '：' in s else ''
            if after:
                # 分隔符兼容：顿号（、）/逗号（, ,）/分号
                parts = re.split(r'[、,，;；]', after)
                themes = {x.strip() for x in parts if x.strip()}
    return emap or None, themes, None


def apply_profile(profile: str | None):
    """把 §7b 配置应用到全局词典（进程内一次）。返回 WARN 或 None。"""
    global ENTITY_MAP, THEME_ENTITIES
    emap, themes, warn = load_profile_entities(profile)
    if emap:
        merged = dict(ENTITY_MAP)
        merged.update(emap)
        ENTITY_MAP = merged
    if themes:
        THEME_ENTITIES = themes
    return warn


def evaluate(claim, title, abstract, body, source):
    """分层判定：返回 dict

    v5 核心修正
    ----------
    1. **主题判定只看「文献核心对象」**：v4 把泛化宿主（鸡/鸭/鹅…）也算进核心实体，
       于是「鸡+曲霉菌病」主张因 L1 题名无「chicken」而被误判主题错配
       ⇒ v5 用 THEME_ENTITIES 白名单，并要求**至少一个核心实体在 L1 或 L2 命中**。
    2. **实体覆盖以全文为准，摘要命中记为「题名/摘要」但不算缺失**：
       摘要级文献（无 PMC 全文）则只能到摘要层。
    3. **数值缺失只在有全文时判**：摘要级文献的数值不能由摘要单独确证，
       记为「摘要级（数值未在摘要出现）」而非硬性缺失。
    """
    zh, en_words = entities_in(claim)
    l1 = (title + " " + abstract).lower()      # L1 题名+摘要
    l2 = body.lower()                          # L2 全文正文
    has_full = source == "全文"

    # ── 实体覆盖 ──
    missed, hit_by = [], []
    for z in zh:
        cands = ENTITY_MAP[z]
        if any(hit_en(l2, c) for c in cands):
            hit_by.append((z, "全文"))
        elif any(hit_en(l1, c) for c in cands):
            hit_by.append((z, "题名/摘要"))
        else:
            missed.append(z)

    # 英文实词（过外推检测信号）
    missed_en = [w for w in en_words if len(w) >= 4 and not hit_en(l2, w)]

    # ── 数值 ──
    nums = []
    for a, b in NUM_RE.findall(claim):
        nums.append(a)
        if b:
            nums.append(b)
    for a in NUM_CN.findall(claim):
        nums.append(a)
    nums = list(dict.fromkeys(n for n in nums if n not in ("1", "2", "3", "4", "5")))
    missed_nums = [n for n in nums if not num_hit(l2 + " " + l1, n)]

    # ── 主题相关性：核心实体在 L1 或 L2 命中 ──
    core = [z for z in zh if z in THEME_ENTITIES]
    theme_ok = True
    if core:
        theme_ok = any(
            any(hit_en(l1, c) or hit_en(l2, c) for c in ENTITY_MAP[z]) for z in core
        )
    else:
        # 无核心实体 → 用长英文实词判断
        theme_ok = (not en_words) or any(hit_en(l1, w) or hit_en(l2, w)
                                          for w in en_words if len(w) >= 5)

    # ── 判定 ──
    if not theme_ok:
        verdict = "不支持（主题错配）"
    elif missed_nums:
        verdict = ("部分支持（定量未获支撑）" if has_full
                   else "部分支持（摘要级·数值未在摘要出现）")
    elif missed:
        verdict = ("部分支持（定性未获全文支撑）" if has_full
                   else "部分支持（摘要级·实体未在摘要出现）")
    else:
        verdict = "支持"

    return {
        "verdict": verdict,
        "theme_ok": theme_ok,
        "entities": zh,
        "core_entities": core,
        "entities_hit": hit_by,
        "missed_entities": missed,
        "missed_en": missed_en,
        "nums": nums,
        "missed_nums": missed_nums,
        "source": source,
    }




# ═══════════════════════ 主控 ═══════════════════════

def self_test() -> int:
    """确定性自检（不联网）：提取器 + 数值判定 + 实体抽取。"""
    ok = True
    # 1) 引用单元提取：多锚点单元各取紧邻分句
    lines = ["H5Nx可感染鸡鸭鹅[实](PMID: 111)；水禽极少发ILTV[实](PMID: 222)。"]
    unit = unit_of(lines, 0)
    pos = [m.start() for m in ANCHOR_RE.finditer(unit[2])]
    c0 = scope_for(unit[2], pos, 0)
    c1 = scope_for(unit[2], pos, 1)
    print(f"  claim#0 = {c0!r}")
    print(f"  claim#1 = {c1!r}")
    if "H5Nx" not in c0 or "水禽" not in c1:
        print("  ✗ 多锚点分句归属错误"); ok = False
    # 2) 数值+单位邻近（v5 词表）
    body = "all vaccines provided 80 %-100 % protection from mortality"
    if not num_hit(body.lower(), "80") or not num_hit(body.lower(), "100"):
        print("  ✗ '80 %-100 %' 空格形态未命中"); ok = False
    # 3) 数值抽取：区间两数分别捕获 + 中文计数
    nums = []
    for a, b in NUM_RE.findall("25~50 ppm 与 1568 例"):
        nums.append(a)
        if b: nums.append(b)
    nums += NUM_CN.findall("共 1568 例感染")
    if "25" not in nums or "50" not in nums or "1568" not in nums:
        print(f"  ✗ 数值抽取不完整: {nums}"); ok = False
    # 4) 实体抽取
    zh, _ = entities_in("鸡舍氨气读数达到 100 ppm 时出现角膜溃疡")
    if "氨气" not in zh:
        print(f"  ✗ 实体抽取失败: {zh}"); ok = False
    # 5) ★K（v2.10.5）学科中立：profile §7b 加载与覆盖
    emap_v, th_v, w_v = load_profile_entities("veterinary")
    if w_v is not None:
        print(f"  ✗ veterinary 加载异常: {w_v}"); ok = False
    emap_c, th_c, w_c = load_profile_entities("computer-science")
    if not emap_c or not th_c:
        print(f"  ✗ computer-science §7b 未解析出词典: emap={bool(emap_c)} theme={bool(th_c)} warn={w_c}")
        ok = False
    else:
        if "哈希表" not in emap_c or "hash" not in emap_c["哈希表"][0].lower():
            print(f"  ✗ CS entity_map 词条解析错: {emap_c.get('哈希表')}"); ok = False
        if not ({"算法", "并发"} <= th_c):
            print(f"  ✗ CS theme_entities 解析错: {sorted(th_c)[:6]}"); ok = False
        print(f"  ✓ CS §7b 词典: entity_map {len(emap_c)} 词条 / theme {len(th_c)} 对象")
    _, _, w_missing = load_profile_entities("law")
    if w_missing is not None:
        print(f"  ✗ law §7b 应可解析（得到 warn={w_missing!r}）"); ok = False
    _, _, w_none = load_profile_entities(None)
    if w_none is not None:
        print("  ✗ 无 profile 应静默回落"); ok = False
    print("✓ self-test 通过" if ok else "✗ self-test 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="R7 全文级引用核验器（包内固化版）")
    ap.add_argument("--work-root", help="WORK_ROOT")
    ap.add_argument("--chapter", default="ch_01", help="章号，如 ch_01")
    ap.add_argument("--profile", default=None,
                    help="★K v2.10.5：学科 profile 名（读其 §7b 实体词典覆盖默认判据数据；"
                         "非兽医学科必须给，否则实体/主题判据产生系统性假阳性）")
    ap.add_argument("--out", default=None,
                    help="结果 JSON 路径（默认 章节/{ch}/review/r7_result.json）")
    ap.add_argument("--self-test", action="store_true",
                    help="确定性自检（不联网）")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if not args.work_root:
        ap.error("--work-root 必填（或用 --self-test）")
    wr = Path(args.work_root).expanduser().resolve()
    draft = wr / "章节" / args.chapter / "draft.md"
    if not draft.is_file():
        print(f"[ERROR] draft 不存在: {draft}", file=sys.stderr)
        return 2

    global CHAPTER
    CHAPTER = args.chapter
    # ★K：profile 词典应用（§7b 有配置则覆盖内置；非兽医学科缺配置显式 WARN）
    pw = apply_profile(args.profile)
    if pw:
        print(f"[WARN] {pw}", file=sys.stderr)
        print("[WARN] 继续运行——但实体/主题判定可能全是假阳性，结果仅供参考",
              file=sys.stderr)
    claims = extract_all(draft.read_text(encoding="utf-8"))
    uniq = sorted({c["pmid"] for c in claims})
    if not uniq:
        print("[WARN] 正文无 [实](PMID: …) 锚点——无事可核", file=sys.stderr)
        return 0

    meta, full, abs_ = {}, {}, {}
    net_fail = 0
    for p in uniq:
        try:
            m = esummary(p)
            meta[p] = m or {}
            if m and m.get("pmcid"):
                full[p] = pmc_fulltext(m["pmcid"])
            else:
                abs_[p] = abstract_text(p)
            print(f"  取回 {p}: {(meta[p] or {}).get('title','NO META')[:60]}"
                  f" [{'全文' if p in full else '摘要'}]")
            time.sleep(0.4)
        except Exception as e:      # noqa: BLE001
            print(f"  ⚠ {p} 取回失败: {e}", file=sys.stderr)
            meta[p] = {}
            net_fail += 1

    if net_fail == len(uniq):
        print("[ERROR] 全部文献取回失败（网络不可用）——本次核验无效", file=sys.stderr)
        return 3

    out = []
    for c in claims:
        p = c["pmid"]
        title = (meta.get(p) or {}).get("title", "")
        abstract = abs_.get(p, "")
        body = full.get(p, "")
        source = "全文" if p in full else ("摘要" if abstract else "无")
        ev = evaluate(c["claim"], title, abstract, body, source)
        rec = dict(c)
        rec.update(ev)
        rec["title"] = title
        rec["journal"] = (meta.get(p) or {}).get("journal", "")
        rec["pmcid"] = (meta.get(p) or {}).get("pmcid")
        out.append(rec)

    out_path = (Path(args.out) if args.out
                else wr / "章节" / args.chapter / "review" / "r7_result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    cnt = Counter(r["verdict"] for r in out)
    print(f"\n⇒ {args.chapter} 共 {len(out)} 处锚点")
    for k, v in cnt.most_common():
        print(f"   {k}: {v}")
    print("\n---- 非「支持」明细 ----")
    for r in out:
        if r["verdict"] != "支持":
            print(f"[{r['pmid']}] L{r['line']} {r['verdict']}")
            print(f"   主张: {r['claim'][:130]}")
            print(f"   缺实体: {r['missed_entities']} 缺数值: {r['missed_nums']}")
    print(f"\n→ {out_path}")
    print("[提醒] 「不支持（主题错配）」判定须人工复核题名后采信（THEME 白名单有假阳性史）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
