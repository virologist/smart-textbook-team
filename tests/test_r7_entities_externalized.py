#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_r7_entities_externalized.py — R7 判据数据外置回归（★L v2.11.2，审计项 E/F1 收口）

==============================================================================
为什么需要：v2.10.2 固化 R7 时三词典（120/32/73）+ 数值单位表写死在 scripts/
通用层，触发「学科中立性门禁」CI 自 2026-11-04 起连续红灯（22 处 HARD + 2 路径）。
v2.11.2 把完整判据数据外置到 references/profiles/（门禁豁免的学科化数据源唯一
合法落点）。本测试锁三件事：
  T1 数据文件存在且 schema 合法（含 num_units 四键——反向例：缺键必须报错）
  T2 判定行为不变（数值+单位 / 区间 / 中文计数 / 实体抽取 / §7b 覆盖链）
  T3 门禁全绿（包根自扫 0 FAIL）+ 通用层脚本零学科 HARD 词（防回潮）

用法：python3 tests/test_r7_entities_externalized.py
退出码：0 全过 | 1 有失败项
==============================================================================
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "tests"))

import verify_citations_r7 as r7  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def ck(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} [{name}]{' ' + detail if detail and not ok else ''}")


def t1_data_file() -> None:
    """数据文件在位、schema 合法、四键齐备；损坏必须显式报错（不静默回落）。"""
    p = _REPO / "references" / "profiles" / "r7-entities-veterinary.json"
    ck("T1.1 数据文件存在", p.is_file(), str(p))
    d = json.loads(p.read_text(encoding="utf-8"))
    ck("T1.2 schema=r7-entities/v1", d.get("schema") == "r7-entities/v1")
    ck("T1.3 四键齐备",
       all(k in d for k in ("entity_map", "generic_entities", "theme_entities", "num_units")))
    ck("T1.4 num_units 四键齐备",
       all(k in d["num_units"] for k in ("NUM_RE", "NUM_TIGHT", "NUM_CN", "num_hit")))
    ck("T1.5 词典规模（120/32/73）",
       len(d["entity_map"]) == 120 and len(d["generic_entities"]) == 32
       and len(d["theme_entities"]) == 73,
       f"{len(d['entity_map'])}/{len(d['generic_entities'])}/{len(d['theme_entities'])}")
    # 反向例：坏文件必须 raise，禁止静默空词典
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write('{"schema": "wrong"}')
        bad = f.name
    try:
        r7.load_entity_data(bad)
        ck("T1.6 坏 schema 报错", False, "未抛异常")
    except ValueError:
        ck("T1.6 坏 schema 报错", True)
    finally:
        os.unlink(bad)
    try:
        r7.load_entity_data(_REPO / "nonexistent.json")
        ck("T1.7 缺文件报错", False, "未抛异常")
    except FileNotFoundError:
        ck("T1.7 缺文件报错", True)


def t2_behavior_unchanged() -> None:
    """判定行为与外置前逐位一致（v5 迭代史的三处实证样本回归）。"""
    # ① '80 %-100 %' 空格形态（v5 修正样本 41352071）
    ck("T2.1 数值+单位空格命中",
       r7.num_hit("all vaccines provided 80 %-100 % protection from mortality".lower(), "80"))
    # ② 区间两数分别捕获
    nums = []
    for a, b in r7.NUM_RE.findall("25~50 ppm"):
        nums.append(a)
        if b:
            nums.append(b)
    ck("T2.2 区间两数捕获", nums == ["25", "50"], str(nums))
    # ③ 中文计数
    ck("T2.3 中文计数", bool(r7.NUM_CN.search("共 1568 例感染")))
    # ④ 实体抽取（含 §7b 覆盖链）
    zh, _ = r7.entities_in("鸡舍氨气读数达到 100 ppm 时出现角膜溃疡")
    ck("T2.4 实体抽取", "氨气" in zh, str(zh))
    # ⑤ §7b 加载链完好
    emap_c, th_c, w_c = r7.load_profile_entities("computer-science")
    ck("T2.5 CS §7b 覆盖", bool(emap_c) and bool(th_c) and w_c is None)
    # ⑥ 数据驱动正则与旧 pattern 字面等价（快照对照）
    units_re = "|".join(__import__("re").escape(u) for u in
                        json.loads((_REPO / "references" / "profiles" /
                                    "r7-entities-veterinary.json").read_text(encoding="utf-8"))
                        ["num_units"]["NUM_RE"])
    expect = (r"(\d+(?:\.\d+)?)(?:\s*[~～\-—至]\s*(\d+(?:\.\d+)?))?\s*(?:" + units_re + r")")
    ck("T2.6 NUM_RE pattern 字面等价", r7.NUM_RE.pattern == expect)


def t3_gate_green() -> None:
    """学科中立门禁包根自扫 0 FAIL；通用层脚本零 HARD 词（防回潮探针由 CI 负责）。"""
    proc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "check_domain_neutral.py"),
         "--root", str(_REPO), "--json"],
        capture_output=True, text=True)
    try:
        d = json.loads(proc.stdout)
        hard = len(d.get("hard_hits", [])) + len(d.get("audience_hard_hits", []))
        paths = len(d.get("path_hits", []))
    except json.JSONDecodeError:
        hard, paths = -1, -1
    ck("T3.1 门禁 0 HARD", hard == 0, f"hard={hard}")
    ck("T3.2 门禁 0 路径违规", paths == 0, f"paths={paths}")
    ck("T3.3 门禁 exit 0", proc.returncode == 0, f"rc={proc.returncode}")


def main() -> int:
    print("=" * 62)
    print("R7 判据数据外置回归（★L v2.11.2）")
    print("=" * 62)
    t1_data_file()
    t2_behavior_unchanged()
    t3_gate_green()
    n_fail = sum(1 for _, ok, _ in CHECKS if not ok)
    print("-" * 62)
    print(f"检查项 {len(CHECKS)} | 通过 {len(CHECKS) - n_fail} | 失败 {n_fail}")
    print("=" * 62)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
