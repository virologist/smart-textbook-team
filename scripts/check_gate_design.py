#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_gate_design.py — 门禁 1（SPECIFY 后 · 教学设计完整性）确定性 linter

==============================================================================
门禁 1 原为主理人 AI 判定、无确定性检查（audit 已确认）。本脚本把其中可机械判的
判据固化，给出可自动判的信号；语义判据（知识域划分是否合理）仍留给人工。

判据（SSOT：pipeline SKILL §检索门禁 + team-lead Phase B 门禁 1）：
  G1.1 knowledge_scope 非空：设计须声明知识域（知识域 / 知识范围 / knowledge_scope），
       且其后有实质内容（非空、非纯占位）。
  G1.2 时数 ≥ 1：设计须声明教学时数，且为整数 ≥ 1。
  G1.3 含知识块锚区块：设计须含「知识块锚点」区块（关键字 知识块 / 锚点 / anchor 任一），
       作为检索锚定的基准（team-lead Phase B「必含知识块锚区块」）。

退出码：0 全部 PASS（可含 WARN）/ 1 存在 FAIL / 2 输入缺失或判据自身失效
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RE_SCOPE_HEAD = re.compile(r"^#{1,6}\s*.*?(知识域|知识范围|knowledge_scope).*?$", re.I | re.M)
RE_SCOPE_KV = re.compile(r"^\s*(知识域|知识范围|knowledge_scope)\s*[:：]\s*(.+)$", re.I)
RE_HOURS = re.compile(r"(时数|学时)\s*[:：]\s*(\d+)", re.I)
RE_ANCHOR = re.compile(r"知识块|锚点|anchor", re.I)


def _sections(text: str) -> list[tuple[str, str]]:
    """切分为 (标题行, 正文) 列表，供「某标题下是否有内容」判定。"""
    parts = re.split(r"(?m)^(#{1,6}\s+.*)$", text)
    out: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        head = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out.append((head, body))
    return out


def check(design_path: str) -> dict:
    p = Path(design_path)
    if not p.is_file():
        return {"ok": False, "exit": 2, "criteria": [],
                "error": f"设计文件不存在：{design_path}"}
    text = p.read_text(encoding="utf-8")
    results = []

    # G1.1 knowledge_scope 非空
    scope_ok = False
    m = RE_SCOPE_KV.search(text)
    if m and m.group(2).strip() and not re.fullmatch(r"[\s\-—待补]*", m.group(2).strip()):
        scope_ok = True
    else:
        for head, body in _sections(text):
            if RE_SCOPE_HEAD.match(head):
                if body.strip() and not re.fullmatch(r"[\s\-—待补]*", body.strip()):
                    scope_ok = True
                break
    results.append({
        "id": "G1.1", "name": "knowledge_scope 非空",
        "pass": scope_ok,
        "detail": "已声明知识域且有实质内容" if scope_ok else "未找到非空的知识域声明（知识域/知识范围/knowledge_scope）",
    })

    # G1.2 时数 ≥ 1
    hours_ok = False
    hm = RE_HOURS.search(text)
    if hm:
        try:
            hours_ok = int(hm.group(2)) >= 1
        except ValueError:
            hours_ok = False
    results.append({
        "id": "G1.2", "name": "时数 ≥ 1",
        "pass": hours_ok,
        "detail": f"时数={hm.group(2) if hm else '未找到'}" + ("" if hours_ok else "（须为整数 ≥ 1）"),
    })

    # G1.3 知识块锚区块
    anchor_ok = bool(RE_ANCHOR.search(text))
    results.append({
        "id": "G1.3", "name": "含知识块锚区块",
        "pass": anchor_ok,
        "detail": "存在知识块锚点区块" if anchor_ok else "未找到知识块/锚点/anchor 区块（team-lead 要求必含）",
    })

    passed = sum(1 for r in results if r["pass"])
    failed = [r for r in results if not r["pass"]]
    return {
        "ok": len(failed) == 0,
        "exit": 0 if len(failed) == 0 else 1,
        "passed": passed,
        "total": len(results),
        "criteria": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="门禁 1 教学设计完整性 linter")
    ap.add_argument("--design", required=True, help="chapter_design.md 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    rep = check(args.design)
    # 输入缺失必须显式报错并退出 2，禁止落到空 criteria 上打印「0 项未通过」
    # ——那会把「判据没跑」在文字上伪装成「判据全过」（静默吞错）。
    if "error" in rep:
        sys.stderr.write(f"[check_gate_design] 输入缺失：{rep['error']}\n")
        return int(rep.get("exit", 2))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"门禁 1 检查：{args.design}")
        for r in rep["criteria"]:
            mark = "PASS" if r["pass"] else "FAIL"
            print(f"  [{mark}] {r['id']} {r['name']} — {r['detail']}")
        failed_n = len([r for r in rep["criteria"] if not r["pass"]])
        print(f"结论：{'全部通过' if rep['ok'] else f'{failed_n} 项未通过'}")
    return int(rep.get("exit", 2))


if __name__ == "__main__":
    sys.exit(main())
