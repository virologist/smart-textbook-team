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

# 安装根解析（N-2，2026-11-01）：EXPERT_DIR 环境变量 > 两个宿主根兜底
# （WorkBuddy=.workbuddy / CodeBuddy=.codebuddy）> 仓库自身（见 DEFAULT_EXPERT_DIR）。
_INSTALL_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), host, "plugins", "marketplaces",
                 "my-experts", "plugins", "smart-textbook-team")
    for host in (".workbuddy", ".codebuddy")
]
_INSTALL_DIR = os.environ.get("EXPERT_DIR") or next(
    (p for p in _INSTALL_CANDIDATES if os.path.isdir(p)), _INSTALL_CANDIDATES[0])
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 与 test_smart_textbook_team.py 同策略：CI/纯 clone 态回落到仓库自身
DEFAULT_EXPERT_DIR = (
    _REPO_DIR
    if os.path.exists(os.path.join(_REPO_DIR, ".codebuddy-plugin", "plugin.json"))
    else _INSTALL_DIR
)
CB = os.path.join(".codebuddy-plugin", "plugin.json")
TEAM_LEAD_ID = "smart-textbook-team-team-lead"  # 供 M10 体积门禁用
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

    # M9a 第三份清单 .claude-plugin/marketplace.json 版本同步（2026-10-15 独立诊断项 7）
    mp_path = os.path.join(d, ".claude-plugin", "marketplace.json")
    if os.path.exists(mp_path):
        try:
            mp = json.loads(open(mp_path, encoding="utf-8").read())
            mp_ver = (mp.get("metadata") or {}).get("version")
            pl0 = (mp.get("plugins") or [{}])[0]
            ok = (mp_ver == cb.get("version") and pl0.get("version") == cb.get("version")
                  and norm_skills(pl0.get("skills")) == s_cb)
            r.add("M9a", ".claude-plugin/marketplace.json 版本/技能同步",
                  ok, f"metadata={mp_ver} plugin={pl0.get('version')}")
        except json.JSONDecodeError as e:
            r.add("M9a", ".claude-plugin/marketplace.json 可解析", False, str(e))

    # M10 散文漂移门禁（2026-10-15 re-audit P1-1）：README 版本/技能数/常驻核心
    # 体积与实际文件比对——所有声明必须能在磁盘即时核出,推不动就红
    readme = os.path.join(d, "README.md")
    if os.path.exists(readme):
        rt = open(readme, encoding="utf-8").read()
        # ① README 头部版本号必须等于 plugin.json version
        m = re.search(r"版本\s*([0-9]+\.[0-9]+\.[0-9]+)", rt)
        rv = m.group(1) if m else None
        r.add("M10a", "README 头部版本号 == plugin.json version",
              rv == cb.get("version"),
              f"README={rv} plugin={cb.get('version')}")
        # ② README 声明的技能数（如「6 个 skill」）必须与 ls skills/ 实际目录数一致
        m2 = re.search(r"(\d+)\s*(?:个\s*)?skills?\b", rt, re.I)
        claimed = int(m2.group(1)) if m2 else None
        actual = sum(1 for x in os.listdir(os.path.join(d, "skills"))
                     if os.path.isdir(os.path.join(d, "skills", x)))
        r.add("M10b", "README 声明技能数 == skills/ 实际目录数",
              claimed == actual,
              f"声明 {claimed} / 实际 {actual}")
        # ③ README 声明的「主理人常驻核心 X KB」必须与 wc -c 误差 ≤ 1KB
        # 校验**所有**主理人体积声明（2026-10-30 修正：原用 search 只查第一个，
        # README 正文别处出现旧值 13.4KB 时不会被发现 —— 实测确实存在第二处残留）。
        # 排除表格行：里程碑表里的 "team-lead 22.1KB→6.8KB" 是**历史数值**，
        # 不是当前态声明，拿它比对会把历史演进记录误判为漂移。
        claims: list[float] = []
        for ln in rt.splitlines():
            if ln.lstrip().startswith("|"):
                continue
            claims += [float(x) for x in re.findall(
                r"主理人[^。\n]*?([0-9]+\.?[0-9]*)\s*KB", ln)]
        if claims:
            lead_bytes = os.path.getsize(os.path.join(d, "agents", f"{TEAM_LEAD_ID}.md"))
            actual_kb = lead_bytes / 1024
            # 文档声明的 KB 通常是 13.4 / 6.8 这种粗略值,允许 ±2 KB 容差
            bad = [(c, round(actual_kb, 1)) for c in claims
                   if abs(actual_kb - c) > 2.0]
            r.add("M10c", "README 全部主理人体积声明 ≈ wc -c 实际(±2KB)",
                  not bad,
                  f"实际 {actual_kb:.1f} KB；不符声明: {bad}" if bad else "")
        else:
            r.add("M10c", "README 含主理人体积声明（可推断）", False, "未匹配到 KB 声明")
    else:
        for sub in ("M10a", "M10b", "M10c"):
            r.add(sub, f"README.md 存在（{sub} 前置）", False, readme + " 不存在")

    # M9 声明路径真实存在
    miss_paths = []
    for rel in list(cb.get("agents", [])) + list(cb.get("skills", [])):
        if not os.path.exists(os.path.join(d, rel.lstrip("./"))):
            miss_paths.append(rel)
    r.add("M9", "声明的 agents/skills 路径均存在", not miss_paths, f"缺失: {miss_paths}")

    # ── M11：安装态可达性（2026-10-29 补，横向归因总纲）───────────────────
    # 判据不是「源文件存在」，而是「install.sh 会把它带到安装态」。
    # 实测教训：role-assembly.md 迁入 references/ 后源仓一切正常、4 道门禁全绿，
    # 但 install.sh 复制清单不含 references/ → 安装态资源清单全是死链，
    # 且 [[ -e ]] 对已迁走的包根条目判假后**静默跳过**，无任何报错。
    inst = os.path.join(d, "install.sh")
    inst_txt = ""
    if os.path.isfile(inst):
        with open(inst, encoding="utf-8") as f:
            inst_txt = f.read()
    m_for = re.search(r"for item in ([^;]*?);\s*do", inst_txt, re.S)
    items = re.findall(r"[\w./\-]+", m_for.group(1)) if m_for else []
    r.add("M11a", "install.sh 复制清单含 references/（安装态资源不丢）",
          "references" in items, f"清单实际: {items}")
    # 死条目检测：清单里列出的条目必须在源仓存在，否则静默跳过、永不报错
    dead = [it for it in items if not os.path.exists(os.path.join(d, it))]
    r.add("M11b", "install.sh 复制清单无死条目（源仓已不存在的路径）",
          not dead, f"死条目: {dead}")
    # 运行期依赖：scripts/ 缺失会让 assemble/progress/record_trace 全部不可用
    r.add("M11c", "install.sh 复制清单含 scripts/（运行期脚本可达）",
          "scripts" in items, f"清单实际: {items}")

    # ── M12：PowerShell 安装路径（2026-10-30 补）─────────────────────────
    # 实测教训：install.ps1 此前**完全未被任何门禁覆盖**，清单里既无 references，
    # 又缺 scripts/tests/vendor/.claude-plugin，还留着已迁走的 role-assembly.md。
    # → Windows 安装态连 assemble_spawn_prompt.py 都不存在，且无人报警。
    ps1 = os.path.join(d, "install.ps1")
    ps1_txt = ""
    if os.path.isfile(ps1):
        with open(ps1, encoding="utf-8") as f:
            ps1_txt = f.read()
    m_ps = re.search(r"\$items\s*=\s*@\((.*?)\)", ps1_txt, re.S)
    ps_items = re.findall(r"'([\w./\-]+)'", m_ps.group(1)) if m_ps else []
    r.add("M12a", "install.ps1 复制清单含 references/ 与 scripts/",
          "references" in ps_items and "scripts" in ps_items,
          f"清单实际: {ps_items}")
    dead_ps = [it for it in ps_items if not os.path.exists(os.path.join(d, it))]
    r.add("M12b", "install.ps1 复制清单无死条目",
          not dead_ps, f"死条目: {dead_ps}")
    # 与 install.sh 的核心目录集合对齐（防止两个安装器长期分叉）
    core = {"agents", "skills", "scripts", "references"}
    r.add("M12c", "install.ps1 与 install.sh 核心目录集合一致",
          core.issubset(set(ps_items)) and core.issubset(set(items)),
          f"ps1 缺 {sorted(core - set(ps_items))}；sh 缺 {sorted(core - set(items))}")

    # ── M13：skills 声明 ↔ 实际目录 双向一致（2026-10-30 补）──────────────
    # 实测教训：新增 skills/manuscript-delivery/ 后只改了 README，三处 plugin.json
    # 与 marketplace.json 的 skills 数组全部漏声明 → 安装态不会加载该 skill，
    # 而既有门禁全部放行：M7 只查「install.sh 覆盖了【已声明】的技能」，
    # M10b 只查「README 声明数 == 目录数」。**「目录里有但未声明」这一侧无人看守**。
    skills_dir = os.path.join(d, "skills")
    actual_skills = {x for x in os.listdir(skills_dir)
                     if os.path.isdir(os.path.join(skills_dir, x))} if os.path.isdir(skills_dir) else set()
    declared_skills = {s.strip("./").split("/")[-1] for s in cb.get("skills", [])}
    undeclared = sorted(actual_skills - declared_skills)
    r.add("M13a", "skills/ 下每个目录都被 plugin.json 声明（防新增技能漏登记）",
          not undeclared, f"目录存在但未声明: {undeclared}")
    missing_dir = sorted(declared_skills - actual_skills)
    r.add("M13b", "plugin.json 声明的每个 skill 都有实际目录（防声明死链）",
          not missing_dir, f"已声明但目录缺失: {missing_dir}")
    # 与 M7（install.sh 技能覆盖）对称的 PowerShell 版本
    # 实测教训：install.ps1 三处技能循环长期只有 5 个（连 task-router 都缺），
    # 而 M7 只查 install.sh → PowerShell 安装态技能缺失无人报警。
    ps_skill_lists = re.findall(
        r"foreach\s*\(\$s\s+in\s+@\((.*?)\)\s*\)", ps1_txt, re.S)
    declared = {s.strip("./").split("/")[-1] for s in cb.get("skills", [])}
    short_ps = []
    for i, lst in enumerate(ps_skill_lists, 1):
        got = set(re.findall(r"'([^']+)'", lst))
        miss = sorted(declared - got)
        if miss:
            short_ps.append(f"第{i}处循环缺 {miss}")
    r.add("M12d", "install.ps1 每个平台循环均覆盖全部声明技能（M7 的 PowerShell 版）",
          bool(ps_skill_lists) and not short_ps,
          "；".join(short_ps) if short_ps else "未找到任何技能循环")

    # ── M14：安装态完整性门禁（2026-10-30 批次 A）──────────────────────
    # 背景：此前 M11/M12 只查「复制清单含 references/scripts」，
    # 但**清单里该有的项是否真被复制**无人看守——实测 install.sh 清单缺
    # avatars/ 与 settings.json → 安装态静态契约从 1.000 掉到 0.988
    # （A2b/A2d/A5a/F32a 四项 FAIL），而 CI 在纯 clone 态跑，**永远测不到**。
    # 现把「安装清单须覆盖包内所有需分发资源」变成可拦截项。
    def _install_items(txt: str) -> set:
        # install.sh: for item in a b c \n  d e; do   /  install.ps1: @('a','b')
        items = set()
        m = re.search(r"for\s+item\s+in\s+(.*?);", txt, re.S)
        if m:
            items |= {x for x in re.findall(r"[A-Za-z0-9_.\-/]+", m.group(1))}
        m2 = re.search(r"\$items\s*=\s*@\((.*?)\)", txt, re.S)
        if m2:
            items |= set(re.findall(r"'([^']+)'", m2.group(1)))
        return items

    sh_items = _install_items(txt)
    ps_items = _install_items(ps1_txt)
    # 包内需要随安装分发的资源（凡被 plugin.json 引用 或 是运行期必需）
    must_ship = {"agents", "skills", "scripts", "tests", "vendor", "references",
                 "avatars", ".codebuddy-plugin", ".claude-plugin", "settings.json"}
    miss_sh = sorted(must_ship - sh_items)
    miss_ps = sorted(must_ship - ps_items)
    r.add("M14a", "install.sh 复制清单覆盖全部需分发资源（含 avatars/settings.json）",
          not miss_sh, f"缺: {miss_sh}")
    r.add("M14b", "install.ps1 复制清单覆盖全部需分发资源（含 avatars/settings.json）",
          not miss_ps, f"缺: {miss_ps}")
    r.add("M14c", "两个安装器复制清单集合一致（防长期分叉）",
          sh_items == ps_items,
          f"仅 sh 有: {sorted(sh_items - ps_items)}；仅 ps1 有: {sorted(ps_items - sh_items)}")

    # D-1 自毁保护：源==目标时不得先删后拷
    r.add("M14d", "install.sh 存在「源=目标不删」保护（防自毁）",
          'if [[ "$REPO_DIR" == "$DEST" ]]' in txt,
          "缺少自毁保护 → 在安装态目录执行 install.sh 会清空整包")
    r.add("M14e", "install.ps1 存在「源=目标不删」保护（防自毁）",
          '$REPO_DIR -eq $DEST' in ps1_txt,
          "缺少自毁保护 → Windows 安装态执行会清空整包")

    # D-3/D-4 marketplace 注册：不得写空 plugins 数组
    r.add("M14f", "install.sh 实际写入 marketplace 注册条目（upsert 而非空数组占位）",
          "plugins.append(entry)" in txt,
          "无 upsert 写入动作 = 注释声称注册、实际未注册")
    r.add("M14g", "install.ps1 含 marketplace 注册动作",
          "marketplace.json" in ps1_txt and "upsert" in ps1_txt.lower(),
          "Windows 侧安装 = 纯目录拷贝，宿主找不到插件")

    # marketplace.json 与 plugin.json 的 skills 集合也必须一致
    try:
        mkp_skills = {s.strip("./").split("/")[-1]
                      for s in json.load(open(os.path.join(d, ".claude-plugin", "marketplace.json"),
                                              encoding="utf-8"))["plugins"][0].get("skills", [])}
        r.add("M13c", "marketplace.json 与 plugin.json 的 skills 集合一致",
              mkp_skills == declared_skills,
              f"marketplace 独有: {sorted(mkp_skills - declared_skills)}；"
              f"plugin 独有: {sorted(declared_skills - mkp_skills)}")
    except (OSError, KeyError, json.JSONDecodeError) as e:
        r.add("M13c", "marketplace.json 可解析且含 plugins[0].skills", False, str(e)[:120])

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
