#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_test_prompts.py — 包内 Skill「契约评测用例」门禁（2026-11-10 批次 S1）

==============================================================================
为什么需要：`skills/*/test-prompts.json` 是各 Skill 的**契约评测用例集**
（每条 prompt 对应一个真实使用场景，expected 描述应触发的机制/命令/门禁）。
2026-11-10 审计发现：10 个 Skill 中只有 4 个有该文件，6 个缺失，
且全仓 `scripts/` `tests/` `.github/` 对 test-prompts **零消费方**——
即「有则加餐、无则全无」，新增/删除用例都不会被任何门禁发现。
更危险的是：文件存在但内容失真（skill 名写错、id 重复、prompt 空、
expected 引用了 SKILL.md 里根本不存在的命令）同样 0 告警。

本门禁把「用例集」从**软约定**变成**机械判据**，覆盖 5 条：
  T1 存在性   —— 每个 Skill 目录必须有 test-prompts.json（缺失 = FAIL）
  T2 结构     —— 顶层必须是 {"skill": <str>, "prompts": [...]}；
                  skill 字段必须等于所在目录名（= frontmatter.name，平台索引键）
  T3 条数     —— prompts 至少 3 条（少于 3 条覆盖不了「正常/异常/边界」三型）
  T4 字段     —— 每条必须有 id / prompt / expected；
                  id 从 1 连续递增（无重复、无跳号）；prompt 与 expected 非空
  T5 引用真实性 —— expected 中出现的**命令/脚本名/门禁编号/判据码**
                  必须能在包内文本池（SKILL.md + references + scripts + agents）
                  中找到，否则判「编造引用」= FAIL

★为什么 T5 必须做：expected 是「该 prompt 应该触发什么机制」的契约说明。
若 expected 引用了不存在的命令（如 `check_foo.py`），评测时无论 Skill 表现如何
都会判 FAIL → **假门禁**：用例本身错了，却逼着 Skill 去满足一个不存在的机制。
这比缺用例更坏（缺用例是明着缺，假门禁是暗着错），故列为 FAIL 而非 WARN。

退出码：0 全部通过 | 1 任一判据失败 | 2 用法错误
用法：
  python3 scripts/check_test_prompts.py --root .
  python3 scripts/check_test_prompts.py --root . --json
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── 判据常量 ────────────────────────────────────────────────────────────

# T5：从 expected 中抽取「可核验标识」的四种形态
#   ① 文件/脚本名：xxx.py / xxx.yaml / xxx.md / xxx.json
RE_FILE = re.compile(r"[\w\-]+\.(?:py|yaml|yml|md|json)")
#   ② 门禁/判据编号：4.10 / 5.2 / 4.10e
RE_NUM = re.compile(r"\b\d+\.\d+[a-z]?\b")
#   ③ 逃逸/判据码：ESC1 / ESC4
RE_ESC = re.compile(r"\bESC\d\b")
#   ④ 大写标识符：NEED_INPUT / P0 / BOOK_DELIVER
RE_UPPER = re.compile(r"\b[A-Z][A-Z_]{2,}\b")

# 标识符「白名单」：纯计数/通用词，不要求在全包文本池中出现
#   （否则「P0」「W1」这类高频通用码会把噪声塞进报告）
IDENT_WHITELIST = {
    "P0", "P1", "P2", "P3", "W0", "W1", "W2", "W3", "W4", "W5",
    "E1", "E2", "E3", "R1", "R2", "R3", "R4",
    "OK", "FAIL", "WARN", "TODO",
}

# T5 扫描的文本池来源（相对包根）
POOL_DIRS = ["skills", "references", "scripts", "agents"]
POOL_SUFFIX = {".md", ".py", ".yaml", ".yml", ".json"}

# ★自证循环防线：test-prompts.json **本身不得进入证据池**。
#   否则被检查文件会把自己写进池里——用例里写什么，池里就有什么，
#   T5 永远命中 → 判据形同虚设（这是 T5 首版实测出的真 bug，已修）。
POOL_EXCLUDE_NAMES = {"test-prompts.json"}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def build_pool(root: Path) -> str:
    """构建 T5 的包内文本池（全包一次性读入）。

    ★排除 test-prompts.json 自身（见 POOL_EXCLUDE_NAMES）——
      否则被检文件自证，判据永远绿灯。
    """
    chunks = []
    for d in POOL_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in POOL_SUFFIX:
                continue
            if p.name in POOL_EXCLUDE_NAMES:
                continue
            chunks.append(_read(p))
    return "\n".join(chunks)


def collect_identifiers(text: str) -> set[str]:
    """抽取 expected 文本中的可核验标识符集合。"""
    ids = set()
    ids |= set(RE_FILE.findall(text))
    ids |= set(RE_NUM.findall(text))
    ids |= set(RE_ESC.findall(text))
    ids |= set(RE_UPPER.findall(text))
    return {i for i in ids if i not in IDENT_WHITELIST}


