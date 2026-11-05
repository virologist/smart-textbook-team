#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_quality.py — R5 质量评分机械化（ADR-05 硬门槛落盘）

==============================================================================
把 R5 五维评分从「LLM 自评散文」落成**结构化文件 + 门禁读取**：
加权总分、80 分红线、权重和校验全部由本脚本机械判定（脚本为 SSOT 权威），
LLM 只负责逐维给分与证据位置（脚本为主、LLM 为辅）。

用法
------------------------------------------------------------------------------
  python3 scripts/score_quality.py --work-root "$WORK_ROOT" --chapter ch01 \\
      --dim 知识严谨性=85 --dim 前沿性=80 --dim 易懂易学=85 \\
      --dim 职业教育适配=80 --dim 规范性=80 \\
      --evidence 运行态/r5-evidence.json

  # 六维/自定义 rubric（profile 配置）：--rubric 传权重 JSON
  python3 scripts/score_quality.py --work-root "$WR" --chapter ch01 \\
      --rubric references/profiles/custom-rubric.json --dim ... --evidence ...

输入
------------------------------------------------------------------------------
  --dim 名称=得分   得分 0–100；名称必须与 rubric 维度名完全一致，且一个不缺
  --evidence JSON   {"维度名": ["证据位置", ...]}；每维 ≥1 条证据位置
  --rubric JSON     可选，{"维度名": 权重(0-100)}，权重和必须 = 100；
                    缺省读 references/chapter-structure.md §2 五维表（SSOT）

输出
------------------------------------------------------------------------------
  {WORK_ROOT}/运行态/r5-score.json:
  {
    "chapter": "ch01",
    "dims": {"知识严谨性": {"score": 85.0, "weight": 30, "points": 25.5,
                             "evidence": ["§1.2 [实]（PMID:38960123）"]}, ...},
    "total": 82.75,          # Σ(score×weight)/100
    "weight_sum": 100,
    "verdict": "pass|fail"   # pass ⇔ total≥80 ∧ weight_sum==100 ∧ 每维证据≥1
  }

退出码
------------------------------------------------------------------------------
  0 verdict=pass   1 verdict=fail   2 输入错误（缺维度/未知维度/证据空/rubric 非法）

反伪造
------------------------------------------------------------------------------
  check_manuscript 4.14 独立重算 Σ(维度×权重)/100 与 weight_sum——
  手改 total 或权重和 ≠100 必被拦截；本脚本拒绝产出不自洽文件。
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 缺省 rubric（SSOT：references/chapter-structure.md §2 五维质量评分表）
DEFAULT_RUBRIC_PATH = Path(__file__).resolve().parent.parent / "references" / "chapter-structure.md"

# §2 表行：| 知识严谨性 | 30% | ... |
RE_RUBRIC_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*%\s*\|", re.M)


