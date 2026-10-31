#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_team.py — 动态专家团队构成提案生成器（只出提案，不落盘生效）

==============================================================================
设计要点
------------------------------------------------------------------------------
1. **只产出提案**：写 `--out` 文件供用户对齐；**绝不写** 运行态/dynamic-members.yaml
   （注册生效是主理人在用户确认后的动作，见 skills/team-generation §1 闸门）
2. 输入：chapter_design.md 的 knowledge_scope + 学科 profile 的映射表
3. 输出构成表自带三维评估（覆盖深度/领域匹配度/准确性保障），供用户裁决参考

用法
------------------------------------------------------------------------------
  python3 scripts/generate_team.py \
      --design  "$WORK_ROOT/章节/ch01/chapter_design.md" \
      --profile veterinary \
      --out     "$WORK_ROOT/运行态/team-proposal-ch01.yaml"

退出码：0 提案已生成 | 2 输入缺失 | 3 profile 无映射表
==============================================================================
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 固定视角（每章必有，不参与动态生成）
FIXED = [
    ("textbook-senior-editor", "教材资深编辑",
     ["术语一致性", "引用格式", "段落节奏"]),
    ("vocational-edu-adapter", "高职学段适配",
     ["学段可消化性", "公式最小化", "案例密度"]),
]

# 默认 examines 模板（领域视角；profile 未给 examines 时用）
DEFAULT_EXAMINES = ["术语精确性", "因果链完整性", "鉴别点充分性"]


def parse_profile_mappings(profile_path: Path) -> dict[str, tuple[str, str]]:
    """解析 profile §1 映射表 → {知识域: (role_id, role_name)}。

    表格式：| 知识域 | role_id | role_name |（兼容首尾空格与全角空格）。
    """
    text = profile_path.read_text(encoding="utf-8")
    # 截取 §1 到 §2 之间
    m = re.search(r"##\s*1\..*?(?=##\s*2\.)", text, re.S)
    seg = m.group(0) if m else text
    out: dict[str, tuple[str, str]] = {}
    for line in seg.splitlines():
        line = line.strip().replace("　", " ")
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= {"-", ":", " "}:
            continue
        domain, rid, rname = cells[0], cells[1], cells[2]
        if not re.fullmatch(r"[a-z0-9\-]+", rid):
            continue  # 跳过表头行
        out[domain] = (rid, rname)
    return out


