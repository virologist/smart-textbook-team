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

ENTITY_MAP = {
    # 病原 / 疾病
    "曲霉菌病": ["aspergillosis", "aspergillus"],
    "曲霉菌": ["aspergillus"],
    "曲霉菌结节": ["aspergillus granuloma", "fungal granuloma", "caseous granuloma"],
    "氨气": ["ammonia"],
    "新城疫": ["newcastle disease", "newcastle disease virus", "ndv"],
    "NDV": ["newcastle disease", "ndv"],
    "禽流感": ["avian influenza", "influenza a"],
    "高致病性禽流感": ["highly pathogenic avian influenza", "h5n1", "hpaiv"],
    "低致病性禽流感": ["low pathogenic", "h9n2"],
    "H9N2": ["h9n2"],
    "H5Nx": ["h5nx"],
    "H5N1": ["h5n1"],
    "H7N9": ["h7n9"],
    "H5N6": ["h5n6"],
    "H5N8": ["h5n8"],
    "H7N3": ["h7n3"],
    "2.3.4.4b": ["2.3.4.4b", "clade 2.3.4.4b"],
    "clade 2.3.4.4b": ["clade 2.3.4.4b", "genotype d1.1"],
    "基因型 D1.1": ["genotype d1.1", "d1.1"],
    "传染性支气管炎": ["infectious bronchitis", "ibv"],
    "IBV": ["infectious bronchitis", "ibv"],
    "QX-like": ["qx-like", "gi-19"],
    "LDT3": ["ldt3"],
    "H120": ["h120"],
    "鸡毒支原体": ["mycoplasma gallisepticum", "mycoplasma gallisepticum"],
    "滑液支原体": ["mycoplasma synoviae"],
    "支原体": ["mycoplasma"],
    "MG": ["mycoplasma gallisepticum", "mycoplasma"],
    "大肠杆菌": ["escherichia coli", "colibacillus", "apec"],
    "APEC": ["apec", "avian pathogenic escherichia coli", "escherichia coli"],
    "传染性法氏囊病": ["infectious bursal disease"],
    "传染性鼻炎": ["infectious rhinitis", "haemophilus"],
    "ILTV": ["infectious laryngotracheitis", "iltv"],
    "传染性喉气管炎": ["infectious laryngotracheitis", "iltv"],
    "维生素A": ["vitamin a", "retinol", "beta-carotene", "β-carotene"],
    "维生素E": ["vitamin e", "tocopherol", "selenium"],
    # 器官 / 病变
    "剖检": ["necropsy", "postmortem", "gross pathology", "lesion", "gross lesion"],
    "剖检病变": ["lesion", "gross lesion", "postmortem"],
    "腺胃": ["proventriculus"],
    "胰腺": ["pancreas", "pancreatic"],
    "肌胃": ["gizzard"],
    "气囊": ["air sac"],
    "法氏囊": ["bursa of fabricius", "bursa"],
    "心包炎": ["pericarditis"],
    "肝周炎": ["perihepatitis"],
    "腹膜炎": ["peritonitis"],
    "鼻窦": ["sinus", "infraorbital sinus"],
    "神经症状": ["neuro", "nervous sign"],
    "粪便": ["feces", "faecal", "faeces"],
    "出血": ["hemorrhage", "haemorrhage", "bleeding"],
    "坏死": ["necrosis", "necrotic"],
    "结节": ["nodule", "granuloma"],
    "纤维素": ["fibrin", "fibrinous"],
    "干酪样": ["caseous", "caseation"],
    "温和": ["mild", "slight"],
    "继发": ["secondary", "secondary infection"],
    "脐带": ["umbilical", "navel"],
    "产蛋率": ["egg production", "lay rate", "egg laying"],
    "免疫程序": ["vaccination schedule", "vaccine schedule", "vaccination program"],
    "宿主范围": ["host range", "host spectrum", "host restriction", "susceptible host"],
    "活禽市场": ["live poultry market", "live bird market", "wet market"],
    "垂直传播": ["vertical transmission", "transovarian", "egg transmission"],
    "野鸟": ["wild bird", "wildfowl", "wild birds"],
    "水禽": ["waterfowl", "duck", "waterfowl infection"],
    # 宿主种（过外推检测的关键）
    "鸡": ["chicken", "chickens", "broiler", "layer"],
    "鸭": ["duck", "ducks"],
    "鹅": ["goose", "geese", "gosling"],
    "鹌鹑": ["quail", "quails"],
    "鸽": ["pigeon", "pigeons"],
    "雉鸡": ["pheasant", "pheasants"],
    "孔雀": ["peacock", "peafowl"],
    "猫": ["cat", "feline", "cats"],
    "奶牛": ["dairy cattle", "cattle", "herd"],
    "人源": ["human"],
    "禽→牛→人": ["spillover", "cross-species", "cattle to human"],
    "禽→牛→人→禽": ["spillover", "cross-species", "cattle to human"],
    # 生态 / 传播
    "野鸟—家禽界面": ["wild bird-poultry interface", "interface between wild birds and poultry"],
    "迁徙": ["migration", "migratory", "flyway"],
    "候鸟迁徙": ["migratory birds", "migration", "flyway"],
    "水体暴露": ["water", "wetland", "pond", "lagoon"],
    "外环境监测": ["environmental surveillance", "environmental sampling", "environment"],
    "混合": ["mixed", "mixed infection", "co-infection"],
    "重组": ["reassortment", "reassortant"],
    "重配": ["reassortment", "reassortant"],
    "外源": ["exogenous", "environmental"],
    # 疫苗 / 免疫
    "HI": ["haemagglutination inhibition", "hemagglutination inhibition", "hi antibody"],
    "微量中和": ["micro-neutralization", "neutralizing antibody", "neutralization"],
    "死亡率保护": ["mortality protection", "protection", "mortality"],
    "商品疫苗": ["commercial vaccine", "commercial vaccines"],
    "疫苗种毒": ["vaccine strain", "seed strain", "vaccine seed"],
    "遗传距离": ["genetic distance", "genetic relatedness", "genetic"],
    "耐药": ["antimicrobial resistance", "resistance"],
    "青霉素": ["penicillin", "ampicillin"],
    # 临床 / 诊断
    "血凝抑制": ["haemagglutination inhibition", "hemagglutination inhibition"],
    "血凝": ["haemagglutination", "hemagglutination"],
    "琼脂": ["agar", "gel immunoprecipitation", "gpt"],
    "荧光": ["fluorescence", "fa", "fluorescent"],
    "PCR": ["pcr", "rt-pcr", "polymerase chain reaction"],
    "分离": ["isolation", "isolated", "isolate"],
    "致病力": ["pathogenicity", "virulence", "pathogenic"],
    "毒力": ["virulence"],
    "F蛋白": ["fusion protein", "f protein", "f gene"],
    "F基因": ["fusion gene", "f gene", "fusion protein"],
    "F蛋白裂解位点": ["cleavage site", "cleavage motif", "polybasic"],
    "裂解位点": ["cleavage site", "cleavage motif", "polybasic"],
    "类器官": ["organoid"],
    "中和抗体": ["neutralizing antibody", "neutralizing antibodies", "neutralisation"],
    "神经氨酸酶": ["neuraminidase"],
    "白细胞总数": ["leukocyte", "white blood cell"],
    # 人兽共患 / 职业
    "病死率": ["case fatality", "mortality rate", "fatality"],
    "病死禽": ["dead poultry", "cull", "infected birds"],
    "无害化处理": ["disposal", "safe disposal", "culling"],
    "职业暴露": ["occupational exposure"],
    "生物安全": ["biosecurity"],
    "生物安全柜": ["biosafety cabinet"],
    "防护": ["personal protective equipment", "ppe", "protective"],
    "PPE": ["ppe", "personal protective equipment"],
    "消毒": ["disinfection", "disinfectant"],
    "洗手": ["hand hygiene", "hand washing", "wash hands"],
    "无害化": ["safe disposal", "disposal"],
}

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

