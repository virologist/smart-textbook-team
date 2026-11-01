#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_cross_chapter.py — 跨章一致性校验器（C10，批次 5）

==============================================================================
为什么需要：单章流程内的校验（审查 R1-R4 / 门禁 3 / 门禁 4）都只看【本章】，
多章成书时三类跨章矛盾无人看守：
  ① 同一术语多种写法（「禽流感」vs「禽流行性感冒」混用）
  ② 数据矛盾（ch01 说发病率 12.5%，ch07 说 21%——同源数据必有一错）
  ③ 内容重复（两章大段复述同一背景，成书后读者跳戏）

用法
------------------------------------------------------------------------------
  python3 scripts/check_cross_chapter.py --work-root "$WORK_ROOT" [--terms 术语表.md]

  # 术语表格式（可选；缺省用章节内高频名词自动比对）：
  #   标准写法: 别名1, 别名2
  #   禽流感: 禽流行性感冒, AI（此缩写太泛,建议不要收录）

退出码：0 一致 | 1 存在矛盾（--strict 时）| 2 输入缺失
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def load_chapters(work_root: Path) -> dict[str, str]:
    """读各章 draft（无 draft 的章跳过）。返回 {ch##: text}。"""
    out: dict[str, str] = {}
    ch_dir = work_root / "章节"
    if not ch_dir.is_dir():
        return out
    for ch in sorted(ch_dir.glob("ch*")):
        d = ch / "draft.md"
        if d.is_file():
            out[ch.name] = d.read_text(encoding="utf-8")
    return out


def strip_code(text: str) -> str:
    """剔除代码块与 frontmatter——那些区域出现「不一致」是正常的（示例/元数据）。"""
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return text


# ── ① 术语一致性 ─────────────────────────────────────────────────────────
def check_terms(chapters: dict[str, str], terms_file: Path | None) -> list[dict]:
    issues = []
    if terms_file and terms_file.is_file():
        # 用户术语表：标准写法: 别名1, 别名2
        for ln in terms_file.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or ":" not in ln:
                continue
            std, aliases = ln.split(":", 1)
            std = std.strip()
            alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
            found_in: dict[str, list[str]] = {}
            for ch, text in chapters.items():
                body = strip_code(text)
                hits = [a for a in alias_list if a and a in body]
                if hits:
                    found_in[ch] = hits
            if found_in:
                issues.append({
                    "type": "术语别名", "term": std,
                    "detail": f"别名 {found_in} 应统一为「{std}」",
                    "severity": "WARN" if len(found_in) == 1 else "FAIL",
                })
    else:
        # 无术语表：抓「同一概念多种括注写法」（如 X（Y）与 Y（X）并存）
        paren = re.compile(r"([\u4e00-\u9fff]{2,12})（([A-Za-z][A-Za-z0-9\- ]{1,20})）")
        std2abbr: dict[str, set] = defaultdict(set)
        abbr2std: dict[str, set] = defaultdict(set)
        for text in chapters.values():
            body = strip_code(text)
            for cn, en in paren.findall(body):
                std2abbr[cn].add(en)
                abbr2std[en].add(cn)
        for en, cns in abbr2std.items():
            if len(cns) > 1:
                issues.append({
                    "type": "术语多写法", "term": en,
                    "detail": f"同一英文缩写被标注为多个中文名 {sorted(cns)}——必有一处不规范",
                    "severity": "WARN",
                })
    return issues


# ── ② 数据矛盾 ───────────────────────────────────────────────────────────
def check_data_conflicts(chapters: dict[str, str]) -> list[dict]:
    """同一「指标+对象」在不同章给出不同数值。

    口径：只比对带 [实] 标签的数值陈述（有标签才算断言；未标数据由单章流程管）。
    """
    issues = []
    # 「{对象} 的 {指标} 为/约/达 {数值}{单位}」
    # P3-7 实战修正（2026-11-01）：对象名此前限定为纯汉字 `[\u4e00-\u9fff]{2,10}`，
    # 而教材里的指标几乎都挂在**病原/毒株名**上（H9N2、H5N1、E. coli、PRRSV），
    # 全是 ASCII → 真实稿件里最该被抓的一类矛盾**永远不命中**（实测 ch01 1% vs ch02 25%
    # 双章 [实] 断言，检测器 FAIL 0 静默放过）。现对象允许字母数字与连字符。
    pat = re.compile(
        r"([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff\- .]{1,14}?)"
        r"的(?:发病率|病死率|死亡率|阳性率|检出率|感染率)"
        r"[约为达高达]*\s*(\d+(?:\.\d+)?)\s*[%％][^\n]*?\[实\]")
    claims: dict[tuple, list] = defaultdict(list)
    for ch, text in chapters.items():
        body = strip_code(text)
        for obj, num in pat.findall(body):
            claims[(obj.strip(),)].append((ch, num))
    for (obj,), lst in claims.items():
        nums = {n for _, n in lst}
        if len(nums) > 1:
            issues.append({
                "type": "数据矛盾", "term": obj,
                "detail": f"「{obj}」同指标多章数值不一: {lst}（同源数据必有一错，须回溯检索摘要定对错）",
                "severity": "FAIL",
            })
    return issues


# ── ③ 内容重复 ───────────────────────────────────────────────────────────
def check_duplication(chapters: dict[str, str], min_len: int = 60) -> list[dict]:
    """跨章 ≥N 字的相同句串（按句切，两句连续相同即报）。"""
    issues = []
    sents: dict[str, list[str]] = {}
    for ch, text in chapters.items():
        body = strip_code(text)
        body = re.sub(r"\[(?:实|估|引|待核实)[^\]]*\]", "", body)
        sents[ch] = [s.strip() for s in re.split(r"[。！？\n]", body)
                     if len(s.strip()) >= min_len]
    chs = sorted(sents)
    for i, a in enumerate(chs):
        for b in chs[i + 1:]:
            common = set(sents[a]) & set(sents[b])
            if common:
                sample = sorted(common)[0][:40]
                issues.append({
                    "type": "内容重复",
                    "term": f"{a} ↔ {b}",
                    "detail": f"{len(common)} 个长句完全相同（如「{sample}…」）——成书后读者跳戏，建议改写其一",
                    "severity": "WARN",
                })
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="跨章一致性校验器（术语/数据/重复）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--terms", default=None, help="术语表路径（可选）")
    ap.add_argument("--strict", action="store_true", help="存在 FAIL 即 exit 1")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    chapters = load_chapters(work_root)
    if len(chapters) < 2:
        print(f"[WARN] 有效章节 {len(chapters)} 章（<2）——跨章校验需要 ≥2 章 draft，跳过",
              file=sys.stderr)
        return 0

    terms_file = Path(args.terms).expanduser() if args.terms else None
    issues = (check_terms(chapters, terms_file)
              + check_data_conflicts(chapters)
              + check_duplication(chapters))

    if args.json:
        print(json.dumps({"chapters": sorted(chapters), "issues": issues},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"跨章一致性校验 | 章节: {', '.join(sorted(chapters))}")
        print("=" * 62)
        if not issues:
            print("  ✓ 未发现跨章矛盾")
        for i in issues:
            mark = "✗" if i["severity"] == "FAIL" else "⚠"
            print(f"  {mark} [{i['type']}] {i['term']}")
            print(f"      → {i['detail']}")
        n_fail = sum(1 for i in issues if i["severity"] == "FAIL")
        print("-" * 62)
        print(f"FAIL {n_fail} | WARN {len(issues) - n_fail}")
        print("=" * 62)

    if args.strict and any(i["severity"] == "FAIL" for i in issues):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
