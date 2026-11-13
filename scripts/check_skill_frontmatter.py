#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
check_skill_frontmatter.py — 包内 Skill「frontmatter + 版本演进记录」门禁（2026-11-10 批次 S7）

==============================================================================
为什么需要：S1 批次把「契约评测用例集」门禁化后，darwin 复诊指出**另一半
成果没被锁死**——各 Skill 的 frontmatter 与版本演进记录仍是**纯散文约定**：

  ① version 字段：10 个 Skill 的 frontmatter 里都有，但**零机械护栏**。
     谁把 `version: 1.8.0` 改成 `1.8`（非法 semver）、或整行删掉，
     平台侧照样加载成功——版本位静默腐化，下游（CHANGELOG / 变更记录 /
     安装清单）全部对不上，且没有任何一步会红。
  ② 变更记录节：10 个 Skill 中 3 个**完全没有**版本演进记录节
     （agent-harness-protocol / learn-protocol / textbook-pipeline-workflow），
     其余 7 个节名还不统一（`## 变更记录` vs `## 7. Changelog`），
     **全仓 0 处消费** ⇒ 补了没人看、删了没人管。
  ③ 更隐蔽的一种腐化：**补了节但内容与版本对不上**。
     实测 manuscript-delivery 的 frontmatter 是 `version: 1.4.0`，
     而它「变更记录」节里最新条目仍是 `v1.3.0`——节在、版本错位，
     正是「有则加餐」式约定最典型的假绿。

本门禁把「frontmatter 完整性 + 版本演进记录」从**软约定**变成**机械判据**，
覆盖 5 条：
  F1 版本必填   —— frontmatter 必须有 version，非空，且是合法 semver
                  （^\d+\.\d+\.\d+$；无 v 前缀、无预发布后缀）
  F2 记录节存在 —— 每个 Skill 必须有版本演进记录节。节名允许的别名：
                  变更记录 / Changelog / 版本记录 / 版本演进
                  （大小写不敏感；标题可带编号前缀，如 `## 7. Changelog`）
  F3 版本对齐   —— 记录节内**必须至少有一条**条目标注了当前 frontmatter
                  version（`- v{版本} ...`）。★这是防「补了节但内容对不上」
                  的关键一条：只判节存在会把 v1.4.0/v1.3.0 错位放行。
  F4 name 对齐  —— frontmatter.name 必须等于所在目录名
                  （= 平台索引键；name 与目录名分离会让 Skill 加载不到）
  F5 边界完整   —— 文件必须以 `---` 开头且 frontmatter 闭合；
                  frontmatter 至少含 name 与 description，且 description 非空

★门禁边界（纪律）：本门禁**只判 frontmatter + 变更记录节的存在性与对齐**，
  **不检查 SKILL.md 正文内容**——正文语义归 check_doc_consistency /
  check_cross_refs / check_domain_neutral 等门禁管，越界即职责重叠。

★零依赖：本门禁在 CI 中于「安装书稿链依赖（PyYAML）」**之前**执行，
  故 frontmatter 解析**不依赖 PyYAML**（手写行解析器，覆盖本包实际形态：
  单行 `key: value`，值可带双引号）。

退出码：0 全部通过 | 1 任一判据失败 | 2 用法错误
用法：
  python3 scripts/check_skill_frontmatter.py --root .
  python3 scripts/check_skill_frontmatter.py --root . --json
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── 判据常量 ────────────────────────────────────────────────────────────

# F1：合法 semver（严格三段；不带 v 前缀、不带预发布/构建后缀）
RE_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# F2：版本演进记录节的合法节名别名（匹配时大小写不敏感）
CHANGELOG_ALIASES = ("变更记录", "changelog", "版本记录", "版本演进")

# 标题行：一/二/三级标题（`#`~`###`）
RE_HEADING = re.compile(r"^(#{1,3})[ \t]+(.*)$")

# 标题里的编号前缀：`7.` / `3.2` / `3)` / `2、` 等
RE_HEADING_NUM_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*\s*[.、)）]\s*")

# frontmatter 键值行：`name: agent-harness-protocol`
RE_FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")

# F3：变更记录条目行（项目符号 + 紧跟 v{版本}）
RE_ENTRY_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


# ── frontmatter 解析（零依赖）────────────────────────────────────────────


