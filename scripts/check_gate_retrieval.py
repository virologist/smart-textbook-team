#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_gate_retrieval.py — 门禁 2（RETRIEVE 后 · 检索质量）确定性 linter

==============================================================================
门禁 2 原为主理人 AI 判定、无确定性检查（audit 已确认）。本脚本把其中可机械判的
判据固化为信号；语义判据（多源冲突是否真冲突、证据是否真支撑论点）仍留给人工。

判据（SSOT：pipeline SKILL §检索门禁）：
  G2.1 覆盖率：数据型陈述须带 [实]/[估]/[引]/[待核实] 之一；无标签率应 ≤20%
        （代理口径：检索稿中含数值触发词的行，带标签的比例 ≥80% → PASS）
  G2.2 时效性：流行病学数据近 10 年占比 ≥80%（按行内 4 位年份统计）
  G2.3 冲突率：多源冲突数据 <20% 且已列明 —— 机械层面只能「发现冲突标记并报告」，
        是否真冲突由人工裁决，故本项为 WARN（不自动 FAIL）

退出码：0 全部 PASS（冲突项可为 WARN）/ 1 存在硬 FAIL（覆盖率/时效性 <80%）/ 2 输入缺失
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# 数据型陈述行的识别：通用层保持学科中立——不写死兽医/流行病学等学科词，
# 而是用「含数值（整数/小数/百分数）」这一学科无关判据识别数据型行。
# 具体学科词（发病率/效价/日龄…）应下沉到 profiles/，不污染通用门禁脚本。
RE_NUM = re.compile(r"\d+(?:\.\d+)?\s*(?:%|倍|例|万|元|kg|mg|ml|年|月|天|周|°C|ppm)?")
RE_TAG = re.compile(r"\[(实|估|引|待核实)\]")
RE_YEAR = re.compile(r"(1[89]\d{2}|20\d{2})")
RE_CONFLICT = re.compile(r"冲突|矛盾|contradict|不一致", re.I)


def _retrieval_text(retrieval_dir: str) -> str:
    d = Path(retrieval_dir)
    if not d.is_dir():
        return ""
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in sorted(d.glob("*.md"))
    )


def check(design_path: str, retrieval_dir: str, strict: bool = False) -> dict:
    design = Path(design_path)
    if not design.is_file():
        return {"ok": False, "exit": 2, "error": f"设计文件不存在：{design_path}"}
    rtext = _retrieval_text(retrieval_dir)
    if not rtext.strip():
        return {"ok": False, "exit": 2, "error": f"检索目录无内容：{retrieval_dir}"}

    lines = [ln for ln in rtext.splitlines() if RE_NUM.search(ln)]
    tagged = [ln for ln in lines if RE_TAG.search(ln)]
    cov = (len(tagged) / len(lines)) if lines else 1.0
    cov_pass = cov >= 0.80

    years = [int(y) for y in RE_YEAR.findall(rtext)]
    cur = date.today().year
    recent = [y for y in years if cur - 10 < y <= cur]
    rec = (len(recent) / len(years)) if years else 1.0
    rec_pass = rec >= 0.80

    conflicts = len(RE_CONFLICT.findall(rtext))

    results = [
        {
            "id": "G2.1", "name": "覆盖率 ≥80% 数据带标签",
            "pass": cov_pass, "level": "FAIL",
            "detail": f"数据型行 {len(lines)}，带标签 {len(tagged)}，覆盖率 {cov*100:.1f}%",
        },
        {
            "id": "G2.2", "name": "时效性 近10年 ≥80%",
            "pass": rec_pass, "level": "FAIL",
            "detail": f"年份样本 {len(years)}，近10年 {len(recent)}，占比 {rec*100:.1f}%",
        },
        {
            "id": "G2.3", "name": "冲突项已列明（人工裁决）",
            "pass": True, "level": "WARN",
            "detail": f"检出冲突标记 {conflicts} 处（本项不自动 FAIL，交由人工裁定是否真冲突）",
        },
    ]
    hard_fail = [r for r in results if r["level"] == "FAIL" and not r["pass"]]
    return {
        "ok": len(hard_fail) == 0,
        "exit": 0 if len(hard_fail) == 0 else 1,
        "criteria": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="门禁 2 检索质量 linter")
    ap.add_argument("--design", required=True, help="chapter_design.md 路径")
    ap.add_argument("--retrieval-dir", required=True, help="检索产物目录（含 *.md）")
    ap.add_argument("--strict", action="store_true", help="保留位（冲突项始终 WARN）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    rep = check(args.design, args.retrieval_dir, args.strict)
    if "error" in rep:
        sys.stderr.write(f"[check_gate_retrieval] {rep['error']}\n")
        return int(rep.get("exit", 2))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"门禁 2 检查：{args.retrieval_dir}")
        for r in rep["criteria"]:
            # 显示标记：未通过且为硬失败类→FAIL；WARN 类→WARN；其余→PASS。
            # 不改变退出码（退出码只看 hard_fail 列表）。
            if r.get("level") == "WARN":
                mark = "WARN"
            elif r.get("level") == "FAIL" and not r["pass"]:
                mark = "FAIL"
            else:
                mark = "PASS"
            print(f"  [{mark}] {r['id']} {r['name']} — {r['detail']}")
        print(f"结论：{'全部通过' if rep['ok'] else '存在硬 FAIL（覆盖率/时效性 <80%）'}")
    return int(rep.get("exit", 2))


if __name__ == "__main__":
    sys.exit(main())