def check_skill_dir(skill_dir: Path, pool: str) -> list[dict]:
    """对单个 Skill 目录执行 T1–T5，返回失败项列表。"""
    fails: list[dict] = []
    name = skill_dir.name
    tp = skill_dir / "test-prompts.json"

    # T1 存在性
    if not tp.is_file():
        return [{"id": "T1", "skill": name, "detail": f"缺失 {name}/test-prompts.json"}]

    # T2 结构（JSON 可解析 + 顶层键）
    try:
        data = json.loads(tp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [{"id": "T2", "skill": name, "detail": f"JSON 解析失败：{e}"}]

    if not isinstance(data, dict):
        return [{"id": "T2", "skill": name, "detail": "顶层必须是对象"}]
    extra = set(data) - {"skill", "prompts"}
    if extra:
        fails.append({"id": "T2", "skill": name,
                      "detail": f"顶层出现未定义键 {sorted(extra)}（只许 skill/prompts）"})
    if "skill" not in data:
        fails.append({"id": "T2", "skill": name, "detail": "缺顶层键 skill"})
    elif not isinstance(data["skill"], str) or not data["skill"].strip():
        fails.append({"id": "T2", "skill": name, "detail": "skill 必须是非空字符串"})
    elif data["skill"] != name:
        fails.append({"id": "T2", "skill": name,
                      "detail": f"skill 字段 '{data['skill']}' ≠ 目录名 '{name}'"
                                f"（skill 字段须等于 frontmatter.name = 平台索引键）"})
    if "prompts" not in data:
        fails.append({"id": "T2", "skill": name, "detail": "缺顶层键 prompts"})
        return fails
    prompts = data["prompts"]
    if not isinstance(prompts, list):
        fails.append({"id": "T2", "skill": name, "detail": "prompts 必须是数组"})
        return fails

    # T3 条数
    if len(prompts) < 3:
        fails.append({"id": "T3", "skill": name,
                      "detail": f"仅 {len(prompts)} 条用例，至少 3 条"
                                f"（需覆盖正常/异常/边界三型）"})

    # T4 字段完整性 + id 连续
    seen_ids = []
    for idx, item in enumerate(prompts):
        loc = f"prompts[{idx}]"
        if not isinstance(item, dict):
            fails.append({"id": "T4", "skill": name, "detail": f"{loc} 不是对象"})
            continue
        for key in ("id", "prompt", "expected"):
            if key not in item:
                fails.append({"id": "T4", "skill": name, "detail": f"{loc} 缺字段 {key}"})
        if "prompt" in item and (not isinstance(item["prompt"], str) or not item["prompt"].strip()):
            fails.append({"id": "T4", "skill": name, "detail": f"{loc}.prompt 为空或非字符串"})
        if "expected" in item and (not isinstance(item["expected"], str) or not item["expected"].strip()):
            fails.append({"id": "T4", "skill": name, "detail": f"{loc}.expected 为空或非字符串"})
        if "id" in item:
            if not isinstance(item["id"], int) or isinstance(item["id"], bool):
                fails.append({"id": "T4", "skill": name, "detail": f"{loc}.id 必须是整数"})
            else:
                seen_ids.append(item["id"])
    if seen_ids:
        expect = list(range(1, len(seen_ids) + 1))
        if sorted(seen_ids) != expect:
            dup = sorted({i for i in seen_ids if seen_ids.count(i) > 1})
            detail = f"id 序列应为 {expect}，实际 {sorted(seen_ids)}"
            if dup:
                detail += f"（重复 id：{dup}）"
            fails.append({"id": "T4", "skill": name, "detail": detail})

    # T5 引用真实性
    for idx, item in enumerate(prompts):
        if not isinstance(item, dict):
            continue
        exp = item.get("expected")
        if not isinstance(exp, str) or not exp.strip():
            continue
        missing = sorted(i for i in collect_identifiers(exp) if i not in pool)
        if missing:
            fails.append({
                "id": "T5", "skill": name,
                "detail": f"prompts[{idx}].expected 引用了包内不存在的标识：{missing}",
            })

    return fails


def run(root: Path) -> dict:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return {"ok": False, "error": f"未找到 skills 目录：{skills_dir}", "fails": [],
                "checked": 0, "total_fails": 1}

    pool = build_pool(root)
    skill_dirs = sorted(d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())

    all_fails: list[dict] = []
    for sd in skill_dirs:
        all_fails.extend(check_skill_dir(sd, pool))

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
    ap = argparse.ArgumentParser(description="包内 Skill 契约评测用例（test-prompts.json）门禁")
    ap.add_argument("--root", default=".", help="包根目录（默认当前目录）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    res = run(root)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    if res.get("error"):
        print(f"✗ {res['error']}")
        return 2

    print("=" * 62)
    print("Skill 契约评测用例门禁（test-prompts.json）")
    print("=" * 62)
    print(f"Skill 目录数：{res['checked']}")
    if res["total_fails"] == 0:
        print("✓ T1 存在性 / T2 结构 / T3 条数 / T4 字段 / T5 引用真实性 —— 全部通过")
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
