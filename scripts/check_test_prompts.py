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

本门禁把「用例集」从**软约定**变成**机械判据**，覆盖 7 条：
  T1 存在性   —— 每个 Skill 目录必须有 test-prompts.json（缺失 = FAIL）
  T2 结构     —— 顶层必须是 {"skill": <str>, "prompts": [...]}；
                  skill 字段必须等于所在目录名（= frontmatter.name，平台索引键）
  T3 条数     —— prompts 至少 3 条（少于 3 条覆盖不了「正常/异常/边界」三型）
  T4 字段     —— 每条必须有 id / prompt / expected；
                  id 从 1 连续递增（无重复、无跳号）；prompt 与 expected 非空
  T5 引用真实性 —— expected 中出现的**命令/脚本名/门禁编号/判据码**
                  必须能在包内文本池（SKILL.md + references + scripts + agents）
                  中找到，否则判「编造引用」= FAIL
  T6 证据域定位 + 版本对齐（2026-11-10 批次 U-2，第三层一致性）
    T6a 域内定位 —— 编号类标识（4.13 / 4.10e / 5.5 等）必须能在**该 Skill 自身
                  证据域**（SKILL.md + 该 Skill 自己的 references/*.md）中
                  以**精确 token** 形式定位到；只在别处残留不算数
    T6b 版本对齐 —— 用例集顶层须声明 skill_version，且等于该 Skill
                  frontmatter 的 version；Skill 升版后用例集未同步 = FAIL

★为什么 T5 必须做：expected 是「该 prompt 应该触发什么机制」的契约说明。
若 expected 引用了不存在的命令（如 `check_foo.py`），评测时无论 Skill 表现如何
都会判 FAIL → **假门禁**：用例本身错了，却逼着 Skill 去满足一个不存在的机制。
这比缺用例更坏（缺用例是明着缺，假门禁是暗着错），故列为 FAIL 而非 WARN。

★为什么 T6 必须做（U-2，2026-11-10 批次）：
  T5 的证据池是**全包**——编号只要在包内任意角落出现就算「有实据」。
  于是出现两个静默漏洞：
    ① 域外残留：某 Skill 正文删掉了 4.13，但 4.13 还在别的 skill 正文里
       残留 → 用例集照样判「引用真实」→ 实际该 Skill 已无此机制，用例失效。
    ② 版本漂移：Skill 从 1.4.0 升到 1.5.0，机制语义变了，但用例集**从不
       声明**自己对应哪个版本 → 升版后 expected 静默过期，零机制提示。
  T6 把「用例集 ↔ Skill 当前版本」这条链补上：域内定位（T6a）+ 版本绑定（T6b）。
  缺了第三层，用例集就会在 Skill 演进中**逐版腐坏而不报任何警**。

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

# ★自证防线二（2026-11-10 实测的第二处逃逸）：**门禁脚本自身**的文本也不得进入
#   证据池。本脚本 docstring 里写着「如 `check_foo.py`」这类**反例示例名**，
#   它会被 RE_FILE 抽成 token 放进池里 → 用例里写 `check_foo.py` 反而「查得到」
#   → 假阴性逃逸。门禁自己的反例名绝不能成为门禁的证据。
GATE_SELF_NAME = "check_test_prompts.py"

# ── 豁免机制（2026-11-10 批次：架构师审计 D-2，§9.3 方案 2）──────────────
# 病灶：T1「每个 Skill 必须有 test-prompts.json」无逃生阀——未来新增**纯参考型
#   Skill**（只提供术语表/规范查询，无行为契约）时会被逼着写 3 条无意义 prompt，
#   反而稀释用例集质量。包内其他门禁都有同类豁免（check_domain_neutral 的
#   SKIP_DIRS / AUDIENCE_SKIP_FILES 同构）。
# 三护栏（缺一即 FAIL，防止豁免机制本身被滥用成「永久免检」后门）：
#   ① 键必须在包内真实存在（防「为不存在的 skill 预留豁免」占位不放水）
#   ② 理由必填非空（豁免必须可审计）
#   ③ 豁免数 > 0 时输出提醒（防长期遗忘）
# 当前表为空 = 机制就位、不放水。新增豁免属**判据改动**，须经管家节点确认。
EXEMPT_SKILLS: dict[str, str] = {
    # "skill-name": "豁免理由（必填非空，说明为何无可评测的 prompt 契约）",
}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def collect_identifiers(text: str) -> set[str]:
    """抽取文本中的可核验标识符集合。"""
    ids = set()
    ids |= set(RE_FILE.findall(text))
    ids |= set(RE_NUM.findall(text))
    ids |= set(RE_ESC.findall(text))
    ids |= set(RE_UPPER.findall(text))
    return {i for i in ids if i not in IDENT_WHITELIST}


def build_pool(root: Path) -> tuple[set[str], set[str]]:
    """构建 T5 的证据池，返回 (真实文件名集合, 包内标识符 token 集合)。

    ★为什么不用「整池字符串 + 子串匹配」（2026-11-10 实测的两个逃逸）：
      ① 子串逃逸：`check_foo.py` 是 `check_doc_consistency.py` 的**子串**，
         子串匹配会判「存在」→ 假阴性。token 集合是**精确相等**判定，天然免疫。
      ② 自证逃逸：门禁自身 docstring 里的反例名会被抽成 token 放进池里
         → 写假名反而「查得到」。故门禁自身文件不参与 token 抽取。

    文件名类标识符查**真实文件系统**（file_names），其余标识符查 token 集合
    （tokens）——两者取并集即为「该标识符在包内确有实据」。
    """
    file_names: set[str] = set()
    tokens: set[str] = set()
    for d in POOL_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        # ★确定性遍历（2026-11-10 批次 D-3）：rglob 结果必须 sorted——
        #   文件系统返回序不保证稳定，set 判定虽不受顺序影响，但同构门禁
        #   （check_doc_consistency / check_cross_refs 均已 sorted）与未来可能的
        #   顺序敏感逻辑都要求「同输入 → 同遍历序」的可复现性。
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix in POOL_SUFFIX:
                file_names.add(p.name)
                # ★门禁自身与被检文件都不进 token 池（见 POOL_EXCLUDE_NAMES / GATE_SELF_NAME）
                if p.name in POOL_EXCLUDE_NAMES or p.name == GATE_SELF_NAME:
                    continue
                tokens |= collect_identifiers(_read(p))
    return file_names, tokens


def identifier_exists(ident: str, file_names: set[str], tokens: set[str]) -> bool:
    """判断标识符在包内是否有实据（文件名查文件系统，其余查 token 集合）。

    ★精确匹配，绝不用子串包含——子串匹配会让「取真实文件名的片段当假名」
      逃逸（实测 `check_foo.py` ⊂ `check_doc_consistency.py`）。
    """
    return ident in file_names or ident in tokens


# ── T6：证据域 + 版本对齐（U-2 第三层一致性）──────────────────────────

# T6a 域内定位只对**编号类**标识生效（RE_NUM）。
#   文件名类（xxx.py）已在 T5 按真实文件系统判定（T6 若再判域内定位，
#   会与 T5 语义重叠且产生假阴性——脚本常在包级 scripts/ 而不在 skill 域内）；
#   大写码（ESC1 / P0）同理有跨 skill 通用语义。
#   实测：10 个 Skill 的用例集共引用 10 个编号，全部能在各自域内精确定位。

def build_own_domain(skill_dir: Path) -> str:
    """构建单个 Skill 的**自身证据域**文本。

    域 = 该 Skill 的 SKILL.md + 该 Skill 自己的 references/*.md。
    ★刻意**不含**：
      - 其他 Skill 的正文（否则域外残留会互相串味，T6a 退化成 T5）
      - 包级 scripts/（门禁脚本是包级基础设施，不是某个 Skill 的私有契约；
        用例集引用 check_manuscript.py 是合法的跨层引用，不该判 FAIL）
    """
    chunks: list[str] = []
    files = [skill_dir / "SKILL.md"] + sorted(skill_dir.glob("references/*.md"))
    for f in files:
        if f.is_file():
            chunks.append(_read(f))
    return "\n".join(chunks)


def locate_in_domain(ident: str, domain: str) -> bool:
    """在证据域中以**精确 token** 方式定位标识符。

    ★为什么不能用子串包含（第三次实测陷阱）：
      `4.10` 是 `4.10e` 的前缀，`4.1` 是 `4.13` 的前缀——子串匹配会让
      「编号已被删除、只剩更长的相似编号」的情形误判为「仍在」。
      精确 token 判据：编号前后不得是 word char 或 `.`。
    """
    pat = re.compile(r"(?<![\w.])" + re.escape(ident) + r"(?![\w.])")
    return pat.search(domain) is not None


def read_skill_version(skill_dir: Path) -> str:
    """读取 Skill frontmatter 的 version（零依赖行解析，不用 PyYAML）。"""
    text = _read(skill_dir / "SKILL.md")
    m = re.search(r"^version:\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else ""


def check_skill_dir(skill_dir: Path, file_names: set[str], tokens: set[str]) -> list[dict]:
    """对单个 Skill 目录执行 T1–T5，返回失败项列表。"""
    fails: list[dict] = []
    name = skill_dir.name
    tp = skill_dir / "test-prompts.json"

    # 豁免检查（先于 T1）：豁免的 skill 跳过全部判据，但豁免声明本身受三护栏校验
    if name in EXEMPT_SKILLS:
        reason = EXEMPT_SKILLS[name]
        if not isinstance(reason, str) or not reason.strip():
            # 护栏②：理由必填非空
            return [{"id": "T1", "skill": name,
                     "detail": "EXEMPT_SKILLS 中该 skill 的豁免理由为空（豁免必须可审计）"}]
        # 豁免生效：跳过 T1–T5（豁免条目仍需通过 run() 的护栏①校验）
        return []

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
    extra = set(data) - {"skill", "prompts", "skill_version"}
    if extra:
        fails.append({"id": "T2", "skill": name,
                      "detail": f"顶层出现未定义键 {sorted(extra)}（只许 skill/prompts/skill_version）"})
    if "skill" not in data:
        fails.append({"id": "T2", "skill": name, "detail": "缺顶层键 skill"})
    elif not isinstance(data["skill"], str) or not data["skill"].strip():
        fails.append({"id": "T2", "skill": name, "detail": "skill 必须是非空字符串"})
    elif data["skill"] != name:
        fails.append({"id": "T2", "skill": name,
                      "detail": f"skill 字段 '{data['skill']}' ≠ 目录名 '{name}'"
                                f"（skill 字段须等于 frontmatter.name = 平台索引键）"})

    # T6b 版本对齐：用例集必须声明自己对应哪个 Skill 版本
    #   病灶（U-2）：用例集不声明版本 → Skill 升版后 expected 语义静默漂移，
    #   零机制提示。声明后，Skill 一升版就必须同步复检用例集，否则 T6b FAIL。
    skill_version = read_skill_version(skill_dir)
    declared = data.get("skill_version")
    if "skill_version" not in data:
        fails.append({"id": "T6", "skill": name,
                      "detail": "缺顶层键 skill_version（用例集未声明对应 Skill 版本，"
                                f"Skill 升版后 expected 将静默漂移；当前 Skill version={skill_version or '未知'}）"})
    elif not isinstance(declared, str) or not declared.strip():
        fails.append({"id": "T6", "skill": name, "detail": "skill_version 必须是非空字符串"})
    elif skill_version and declared.strip() != skill_version:
        fails.append({"id": "T6", "skill": name,
                      "detail": f"skill_version '{declared}' ≠ Skill frontmatter version '{skill_version}'"
                                "（Skill 已升版：用例集须复检并同步 skill_version）"})

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
        missing = sorted(i for i in collect_identifiers(exp)
                         if not identifier_exists(i, file_names, tokens))
        if missing:
            fails.append({
                "id": "T5", "skill": name,
                "detail": f"prompts[{idx}].expected 引用了包内不存在的标识：{missing}",
            })

    # T6a 域内定位：编号类标识必须能在**本 Skill 自身证据域**中精确定位
    #   病灶（U-2）：T5 的证据池是全包，编号在别处残留即可蒙混过关 →
    #   本 Skill 已删除该机制、别处仍有残留时，用例集会静默失效。
    domain = build_own_domain(skill_dir)
    if domain.strip():
        for idx, item in enumerate(prompts):
            if not isinstance(item, dict):
                continue
            exp = item.get("expected")
            if not isinstance(exp, str) or not exp.strip():
                continue
            nums = sorted(i for i in RE_NUM.findall(exp)
                          if not locate_in_domain(i, domain))
            if nums:
                fails.append({
                    "id": "T6", "skill": name,
                    "detail": f"prompts[{idx}].expected 引用的编号 {nums} 无法在本 Skill "
                              f"证据域（SKILL.md + 自身 references/）中定位"
                              "（编号可能只在别处残留，或已随版本删除 → 用例集随版本漂移）",
                })

    return fails


def run(root: Path) -> dict:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return {"ok": False, "error": f"未找到 skills 目录：{skills_dir}", "fails": [],
                "checked": 0, "total_fails": 1}

    file_names, tokens = build_pool(root)
    skill_dirs = sorted(d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())
    skill_names = {d.name for d in skill_dirs}

    all_fails: list[dict] = []

    # 豁免护栏①：豁免键必须在包内真实存在（防「为不存在的 skill 预留豁免」占位不放水）
    for exempt_name in sorted(EXEMPT_SKILLS):
        if exempt_name not in skill_names:
            all_fails.append({
                "id": "T1", "skill": exempt_name,
                "detail": f"EXEMPT_SKILLS 声明的豁免键 '{exempt_name}' 在包内不存在"
                          "（禁止为不存在的 skill 预留豁免；若 skill 已删除，豁免应同步删除）",
            })

    for sd in skill_dirs:
        all_fails.extend(check_skill_dir(sd, file_names, tokens))

    by_id: dict[str, int] = {}
    for f in all_fails:
        by_id[f["id"]] = by_id.get(f["id"], 0) + 1

    return {
        "ok": not all_fails,
        "checked": len(skill_dirs),
        "total_fails": len(all_fails),
        "by_id": by_id,
        "fails": all_fails,
        # 豁免护栏③的载体：豁免数 > 0 时由输出层提醒（防长期遗忘）
        "exemptions": sorted(EXEMPT_SKILLS),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="包内 Skill 契约评测用例（test-prompts.json）门禁")
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
    print("Skill 契约评测用例门禁（test-prompts.json）")
    print("=" * 62)
    print(f"Skill 目录数：{res['checked']}")
    # 豁免护栏③：豁免数 > 0 时提醒（防长期遗忘成「永久免检」后门）
    if res.get("exemptions"):
        print(f"⚠ 豁免生效 {len(res['exemptions'])} 个 skill（须有理由且经管家节点确认）："
              f"{', '.join(res['exemptions'])}")
    if res["total_fails"] == 0:
        print("✓ T1 存在性 / T2 结构 / T3 条数 / T4 字段 / T5 引用真实性 / "
              "T6 域内定位+版本对齐 —— 全部通过")
    else:
        for f in res["fails"]:
            print(f"✗ [{f['id']}] {f['skill']}：{f['detail']}")
        print("-" * 62)
        print("失败判据分布：" + " | ".join(f"{k}={v}" for k, v in sorted(res["by_id"].items())))
    print("-" * 62)
    print(f"FAIL {res['total_fails']} | 检查项 7 类 × {res['checked']} 个 Skill")
    print("=" * 62)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