def extract_knowledge_scope(design_path: Path) -> list[str]:
    """从 chapter_design.md 提取知识域清单。

    兼容格式：`knowledge_scope:` 行（逗号/顿号分隔）或 §A 中「知识域」表格行。
    """
    text = design_path.read_text(encoding="utf-8")
    domains: list[str] = []
    m = re.search(r"knowledge_scope\s*[:：]\s*(.+)", text)
    if m:
        raw = m.group(1).strip()
        # 剥离 YAML 列表括号（[a, b] → a, b）——此前 [] 被并入域名致映射必不命中
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        domains = [d.strip() for d in re.split(r"[,，、;；/]", raw) if d.strip()]
    if not domains:
        # 退化：抓「知识域」列
        for line in text.splitlines():
            if "知识域" in line and "|" in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if cells and cells[0] not in ("知识域", "") \
                        and not set(cells[0]) <= {"-", ":", " "}:
                    domains.append(cells[0])
    # 去重保序
    seen, out = set(), []
    for d in domains:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="动态专家团队构成提案生成器（只出提案）")
    ap.add_argument("--design", required=True, help="chapter_design.md 路径")
    ap.add_argument("--profile", default="veterinary",
                    help="学科 profile 名（默认 veterinary）")
    ap.add_argument("--expert-dir", default=None,
                    help="专家包根（默认按本脚本位置反推）")
    ap.add_argument("--out", required=True, help="提案 yaml 输出路径")
    args = ap.parse_args()

    design = Path(args.design).expanduser()
    if not design.is_file():
        print(f"[ERROR] chapter_design 不存在：{design}", file=sys.stderr)
        return 2

    pkg_root = (Path(args.expert_dir).expanduser() if args.expert_dir
                else Path(__file__).resolve().parent.parent)
    profile_path = pkg_root / "references" / "profiles" / f"{args.profile}.md"
    if not profile_path.is_file():
        print(f"[ERROR] profile 不存在：{profile_path}", file=sys.stderr)
        return 2

    mappings = parse_profile_mappings(profile_path)
    if not mappings:
        print(f"[ERROR] profile 映射表为空：{profile_path}", file=sys.stderr)
        return 3

    domains = extract_knowledge_scope(design)
    if not domains:
        print("[ERROR] chapter_design 中未找到 knowledge_scope / 知识域清单", file=sys.stderr)
        return 2

    # 领域成员：知识域 → 映射表命中；未命中 → 构造 {domain}-specialist
    # **member_id 全局去重**（2026-10-30 实测：不同域可能构造出同名 ID，
    # 如「病毒学/病毒」「病毒」都落 domain-specialist → 注册表键冲突）。
    domain_members = []
    seen_ids: dict[str, int] = {}
    # E2 修复（2026-10-31）：三维评估此前两维恒真——covered 与 domains 同源构造、
    # examines 恒为 DEFAULT_EXAMINES。现在：
    # ① examines 按 profile 差异化：映射表命中域用「领域默认 3 维」，
    #   构造域追加「领域知识域特异性」维（[待定·按 {domain} 校准]），使 accuracy 维有信息量；
    # ② covered/unmatched 按 **映射表命中** 独立统计（不与成员集合同源），恒真不可能。
    hit_domains: list[str] = []      # 命中 profile 映射表的域
    constructed_domains: list[str] = []  # 未命中、由命名约定构造的域
    for d in domains:
        hit = mappings.get(d)
        if hit:
            rid, rname = hit
            src = f"profile:{args.profile}"
            examines = list(DEFAULT_EXAMINES)
            hit_domains.append(d)
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", d.lower()).strip("-") or "domain"
            rid, rname = f"{slug}-specialist", f"{d}领域专家"
            src = "constructed"
            # 构造域的 examines 显式标注「待校准」——用户对齐三问第 2 问的实质输入
            examines = list(DEFAULT_EXAMINES) + [f"[待校准·{d}特异性维度]"]
            constructed_domains.append(d)
        if rid in seen_ids:
            seen_ids[rid] += 1
            rid = f"{rid}-{seen_ids[rid]}"   # domain-specialist-2
            src += "+dedup"
        else:
            seen_ids[rid] = 1
        domain_members.append({
            "member_id": rid, "role_name": rname, "domain": d,
            "examines": examines, "source": src,
        })

    # 三维评估（E2：按映射命中独立计算，杜绝同源恒真）
    n_hit = len(hit_domains)
    n_total = len(domains)
    hit_ratio = n_hit / n_total if n_total else 0.0
    all_exam = set()
    for m in domain_members:
        all_exam.update(m["examines"])
    has_term = "术语精确性" in all_exam
    n_tbd = sum(1 for m in domain_members if any("[待校准" in e for e in m["examines"]))

    # 提案 yaml（confirmed_by_user 必须为 false —— 生效由主理人在用户确认后另写）
    lines = [
        f"# 团队构成提案（仅提案，未生效）— {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"chapter_design: {design}",
        f"discipline: {args.profile}",
        "confirmed_by_user: false   # 闸门：用户明确确认后，主理人才可把它转写为注册表并置 true",
        "members:",
    ]
    for m in domain_members:
        lines.append(f"  - member_id: {m['member_id']}")
        lines.append(f"    role_name: {m['role_name']}")
        lines.append(f"    domain: {m['domain']}")
        lines.append(f"    examines: [{', '.join(m['examines'])}]")
        lines.append(f"    source: {m['source']}")
    for rid, rname, ex in FIXED:
        lines.append(f"  - member_id: {rid}")
        lines.append(f"    role_name: {rname}")
        lines.append("    domain: (固定视角)")
        lines.append(f"    examines: [{', '.join(ex)}]")
        lines.append("    source: fixed")

    lines += [
        "",
        "# ── 三维评估（供用户对齐参考；E2 起按映射命中独立计算，杜绝恒真）──",
        f"coverage: 知识域 {n_total} 个；映射表命中 {n_hit} 个（{hit_ratio:.0%}）；"
        + (f"构造域（未命中）: {constructed_domains}" if constructed_domains else "全部命中映射表"),
        f"domain_match: 命中 {n_hit} 来自 profile:{args.profile} 映射"
        + (f"；{len(constructed_domains)} 个为构造 role_id——**对齐三问第 1 问重点审查对象**" if constructed_domains else ""),
        f"accuracy: 术语精确性视角{'已含' if has_term else '缺失！需补领域术语成员'}；"
        + (f"{n_tbd} 个构造成员 examines 含 [待校准] 维——对齐三问第 2 问须逐个确认" if n_tbd else "examines 全部来自 profile 映射，无需校准"),
        "",
        "# 对齐三问（主理人呈现给用户）：",
        "#   1. 这 N 个视角覆盖是否合适？（多/少/错）——命中比 <100% 时先审 constructed 域",
        "#   2. examines 分工是否符合预期？——含 [待校准] 维的成员须逐个确认",
        "#   3. 确认生效 or 修改 or 放弃？",
    ]
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[OK] 提案已写入：{out}", file=sys.stderr)
    print(f"[OK] 领域成员 {len(domain_members)} + 固定 {len(FIXED)} = "
          f"{len(domain_members) + len(FIXED)} 个；知识域命中 "
          f"{n_hit}/{n_total}", file=sys.stderr)
    if constructed_domains:
        print(f"[WARN] 未命中 profile 映射、由命名约定构造的域: {constructed_domains}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
