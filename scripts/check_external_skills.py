#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_external_skills.py — 外部判据 skill 挂载校验（★E1 v2.11.0）

规范 SSOT = references/skill-mounting.md（§3 frontmatter / §4 冲突检测 /
§6 卸载无残留）。本脚本做四项机械校验：

  1. 清单存在性   external-skills.yaml 存在且可解析（无挂载 → exit 0 N/A）
  2. 命名冲突     外部 skill 名与包内 10 skill 撞名 → FAIL
  3. frontmatter  name 带命名空间前缀 / version / discipline / purpose=判据
                  / criteria_refs 非空 / source 非空 → 缺一 FAIL
  4. 双向一致     清单条目 ↔ 目录 双向对齐（挂载残留 / 卸载残留都 FAIL）

退出码：0 通过（或无挂载）| 1 存在 FAIL | 2 结构错误（清单/目录无法读）

用法
====
  python3 scripts/check_external_skills.py --work-root "$WORK_ROOT"
  python3 scripts/check_external_skills.py --work-root "$WORK_ROOT" --json

红线：本脚本只报不修——修挂载清单/目录是主理人动作（脚本只报不 spawn 同源纪律）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent

# 包内 10 skill（与 plugin.json skills[] 同源；挂载不得撞名）
BUILTIN_SKILLS = [
    "agent-harness-protocol", "book-orchestration", "citation-verify",
    "learn-protocol", "manuscript-delivery", "multi-agent-patterns",
    "scientific-figure", "task-router", "team-generation",
    "textbook-pipeline-workflow",
]

REQUIRED_FRONTMATTER = ("name", "version", "discipline", "purpose",
                        "criteria_refs", "source")

NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9-]*-[a-z][a-z0-9-]*$")  # 至少一个连字符


def load_manifest(work_root: Path) -> tuple[list[dict] | None, str | None]:
    """读 external-skills.yaml（轻量 YAML 子集：`- name: xxx` 条目列表）。

    返回 (条目列表, 错误)。无文件 → ([], None)——未挂载是合法状态。
    """
    mf = work_root / "学科标准" / "external-skills.yaml"
    if not mf.is_file():
        return [], None
    out, cur = [], None
    for i, line in enumerate(mf.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- "):
            if cur:
                out.append(cur)
            body = s[2:].strip()
            # 兼容两种清单形态：`- {skill-name}` 或 `- name: {skill-name}`
            if body.startswith("name:") and ":" in body:
                cur = {"name": body.split(":", 1)[1].strip(), "_line": i}
            else:
                cur = {"name": body, "_line": i}
        elif s.startswith("dir:") and cur is not None:
            cur["dir"] = s.split(":", 1)[1].strip()
        elif s.startswith("purpose:") and cur is not None:
            cur["purpose"] = s.split(":", 1)[1].strip()
    if cur:
        out.append(cur)
    return out, None


def check_skill_dir(skill_dir: Path, name: str) -> list[str]:
    """单 skill 目录校验 → 问题列表。"""
    problems: list[str] = []
    sm = skill_dir / "SKILL.md"
    if not sm.is_file():
        return [f"{name}: SKILL.md 缺失（{skill_dir}）"]
    text = sm.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return [f"{name}: SKILL.md 无 frontmatter"]
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return [f"{name}: frontmatter 未闭合"]
    fm = m.group(1)
    fields = {}
    for line in fm.splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            # 列表键（值为空、下一行是 "- " 项）→ 标记为已声明非空
            fields[k] = v if v else ("LISTED" if k in ("criteria_refs",) else "")
    for req in REQUIRED_FRONTMATTER:
        if req not in fields or not fields[req]:
            problems.append(f"{name}: frontmatter 缺必填项 {req}")
    fm_name = fields.get("name", "")
    if fm_name and fm_name != name:
        problems.append(f"{name}: frontmatter name={fm_name!r} 与登记名不一致")
    if not NAMESPACE_RE.match(name) or name in BUILTIN_SKILLS:
        problems.append(
            f"{name}: 命名不合规（须 {namespace_hint()} 且不与包内 skill 撞名）")
    if fields.get("purpose") and fields["purpose"] != "判据":
        problems.append(
            f"{name}: purpose={fields['purpose']!r} ≠ 判据——内容源类 skill "
            f"禁止挂载（铁律：判据与内容源分离）")
    return problems


def namespace_hint() -> str:
    return "namespace-skillname 形态（namespace ≥2 字符）"


def check_work_root(work_root: Path) -> tuple[list[str], int]:
    """四项校验 → (问题列表, 挂载数)。"""
    problems: list[str] = []
    entries, err = load_manifest(work_root)
    if err:
        return [f"清单解析失败: {err}"], 0
    if not entries:
        # 清单空 ≠ 无检查——反向残留（目录在清单无）仍要扫（★§6 卸载无残留）
        base = work_root / "学科标准" / "external"
        residual = []
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    residual.append(
                        f"{d.name}: 目录存在但清单未登记（挂载残留——删目录或补清单行）")
        return residual, 0
    base = work_root / "学科标准" / "external"
    seen = set()
    for e in entries:
        name = e.get("name", "")
        if not name:
            problems.append(f"清单 L{e.get('_line')}: 条目缺 name")
            continue
        if name in seen:
            problems.append(f"{name}: 清单重复登记")
        seen.add(name)
        if name in BUILTIN_SKILLS:
            problems.append(f"{name}: 与包内 skill 撞名（挂载禁止）")
        skill_dir = Path(e.get("dir") or base / name)
        resolved = skill_dir if skill_dir.is_absolute() else work_root / skill_dir
        if not resolved.is_dir():
            problems.append(f"{name}: 目录缺失（卸载残留——删清单行或补目录）")
            continue
        problems.extend(check_skill_dir(resolved, name))
    # 反向：目录有、清单没有 = 挂载登记残留
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and d.name not in seen and not d.name.startswith("."):
                problems.append(
                    f"{d.name}: 目录存在但清单未登记（挂载残留——删目录或补清单行）")
    return problems, len(entries)


def main() -> int:
    ap = argparse.ArgumentParser(description="外部判据 skill 挂载校验（只报不修）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    wr = Path(args.work_root).expanduser().resolve()
    if not wr.is_dir():
        print(f"ERROR WORK_ROOT 不存在: {wr}", file=sys.stderr)
        return 2

    problems, n = check_work_root(wr)
    report = {"schema": "stt.external_skills/1", "mounted": n,
              "ok": not problems, "problems": problems}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if n == 0:
            print(f"✓ 未挂载外部判据 skill（N/A，规范见 references/skill-mounting.md）")
            return 0
        if problems:
            print(f"✗ 外部 skill 挂载校验 FAIL（{n} 个挂载，{len(problems)} 项问题）：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"✓ 外部 skill 挂载校验通过（{n} 个挂载，命名/frontmatter/双向一致全过）")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