def load_default_rubric(path: Path = DEFAULT_RUBRIC_PATH) -> dict[str, int]:
    """解析 chapter-structure.md §2 五维表 → {维度名: 权重}（权重为整数百分点）。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^##\s*2\..*?$([\s\S]*?)^##\s", text + "\n## ", re.M)
    section = m.group(1) if m else text
    rubric: dict[str, int] = {}
    for name, weight in RE_RUBRIC_ROW.findall(section):
        name = name.strip()
        if name in ("维度", "---") or set(name) <= {"-", " "}:
            continue
        rubric[name] = int(weight)
    return rubric


def load_rubric_file(path: Path) -> dict[str, int]:
    """--rubric JSON：{"维度名": 权重}。值须为 int/float 百分点。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("--rubric 须为非空 JSON 对象 {维度名: 权重}")
    out: dict[str, int] = {}
    for k, v in data.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"--rubric 权重非数值: {k}={v!r}")
        out[str(k)] = int(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="R5 五维质量评分机械化（ADR-05）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--dim", action="append", required=True, default=[],
                    metavar="名称=得分",
                    help="逐维得分（0–100），可重复传；须覆盖 rubric 全部维度")
    ap.add_argument("--evidence", required=True,
                    help="证据 JSON 路径：{\"维度名\": [\"位置\", ...]}，每维 ≥1 条")
    ap.add_argument("--rubric", default=None,
                    help="自定义权重 JSON（缺省读 chapter-structure.md §2 五维表）")
    args = ap.parse_args()

    # ── rubric（维度列表 + 权重，SSOT）──
    if args.rubric:
        try:
            rubric = load_rubric_file(Path(args.rubric).expanduser())
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"[ERROR] --rubric 不可用: {e}", file=sys.stderr)
            return 2
    else:
        rubric = load_default_rubric()
        if not rubric:
            print("[ERROR] chapter-structure.md §2 五维表解析为空（rubric SSOT 失效）",
                  file=sys.stderr)
            return 2

    # ── --dim 解析：名称=得分 ──
    scores: dict[str, float] = {}
    for spec in args.dim:
        if "=" not in spec:
            print(f"[ERROR] --dim 格式应为 名称=得分: {spec!r}", file=sys.stderr)
            return 2
        name, _, raw = spec.partition("=")
        name = name.strip()
        try:
            score = float(raw.strip())
        except ValueError:
            print(f"[ERROR] --dim 得分非数值: {spec!r}", file=sys.stderr)
            return 2
        if not (0 <= score <= 100):
            print(f"[ERROR] --dim 得分超出 0–100: {spec!r}", file=sys.stderr)
            return 2
        if name in scores:
            print(f"[ERROR] --dim 维度重复: {name}", file=sys.stderr)
            return 2
        scores[name] = score

    missing = sorted(set(rubric) - set(scores))
    extra = sorted(set(scores) - set(rubric))
    if missing or extra:
        print(f"[ERROR] 维度集合不匹配 rubric（缺 {missing} / 多 {extra}）",
              file=sys.stderr)
        return 2

    # ── 证据：每维 ≥1 条位置 ──
    ev_path = Path(args.evidence).expanduser()
    if not ev_path.is_file():
        print(f"[ERROR] 证据文件不存在: {ev_path}", file=sys.stderr)
        return 2
    try:
        evidence = json.loads(ev_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[ERROR] 证据文件不是合法 JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(evidence, dict):
        print("[ERROR] 证据文件须为 {维度名: [位置, ...]}", file=sys.stderr)
        return 2
    ev_missing = [d for d in rubric
                  if not evidence.get(d) or
                  (isinstance(evidence[d], list) and not any(str(x).strip() for x in evidence[d]))]
    if ev_missing:
        print(f"[ERROR] 以下维度缺证据位置（每维 ≥1）: {ev_missing}", file=sys.stderr)
        return 2

    # ── 机械判定（脚本为 SSOT 权威）──
    dims: dict[str, dict] = {}
    weighted = 0.0
    for name, weight in rubric.items():
        score = scores[name]
        points = score * weight / 100.0
        weighted += points
        dims[name] = {
            "score": score,
            "weight": weight,
            "points": round(points, 4),
            "evidence": [str(x) for x in evidence[name]],
        }

    weight_sum = sum(rubric.values())
    total = round(weighted, 4)
    verdict = "pass" if (weight_sum == 100 and total >= 80 and not ev_missing) else "fail"

    out = {
        "chapter": args.chapter,
        "dims": dims,
        "total": total,
        "weight_sum": weight_sum,
        "verdict": verdict,
    }

    out_dir = Path(args.work_root).expanduser() / "运行态"
    out_dir.mkdir(parents=True, exist_ok=True)
    # ★G2（v2.10）：双落盘——运行态 SSOT（门禁 4.14 消费）+ 章节契约路径
    # （member-contracts examiner must_produce 的默认路径；编排者漏传 --produce
    #   时评分不再静默无处可寻，contract_check 按契约路径必查）。
    out_file = out_dir / "r5-score.json"
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    contract_file = (Path(args.work_root).expanduser() / "章节" / args.chapter
                     / "review" / "r5_score.json")
    try:
        contract_file.parent.mkdir(parents=True, exist_ok=True)
        contract_file.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"OK  r5_score.json (契约路径) → {contract_file}")
    except OSError as e:
        # 契约路径写失败不阻塞主产物——主产物（运行态 SSOT）已成功；显式告警不静默
        print(f"[WARN] 契约路径 r5_score.json 写入失败（不阻塞，主产物已落运行态）: {e}",
              file=sys.stderr)

    print(f"OK  r5-score.json → {out_file}")
    print(f"R5_TOTAL={total}")
    print(f"R5_WEIGHT_SUM={weight_sum}")
    print(f"R5_VERDICT={verdict}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
