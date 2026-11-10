#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_redlane_registry.py — 红道登记 / 版本各处声明自洽 检查（改造批次，2026-11-10）

==============================================================================
审计（★L 批次 §3.2/3.4、decision-lanes §3.1）确认两类「机械护栏缺失」：
  (1) CHANGELOG.md / SKILL_CHANGELOG.md 为 IMMUNE_FILES，自述不受一致性检查，
      导致「版本已升但 CHANGELOG 未登记该版本」这类问题不被任何门禁抓到；
  (2) 红道「SKILL_CHANGELOG 登记」步骤在 decision-lanes 里**无执行体**，
      改协议可以不登记就被合入。

本脚本把「版本各处声明自洽 + CHANGELOG 已登记当前版本」固化为确定性检查。
版本权威源与 package_release.sh 完全一致（源仓各处 manifest 必须自洽）：
  R1  .claude-plugin/plugin.json       "version"
  R2  .codebuddy-plugin/plugin.json    "version"（若存在）
  R3  .claude-plugin/marketplace.json  metadata.version 与 plugins[0].version
  R4  install.sh                       VERSION=
  R5  README.md                        "> 版本 X.Y.Z"（对外公示版本，要求一致）
  R6  CHANGELOG.md 顶部 `## [X.Y.Z]` 必须等于当前版本（已登记），
      否则判 FAIL：版本已升但 CHANGELOG 未登记该版本（红道登记缺口）

注：早期版本误读 `root/plugin.json`（该路径在真实包中不存在），导致真实插件
版本文件被静默忽略——已在 v2 中改为读取 `.claude-plugin/plugin.json` 等真实路径。

退出码：0 全通过 / 1 存在 FAIL / 2 输入缺失（核心声明文件读不到）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RE_README = re.compile(r"版本\s+(\d+\.\d+\.\d+)")
RE_INSTALL = re.compile(r'VERSION="(\d+\.\d+\.\d+)"')
RE_CHANGELOG = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.M)


def _read(p: str) -> str | None:
    fp = Path(p)
    return fp.read_text(encoding="utf-8", errors="ignore") if fp.is_file() else None


def _json(p: str) -> dict | None:
    txt = _read(p)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def check(root: str) -> dict:
    root_p = Path(root)
    if not root_p.is_dir():
        return {"ok": False, "exit": 2, "error": f"包根不存在：{root}"}

    versions: dict[str, str | None] = {}

    # R1 .claude-plugin/plugin.json
    cp = _json(root_p / ".claude-plugin" / "plugin.json")
    if cp is not None:
        versions[".claude-plugin/plugin.json"] = cp.get("version")

    # R2 .codebuddy-plugin/plugin.json（若存在）
    cbp = _json(root_p / ".codebuddy-plugin" / "plugin.json")
    if cbp is not None:
        versions[".codebuddy-plugin/plugin.json"] = cbp.get("version")

    # R3 marketplace.json（两处 version 字段）
    mk = _json(root_p / ".claude-plugin" / "marketplace.json")
    if mk is not None:
        versions[".claude-plugin/marketplace.json:metadata"] = (mk.get("metadata") or {}).get("version")
        plugs = mk.get("plugins") or []
        if plugs:
            versions[".claude-plugin/marketplace.json:plugins[0]"] = plugs[0].get("version")

    # R4 install.sh
    install = _read(root_p / "install.sh")
    if install is not None:
        m = RE_INSTALL.search(install)
        versions["install.sh"] = m.group(1) if m else None

    # R5 README
    readme = _read(root_p / "README.md")
    if readme is not None:
        m = RE_README.search(readme)
        versions["README.md"] = m.group(1) if m else None

    # R6 CHANGELOG 顶部
    changelog = _read(root_p / "CHANGELOG.md")
    changelog_top = None
    if changelog is not None:
        m = RE_CHANGELOG.search(changelog)
        changelog_top = m.group(1) if m else None

    present = {k: v for k, v in versions.items() if v is not None}
    results = []

    # R1-R5：已存在的声明必须互相等
    distinct = set(present.values())
    consistent = len(distinct) <= 1
    results.append({
        "id": "R1-R5", "name": "版本各处声明自洽",
        "pass": consistent,
        "detail": " / ".join(f"{k}={v}" for k, v in present.items()) if present
                  else "未找到任何版本声明",
    })

    # R6：CHANGELOG 顶部必须等于当前发布版本（已登记）。
    # 权威版本取 .claude-plugin/plugin.json（发布版本），缺失时回退 README。
    authority = versions.get(".claude-plugin/plugin.json") or versions.get("README.md") or \
        (next(iter(distinct)) if len(distinct) == 1 else None)
    changelog_ok = True
    detail = ""
    if changelog_top is None:
        changelog_ok = False
        detail = "CHANGELOG.md 顶部未解析到版本条目"
    elif authority is None:
        changelog_ok = False
        detail = "无法从 .claude-plugin/plugin.json / README 确定当前版本"
    elif changelog_top != authority:
        changelog_ok = False
        detail = (f"CHANGELOG 顶部={changelog_top}，当前版本(.claude-plugin/plugin.json)={authority} "
                  f"→ 版本已升但 CHANGELOG 未登记该版本（红道登记缺口）")
    else:
        detail = f"CHANGELOG 已登记当前版本 {changelog_top}"
    results.append({
        "id": "R6", "name": "CHANGELOG 已登记当前版本（红道登记）",
        "pass": changelog_ok,
        "detail": detail,
    })

    hard_fail = [r for r in results if not r["pass"]]
    return {
        "ok": len(hard_fail) == 0,
        "exit": 0 if len(hard_fail) == 0 else 1,
        "criteria": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="红道登记 / 版本各处声明自洽检查")
    ap.add_argument("--root", default=".", help="专家包根（默认 .）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    rep = check(args.root)
    if "error" in rep:
        sys.stderr.write(rep["error"] + "\n")
        return int(rep.get("exit", 2))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"红道登记检查：{args.root}")
        for r in rep["criteria"]:
            mark = "PASS" if r["pass"] else "FAIL"
            print(f"  [{mark}] {r['id']} {r['name']} — {r['detail']}")
        print(f"结论：{'全部通过' if rep['ok'] else '存在 FAIL'}")
    return int(rep.get("exit", 2))


if __name__ == "__main__":
    sys.exit(main())