# 数值：必须带单位，且支持区间
NUM_RE = re.compile(
    r"(\d+(?:\.\d+)?)"
    r"(?:\s*[~～\-—至]\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:ppm|mg/m3|%|周|天|小时|log2|倍|日龄|羽|例|℃|人|次|株)"
)

# v5 修正：数值与单位之间允许空格（实测 41352071 摘要原文为 "80 %-100 % protection"
#          —— 百分号前有空格，v4 正则要求紧邻 ⇒ 假阴性「定量未获支撑」）
NUM_TIGHT = re.compile(
    r"(\d+(?:\.\d+)?)"
    r"(?:\s*[~～\-—至]\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:ppm|mg/m3|log2|周|天|小时|倍|日龄|℃)"
)
# 中文计数型数值（"1568 例感染"）：数字 + 可选空格 + 中文计数词
NUM_CN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:例|人|羽|株|次|万|亿)"
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
    units = ("ppm", "mg/m3", "%", "log2", "周", "天", "小时", "倍", "日龄", "℃",
             "例", "人", "羽", "株", "次", "万", "亿")
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


# ── v5 新增：实体分类 ──
# 泛化宿主/器官/流程词：出现在几乎所有家禽主张中，不能用于「主题相关性」判定
GENERIC_ENTITIES = {
    "鸡", "鸭", "鹅", "鹌鹑", "鸽", "雉鸡", "孔雀", "猫", "奶牛", "人源",
    "剖检", "剖检病变", "温和", "继发", "产蛋率", "出血", "坏死", "腹泻",
    "粪便", "剖检", "免疫程序", "混合", "分离", "PCR", "消毒", "洗手",
    "防护", "生物安全", "无害化", "病死禽", "职业暴露", "禽→牛→人", "禽→牛→人→禽",
}
# 文献核心对象：用于「主题相关性」判定（必须命中其一）
THEME_ENTITIES = {
    "曲霉菌病", "曲霉菌", "曲霉菌结节", "氨气", "新城疫", "NDV", "禽流感",
    "高致病性禽流感", "低致病性禽流感", "H9N2", "H5Nx", "H5N1", "H7N9", "H5N6",
    "H5N8", "H7N3", "2.3.4.4b", "clade 2.3.4.4b", "基因型 D1.1",
    "传染性支气管炎", "IBV", "QX-like", "LDT3", "H120",
    "鸡毒支原体", "滑液支原体", "支原体", "MG", "大肠杆菌", "APEC",
    "传染性法氏囊病", "传染性鼻炎", "ILTV", "传染性喉气管炎",
    "维生素A", "维生素E", "野鸟", "水禽", "活禽市场", "垂直传播", "宿主范围",
    "类器官", "中和抗体", "神经氨酸酶", "F蛋白", "F基因", "F蛋白裂解位点",
    "裂解位点", "毒力", "致病力", "重组", "重配", "外源", "耐药",
    "血凝抑制", "血凝", "荧光", "琼脂", "病死率", "野鸟—家禽界面",
    "迁徙", "候鸟迁徙", "水体暴露", "外环境监测", "疫苗种毒", "遗传距离",
    "商品疫苗", "死亡率保护", "HI", "微量中和", "白细胞总数", "宿主范围",
    "禽→牛→人→禽", "禽→牛→人",
}


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
    zh, _ = entities_in("鸡舍氨气浓度达到 100 ppm 时出现角膜溃疡")
    if "氨气" not in zh:
        print(f"  ✗ 实体抽取失败: {zh}"); ok = False
    print("✓ self-test 通过" if ok else "✗ self-test 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="R7 全文级引用核验器（包内固化版）")
    ap.add_argument("--work-root", help="WORK_ROOT")
    ap.add_argument("--chapter", default="ch_01", help="章号，如 ch_01")
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
