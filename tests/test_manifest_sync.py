#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台清单同步门禁（P0-3，2026-10-15）
======================================
背景：R9/harness 升级新增 task-router 技能与 v2.1.0 版本号时，只改了
      .codebuddy-plugin/plugin.json，.claude-plugin/plugin.json 与 install.sh 三处
      技能列表未同步 → Claude Code / Desktop / Cursor 用户拿不到 task-router，
      且两清单版本号漂移（2.1.0 vs 2.0.0）。本门禁把这类漂移做成硬失败。

必一致字段（跨平台语义相同）：name / version / description / skills / author.name
平台专有字段（允许差异，不校验）：expertType / agentName / teamInfo / members /
      displayName / profession / displayDescription / avatar / categoryId /
      quickPrompts / defaultInitPrompt / plugin / homepage / keywords / license / repository

检查项：
  M1 两份 plugin.json 均存在且可解析
  M2 name 一致
  M3 version 一致
  M4 skills 集合一致（顺序无关）
  M5 description 一致
  M6 author.name 一致
  M7 install.sh 三处技能复制列表覆盖全部声明技能（防漏装）
  M8 install.sh VERSION == plugin.json version
  M9 声明的 agents/skills 路径在磁盘真实存在

用法：python3 tests/test_manifest_sync.py [--expert-dir 路径] [--json]
"""

import argparse
import json
import os
import re
import sys

DEFAULT_EXPERT_DIR = os.path.expanduser(
    "~/.workbuddy/plugins/marketplaces/my-experts/plugins/smart-textbook-team"
)
CB = os.path.join(".codebuddy-plugin", "plugin.json")
CC = os.path.join(".claude-plugin", "plugin.json")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except OSError as e:
        return None, str(e)
    except json.JSONDecodeError as e:
        return None, str(e)


class R:
    def __init__(self):
        self.items = []

    def add(self, cid, desc, ok, detail=""):
        self.items.append((cid, desc, bool(ok), detail if not ok else ""))

    @property
    def failed(self):
        return [i for i in self.items if not i[2]]


def norm_skills(lst):
    return sorted(s.strip("./") for s in lst or [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expert-dir", default=DEFAULT_EXPERT_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    d = args.expert_dir
    r = R()

    cb, e1 = load(os.path.join(d, CB))
    cc, e2 = load(os.path.join(d, CC))
    r.add("M1", "两份 plugin.json 均存在且可解析",
          cb is not None and cc is not None, f"codebuddy: {e1} | claude: {e2}")
    if cb is None or cc is None:
        return emit(r, args.json)

    r.add("M2", "name 一致", cb.get("name") == cc.get("name"),
          f"{cb.get('name')} vs {cc.get('name')}")
    r.add("M3", "version 一致", cb.get("version") == cc.get("version"),
          f"{cb.get('version')} vs {cc.get('version')}")
    s_cb, s_cc = norm_skills(cb.get("skills")), norm_skills(cc.get("skills"))
    r.add("M4", f"skills 集合一致（{len(s_cb)} vs {len(s_cc)}）", s_cb == s_cc,
          f"仅 codebuddy: {sorted(set(s_cb) - set(s_cc))} | 仅 claude: {sorted(set(s_cc) - set(s_cb))}")
    r.add("M5", "description 一致", cb.get("description") == cc.get("description"),
          f"cb={str(cb.get('description'))[:60]}… vs cc={str(cc.get('description'))[:60]}…")
    r.add("M6", "author.name 一致",
          (cb.get("author") or {}).get("name") == (cc.get("author") or {}).get("name"),
          f"{(cb.get('author') or {}).get('name')} vs {(cc.get('author') or {}).get('name')}")

    # M7 / M8 install.sh
    ish = os.path.join(d, "install.sh")
    txt = ""
    if os.path.exists(ish):
        with open(ish, encoding="utf-8") as f:
            txt = f.read()
    r.add("M7a", "install.sh 存在", bool(txt), ish)
    if txt:
        blocks = re.findall(r"for s in ([a-z\- ]+); do", txt)
        covered = set()
        for b in blocks:
            covered |= set(b.split())
        # 声明值是路径 skills/xxx，install.sh 循环里是裸名 xxx —— 统一取末段比较
        declared = {s.strip("./").split("/")[-1] for s in (s_cb + s_cc)}
        # 逐个循环校验（不能取并集——并集会让「某单一平台漏装」被其他平台掩盖）
        per_block_miss = []
        for i, b in enumerate(blocks, 1):
            gap = sorted(declared - set(b.split()))
            if gap:
                per_block_miss.append(f"第{i}处循环缺 {gap}")
        miss = per_block_miss
        r.add("M7", f"install.sh 每个平台循环均覆盖全部 {len(declared)} 个声明技能",
              not miss and blocks,
              f"{'; '.join(miss)}（共 {len(blocks)} 处循环，逐处校验）"
              if miss else ("" if blocks else "未发现技能循环块"))
        m = re.search(r'^VERSION="([^"]+)"', txt, re.M)
        r.add("M8", "install.sh VERSION == plugin.json version",
              bool(m) and m.group(1) == cb.get("version"),
              f"install.sh {m.group(1) if m else None} vs plugin {cb.get('version')}")

    # M9 声明路径真实存在
    miss_paths = []
    for rel in list(cb.get("agents", [])) + list(cb.get("skills", [])):
        if not os.path.exists(os.path.join(d, rel.lstrip("./"))):
            miss_paths.append(rel)
    r.add("M9", "声明的 agents/skills 路径均存在", not miss_paths, f"缺失: {miss_paths}")

    return emit(r, args.json)


def emit(r, as_json):
    failed = r.failed
    if as_json:
        print(json.dumps({"total": len(r.items), "failed": len(failed),
                          "items": [{"id": i[0], "desc": i[1], "pass": i[2],
                                     "detail": i[3]} for i in r.items]},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("跨平台清单同步门禁")
        print("=" * 62)
        for cid, desc, ok, detail in r.items:
            print(f"  {'✓' if ok else '✗'} [{cid}] {desc}")
            if detail:
                print(f"          → {detail}")
        print("-" * 62)
        print(f"检查项 {len(r.items)} | 通过 {len(r.items) - len(failed)} | 失败 {len(failed)}")
        print("=" * 62)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