def split_frontmatter(lines: list[str]) -> tuple[dict | None, int, str]:
    """拆出 frontmatter 字段字典、正文起始行号、错误说明。

    返回 (fields, body_start, err)：
      · fields 为 None 时表示边界不完整（err 非空），其余判据据此跳过
      · body_start 为正文首行下标（边界完整时有效）
    """
    if not lines:
        return None, 0, "文件为空"
    if lines[0].strip() != "---":
        return None, 0, "文件未以 '---' 开头（frontmatter 边界缺失）"
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, 0, "frontmatter 未闭合（缺第二个 '---'）"

    fields: dict[str, str] = {}
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = RE_FM_KEY.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        # 去一层成对引号（本包 description 均为双引号整串）
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        fields[key] = val
    return fields, end + 1, ""


# ── 标题 / 变更记录节定位 ───────────────────────────────────────────────


def fence_flags(lines: list[str]) -> list[bool]:
    """标记每行是否位于围栏代码块（``` / ~~~）内。

    ★必须做：包内多处 SKILL.md 的示例代码块里有 `# 注释` 行
    （如 agent-harness-protocol 的 bash 片段），不排除会被误当一级标题。
    """
    inside = [False] * len(lines)
    fence: str | None = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if fence is None:
            if s.startswith("```") or s.startswith("~~~"):
                fence = s[0] * 3
                inside[i] = True
                continue
            inside[i] = False
        else:
            inside[i] = True
            if s.startswith(fence):
                fence = None
    return inside


def normalize_title(title: str) -> str:
    """标题去编号前缀：`7. Changelog` → `Changelog`。"""
    return RE_HEADING_NUM_PREFIX.sub("", title).strip()


def _alias_hit(norm: str, alias: str) -> bool:
    """归一化标题是否命中节名别名。"""
    n = norm.lower()
    a = alias.lower()
    if not a:
        return False
    if n.startswith(a):
        return True
    # 别名前紧邻数字时视为编号前缀的延续（如 `2026年度变更记录`），不算命中
    idx = n.find(a)
    while idx != -1:
        if idx == 0 or not n[idx - 1].isdigit():
            return True
        idx = n.find(a, idx + 1)
    return False


def find_changelog_section(lines: list[str], start: int) -> tuple[int, str, list[str]] | None:
    """定位版本演进记录节，返回 (标题行号, 标题文本, 节正文行)。

    判定：扫描一/二/三级标题行（排除代码块内的行），标题去编号前缀后
    命中 CHANGELOG_ALIASES 任一别名即算该 Skill 存在记录节。
    """
    inside = fence_flags(lines)
    for i in range(start, len(lines)):
        if inside[i]:
            continue
        m = RE_HEADING.match(lines[i])
        if not m:
            continue
        title = m.group(2).strip()
        norm = normalize_title(title)
        if not any(_alias_hit(norm, a) for a in CHANGELOG_ALIASES):
            continue
        level = len(m.group(1))
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            if not inside[j]:
                m2 = RE_HEADING.match(lines[j])
                if m2 and len(m2.group(1)) <= level:
                    break
            body.append(lines[j])
            j += 1
        return i, title, body
    return None


def has_version_entry(body: list[str], version: str) -> bool:
    """节内是否存在 `- v{version} ...` 形态的条目。"""
    if not version:
        return False
    # 版本号后须为行尾/空白/标点（不得再跟版本号字符），
    # 避免 `v1.8.0` 误配 `v1.8.01`；`v` 前缀须紧贴条目开头（可被 markdown 强调包裹）。
    pat = re.compile(r"^v" + re.escape(version) + r"(?![0-9A-Za-z.+-])")
    for raw in body:
        m = RE_ENTRY_BULLET.match(raw)
        if not m:
            continue
        text = m.group(1).strip()
        # 容忍 markdown 强调/代码标记包裹的版本号（`- **v1.4.0** [...]` / `- \`v1.4.0\` [...]`）
        text = text.lstrip("*_`").strip()
        if pat.match(text):
            return True
    return False


# ── 单 Skill 检查 ───────────────────────────────────────────────────────


