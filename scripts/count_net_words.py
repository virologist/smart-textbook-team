#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
净字数 SSOT 计数器（P2-4，2026-10-15；LE-20261015-01 的修复件）
==============================================================
背景（真实运行实证）：同一份 ch08 draft_R2.md 出现三个净字数——
撰稿自报 1203 / 审查官复核 1213 / 主理人脚本复核 1329。三方都声称
按「剔除 frontmatter/图表位/数据标签/缺口清单」统计，但口径无法复现，
字数验收门禁（1200±5%）实际不可判。本脚本把口径写死为代码，杜绝自报。

口径（唯一权威，禁止口头再解释）：
  1. 剔除 YAML frontmatter（首对 --- 之间）；
  2. 剔除整行图表位/习题位标记：以 [图 / [表 / [习题位 开头的行；
  3. 剔除行内数据标签：[实…]/[估…]/[引…]/[待核实…]（含 ·reason 与中文冒号变体）；
  4. 从首个元信息标题行起截断到文末：数据缺口清单 / 缺口清单 / 裁决执行 /
     引用统计 / 审查意见；
  5. 计入 Markdown 标题行字符（出版字数统计惯例，且与撰稿/审查两方自报口径一致）；
     --exclude-headings 可切换为严格正文口径；
  6. 只统计汉字 [\u4e00-\u9fff]；英文缩写/数字/标点一律不计（与教材「净字数」惯例一致）。

用法：
  python3 scripts/count_net_words.py 章节/ch08/draft_R2.md
  python3 scripts/count_net_words.py draft.md --target 1200 --tol 0.05   # 带门禁判定
  python3 scripts/count_net_words.py --self-test                        # 自检内置夹具
退出码：0 成功（带 --target 时=达标）；1 不达标；2 文件缺失
"""

import argparse
import re
import sys
from pathlib import Path

_HAN = re.compile(r"[\u4e00-\u9fff]")
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.S)
_BLOCK_MARK = re.compile(r"^\s*\[(图|表|习题位)\b.*$", re.M)
_INLINE_MARK = re.compile(r"\[(图|表|习题位)[^\]]*\]")   # 行内变体（不独立成行的图表位）
_INLINE_TAG = re.compile(r"\[(实|估|引|待核实)[^\]]*\]")
_META_SECTION = re.compile(
    r"^#{1,6}\s*(数据缺口清单|缺口清单|裁决执行|引用统计|审查意见).*$", re.M)
_HEADING = re.compile(r"^\s*#{1,6}\s.*$", re.M)


def count_net_words(text: str, exclude_headings: bool = False) -> dict:
    """按上述口径计数，返回可审计的分步明细。"""
    steps = {}
    body = _FRONTMATTER.sub("", text, count=1)
    steps["去 frontmatter 后"] = _n(body)
    body = _BLOCK_MARK.sub("", body)
    steps["去图表位/习题位整行后"] = _n(body)
    body = _INLINE_MARK.sub("", body)
    body = _INLINE_TAG.sub("", body)
    steps["去行内标记与数据标签后"] = _n(body)
    m = _META_SECTION.search(body)
    if m:
        body = body[: m.start()]
    steps["截去元信息段后(含标题)"] = _n(body)
    if exclude_headings:
        body = _HEADING.sub("", body)
    steps["最终(标题行{})".format("剔除" if exclude_headings else "计入")] = _n(body)
    return {"steps": steps, "net_final": list(steps.values())[-1]}


def _n(s: str) -> int:
    return len(_HAN.findall(s))


def judge(net: int, target: int, tol: float) -> tuple[bool, str]:
    lo, hi = target * (1 - tol), target * (1 + tol)
    ok = lo <= net <= hi
    verdict = "达标" if ok else ("超出上限" if net > hi else "低于下限")
    return ok, f"净字数 {net} vs 目标 {target}±{tol:.0%}（{lo:.0f}–{hi:.0f}）→ {verdict}"


def self_test() -> int:
    """内置夹具：口径变更必须先改这里再改实现。

    逐段手工计数（只数汉字）：
      标题行「§1 认识病原」           → 认识病原        4
      正文「鸡群的免疫程序要落地。」   →                10
      图表位整行                      → 整行剔除        0
      「发病率可达…，具体参数…。」     → 发病率可达+具体参数 9（100% 与标签剔除）
      「- 数据缺口清单」「D2 毒力判定口径」列表行       → 6+6 = 12
      「## 数据缺口清单」起的元信息段   → 截断剔除        0
    含标题 = 4+10+9+12 = 35；剔标题 = 31
    """
    fixture = """---
章节号: ch99
实际净字数: 999
---

## §1 认识病原

鸡群的免疫程序要落地。[图 1：结构示意｜纯示意（无数据支撑）]

发病率可达 100%[实：PMID:36126448]，具体参数[待核实·reason=检索未覆盖]。

- 数据缺口清单
- D2 毒力判定口径

## 数据缺口清单
这些字不应被计入净字数统计。
"""
    want_with = 35
    want_without = 31
    got_with = count_net_words(fixture)["net_final"]
    got_without = count_net_words(fixture, exclude_headings=True)["net_final"]
    ok1, ok2 = got_with == want_with, got_without == want_without
    print(f"[self-test] 含标题: 期望 {want_with} / 实得 {got_with} → {'PASS' if ok1 else 'FAIL'}")
    print(f"[self-test] 剔标题: 期望 {want_without} / 实得 {got_without} → {'PASS' if ok2 else 'FAIL'}")
    return 0 if (ok1 and ok2) else 1


def main() -> int:
    if "--self-test" in sys.argv:          # 必须在 argparse 之前——--self-test 不是合法选项
        return self_test()
    ap = argparse.ArgumentParser(description="净字数 SSOT 计数器")
    ap.add_argument("file", nargs="?", help="被统计的 markdown 文件")
    ap.add_argument("--exclude-headings", action="store_true",
                    help="剔除标题行字符（默认计入，出版惯例）")
    ap.add_argument("--target", type=int, help="目标净字数（触发门禁判定）")
    ap.add_argument("--tol", type=float, default=0.05, help="容差（默认 0.05）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.file is None:
        ap.error("缺少文件参数（或用 --self-test 自检）")

    p = Path(args.file)
    if not p.is_file():
        print(f"[count_net_words] 文件不存在: {p}", file=sys.stderr)
        return 2
    r = count_net_words(p.read_text(encoding="utf-8"),
                        exclude_headings=args.exclude_headings)
    if args.json:
        import json
        print(json.dumps({"file": str(p), "net": r["net_final"], "steps": r["steps"]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"净字数（SSOT 口径）: {r['net_final']}")
        for k, v in r["steps"].items():
            print(f"  {k}: {v}")
    if args.target is not None:
        ok, msg = judge(r["net_final"], args.target, args.tol)
        print(msg)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