def check_skill_dir(skill_dir: Path) -> list[dict]:
    """对单个 Skill 目录执行 F1–F5，返回失败项列表。"""
    fails: list[dict] = []
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"

    def add(cid: str, detail: str) -> None:
        fails.append({"id": cid, "skill": name, "detail": detail})

    text = _read(skill_md)
    lines = text.splitlines()

    # ── F5 frontmatter 边界完整 ──
    fields, body_start, fm_err = split_frontmatter(lines)
    if fm_err:
        add("F5", fm_err)
        # 边界坏了 → 版本位与 name 无从谈起，F1/F3/F4 跳过（避免级联噪声）
        # F2 仍独立判定：变更记录节是否存在，与 frontmatter 无关
        if find_changelog_section(lines, 0) is None:
            add("F2", "缺版本演进记录节（无别名命中："
                      + "/".join(CHANGELOG_ALIASES) + "）")
        return fails

    # F5a：frontmatter 至少含 name 与 description，且 description 非空
    if "name" not in fields or not fields["name"].strip():
        add("F5", "frontmatter 缺 name 字段（或为空）")
    if "description" not in fields or not fields["description"].strip():
        add("F5", "frontmatter 缺 description 字段（或为空）")

    version = (fields.get("version") or "").strip()

    # ── F1 版本必填 ──
    if not version:
        add("F1", "frontmatter 缺 version 字段（或为空）")
    elif not RE_SEMVER.match(version):
        add("F1", f"version '{version}' 不是合法 semver（须形如 1.8.0）")

    # ── F2 记录节存在 ──
    section = find_changelog_section(lines, body_start)
    if section is None:
        add("F2", "缺版本演进记录节（无别名命中："
                  + "/".join(CHANGELOG_ALIASES) + "）")

    # ── F3 版本与记录对齐 ──
    # version 缺失时不报 F3（已由 F1 覆盖）：否则「删 version」会同时炸 F1+F3，
    # 制造级联噪声，且掩盖 F3 真正要防的「节在、版本错位」病灶。
    if section is None:
        if version:
            add("F3", f"无版本演进记录节可对齐（frontmatter version={version}）")
    elif version and not has_version_entry(section[2], version):
        add("F3", f"变更记录节内无 v{version} 条目"
                  f"（frontmatter version={version} 与记录内容不对齐）")

    # ── F4 name 与目录名一致 ──
    fm_name = (fields.get("name") or "").strip()
    if fm_name and fm_name != name:
        add("F4", f"frontmatter.name '{fm_name}' ≠ 目录名 '{name}'"
                  f"（name 即平台索引键，不一致则 Skill 加载不到）")

    return fails


def run(root: Path) -> dict:
    """对包内全部 Skill 执行 F1–F5，返回结果字典。"""
    skills_dir = Path(root) / "skills"
    if not skills_dir.is_dir():
        return {"ok": False, "error": f"未找到 skills 目录：{skills_dir}", "fails": [],
                "checked": 0, "total_fails": 1}

    skill_dirs = sorted(d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())

    all_fails: list[dict] = []
    for sd in skill_dirs:
        all_fails.extend(check_skill_dir(sd))

    by_id: dict[str, int] = {}
    for f in all_fails:
        by_id[f["id"]] = by_id.get(f["id"], 0) + 1

    return {
        "ok": not all_fails,
        "checked": len(skill_dirs),
        "total_fails": len(all_fails),
        "by_id": by_id,
        "fails": all_fails,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="包内 Skill frontmatter 与版本演进记录门禁")
    ap.add_argument("--root", default=".", help="包根目录（默认当前目录）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    res = run(root)

    if res.get("error"):
        # 判据没跑 ≠ FAIL：退出码统一为 2，且不得虚报 total_fails
        res["total_fails"] = 0
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"✗ {res['error']}")
        return 2

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    print("=" * 62)
    print("Skill frontmatter 与版本演进记录门禁")
    print("=" * 62)
    print(f"Skill 目录数：{res['checked']}")
    if res["total_fails"] == 0:
        print("✓ F1 版本必填 / F2 记录节存在 / F3 版本对齐 / F4 name 对齐 / F5 边界完整 —— 全部通过")
    else:
        for f in res["fails"]:
            print(f"✗ [{f['id']}] {f['skill']}：{f['detail']}")
        print("-" * 62)
        print("失败判据分布：" + " | ".join(f"{k}={v}" for k, v in sorted(res["by_id"].items())))
    print("-" * 62)
    print(f"FAIL {res['total_fails']} | 检查项 5 类 × {res['checked']} 个 Skill")
    print("=" * 62)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
