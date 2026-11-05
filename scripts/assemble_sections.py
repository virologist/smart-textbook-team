#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assemble_sections.py — 节级正文拼接器（E4 落地：pipeline §3.6 步骤③的工具支撑）

==============================================================================
为什么有这个脚本（2026-10-31 E4 实测缺口）
------------------------------------------------------------------------------
pipeline §3.6 规定「>8000 字章节强制按节推进：sections/{节号}.md → 拼接为 draft.md，
拼接必须记录来源节号」。但此前：
  - scripts/ 无任何拼接工具（build_manuscript.py 只直读 draft.md）
  - 「来源节号」记录格式未定义
  - 拼接人（subject-writer）手工 cat → 漏节/错序不可审计
本脚本兑现步骤③：确定性拼接 + 逐节自检前置校验 + 拼接清单落盘（返修定位锚）。

用法
------------------------------------------------------------------------------
  # 基本拼接（按 chapter_design §C 节序，或 --order 显式指定）
  python3 scripts/assemble_sections.py --work-root "$WORK_ROOT" --chapter ch01

  # 显式节序（默认按 chapter_design §C 解析；解析失败时必须给 --order）
  python3 scripts/assemble_sections.py --work-root "$WORK_ROOT" --chapter ch01 \
      --order 1.1,1.2,1.3

退出码
------------------------------------------------------------------------------
  0 成功（draft.md + 拼接清单落盘）
  1 节级自检未过（标签缺失/编号断裂——禁止把带缺陷的节拼成整章）
  2 输入缺失（sections/ 为空、设计节序不可解析等）
  3 RECOVERY_REQUIRED（Batch 4 升级 E：节文件缺失，已产出恢复报告，主理人据它重派）

升级 E：缺失节恢复协议（2026-11-04）
------------------------------------------------------------------------------
旧行为：设计节序里有节号而 sections/ 无文件 ⇒ 直接 exit 1 终止，信息量为 0。
新行为：查 `拼接清单.json`（上次成功落盘记录）判定该节**曾否成功产出**：
  · 曾在清单里（文件后来丢失）→ `RECOVERABLE`：可复用上次 spawn 文案重派
  · 从未在清单里（writer 任务从未完成）→ `NEVER_PRODUCED`：按契约 on_partial=BLOCK 重派
两种路径都写合规 `BLOCK` trace（纳入 retry_rate），产出
`运行态/section_recovery_{ch##}.json`。**脚本只报不 spawn**——重派是主理人的编排权
（与 Batch 4 升级 B/F、Batch 3 parallel_gate 同一纪律）。
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _profile_loader import read_discipline, load_section7

SCRIPT_DIR = Path(__file__).resolve().parent
TRACE_TIMEOUT_S = 30

RE_SECTION_FILE = re.compile(r"^(\d+(?:\.\d+)?)\.md$")
RE_DATA_TAG = re.compile(r"\[(?:实|估|引|待核实)")
RE_FIG_SLOT = re.compile(r"\[图\s*\d+-\d+[：：]")
# 通用数值信号（兜底）：任何「数字+百分比」陈述都算数值陈述、必须带数据标签。
# 学科触发词另从 profile §7 加载（B3，ADR-02）——旧实现把 11 个兽医指标写死，
# 非兽医学科（计算机/法学）的数值陈述恒绿（C-05 病灶）。
RE_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*[%％]")
RE_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
RE_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s")


def strip_frontmatter(text: str) -> tuple[str, str]:
    """拆出 (frontmatter, 正文)。无 frontmatter 时 frontmatter 为空串。

    口径对齐 count_net_words.py 与 check_manuscript.py——三者必须同源，
    否则「标签完整率」在不同工具里量的是不同的东西（C-05 病灶）。
    """
    m = RE_FRONTMATTER.match(text)
    if not m:
        return '', text
    return m.group(1), text[m.end():]


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}", file=sys.stderr)


def parse_design_order(design_path: Path) -> list[str]:
    """从 chapter_design §C 解析节序（「节号」列）；失败返回空表。"""
    text = design_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*C[\.、．]?\s*[^\n]*\n(?:(?!^## ).)*", text, re.S | re.M)
    seg = m.group(0) if m else text
    order: list[str] = []
    for line in seg.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and re.fullmatch(r"\d+(?:\.\d+)+", cells[0]):
            order.append(cells[0])
    return order


def self_check_section(path: Path, sec_no: str, triggers: list[str] | None = None) -> list[str]:
    """节级自查（pipeline §3.6 步骤②：门禁 3.1/3.4 的节内子集）。返回问题列表。

    口径修正（R3 真实跑批暴露，2026-11-05）：
      ① **只判正文**——剥离 YAML frontmatter 后再逐行判定。旧实现把
         `节标题: M2 急性死亡与高死亡率疾病群` 这类 frontmatter 元数据行
         当成「正文陈述」⇒ 明明正文标签齐全仍被拦（exit 1），
         与门禁 3.1 原文「**正文中**凡含数值触发词的陈述」不符。
      ② **跳过标题行**——`## 第二节 M2 急性死亡/高死亡率疾病群` 是小节标题，
         不是陈述句；整章 C9 指标用句级匹配（要求句末标点）天然排除标题，
         节级行级匹配必须显式对齐，否则两把尺量两件事。
    """
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return [f"{sec_no}: 空文件"]
    _fm, body = strip_frontmatter(text)
    # 标签完整率：数值触发词陈述必须带标签（简化口径：触发词所在行无任一标签即报）。
    # 触发 = 学科触发词（profile §7）命中 或 通用百分比数值信号命中。
    triggers = triggers or []
    for i, line in enumerate(body.splitlines(), 1):
        if RE_HEADING_LINE.match(line):
            continue  # 标题行不是陈述
        hit = any(t and t in line for t in triggers) or bool(RE_PERCENT.search(line))
        if hit and not RE_DATA_TAG.search(line):
            problems.append(f"{sec_no} 行{i}: 数值触发词陈述缺 [实]/[估]/[引]/[待核实] 标签")
    # 图表位编号一致性：图位章号无须在此校验（整章门禁 3.4 管），但格式须合法
    for m in re.finditer(r"\[图\s*([^\]：:]{1,8})[：:]", text):
        if not re.fullmatch(r"\d+-\d+", m.group(1).strip()):
            problems.append(f"{sec_no}: 图位编号格式非法: [{m.group(1)}]")
    return problems


# ── 升级 E：缺失节恢复协议（脚本只报不 spawn）────────────────────────────

def load_previous_manifest(ch_dir: Path) -> tuple[dict[str, str], str]:
    """读上次成功拼接清单 → {节号: 来源文件}，以及基线状态。

    基线状态：ok / missing / corrupt。corrupt 必须显式上报，
    不得静默当成「从未产出」——那会掩盖审计数据损坏。
    """
    p = ch_dir / "拼接清单.json"
    if not p.is_file():
        return {}, 'missing'
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, 'corrupt'
    secs = data.get('sections') if isinstance(data, dict) else None
    if not isinstance(secs, list):
        return {}, 'corrupt'
    out: dict[str, str] = {}
    for s in secs:
        if isinstance(s, dict) and s.get('节号'):
            out[str(s['节号'])] = str(s.get('文件') or '')
    return out, 'ok'


def classify_missing(missing: list[str], baseline: dict[str, str],
                     baseline_status: str, chapter: str) -> list[dict]:
    """逐节判 RECOVERABLE / NEVER_PRODUCED，并给出可复用的派工提示。"""
    items: list[dict] = []
    for sec in missing:
        task_id = f"{chapter}-PRODUCE-R1-节{sec}"
        must_produce = f"章节/{chapter}/sections/{sec}.md"
        hint = {
            'task_id': task_id,
            'must_produce': must_produce,
            'reuse': '复用上次 spawn 文案（任务包可重建）',
        }
        if sec in baseline:
            items.append({
                '节号': sec,
                'classification': 'RECOVERABLE',
                'evidence': (f"上次成功拼接清单含该节（来源 {baseline[sec] or '未记文件'}）"
                             f"，但本次文件丢失 ⇒ 曾成功落盘"),
                'suggested_action': 'E2 升级：主理人按 spawn_hint 重派该节（任务包可复用）',
                'spawn_hint': hint,
            })
        else:
            reason = ('上次成功清单无该节 ⇒ writer 任务从未完成'
                      if baseline_status == 'ok' else
                      f'拼接清单基线状态={baseline_status}，无法证明曾成功落盘 ⇒ 保守按从未产出')
            items.append({
                '节号': sec,
                'classification': 'NEVER_PRODUCED',
                'evidence': reason,
                'suggested_action': '按成员契约 on_partial=BLOCK，主理人重派该节',
                'spawn_hint': hint,
            })
    return items


def write_recovery_trace(work_root: Path, chapter: str, report: dict,
                         started_at: str) -> tuple[bool, str]:
    """写合规 BLOCK 行（纳入 compute_metrics.retry_rate），不绕过 record_trace.py。"""
    counts: dict[str, int] = {}
    for it in report['missing']:
        counts[it['classification']] = counts.get(it['classification'], 0) + 1
    notes = ('SECTION_RECOVERY; chapter=' + chapter
             + '; ' + '; '.join(f'{k}={v}' for k, v in sorted(counts.items()))
             + '; sections=' + ','.join(it['节号'] for it in report['missing']))
    cmd = [
        sys.executable, str(SCRIPT_DIR / 'record_trace.py'),
        '--work-root', str(work_root),
        '--task-id', f'{chapter}-PRODUCE-R1-SECTION-RECOVERY',
        '--from', 'smart-textbook-team-team-lead',
        '--to', 'smart-textbook-team-team-lead',
        '--type', 'BLOCK',
        '--outcome', 'BLOCKED',
        '--phase', 'PRODUCE-R1',
        '--start', started_at,
        '--notes', notes,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TRACE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f'调用 record_trace.py 失败: {e}'
    if r.returncode != 0:
        return False, (f'record_trace.py exit {r.returncode}: '
                       f'{r.stderr.strip() or r.stdout.strip()}')
    return True, r.stdout.strip()


def handle_recovery(work_root: Path, ch_dir: Path, chapter: str,
                    order: list[str], present: list[str],
                    missing: list[str], write_trace: bool) -> int:
    """缺节 ⇒ 出恢复报告（不拼接、不 spawn），退出码 3。"""
    baseline, baseline_status = load_previous_manifest(ch_dir)
    started_at = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    items = classify_missing(missing, baseline, baseline_status, chapter)
    report = {
        'chapter': chapter,
        'detected_at': started_at,
        'status': 'RECOVERY_REQUIRED',
        'order': order,
        'present': present,
        'missing': items,
        'baseline_status': baseline_status,
        'baseline_sections': sorted(baseline),
        'script_only_reports': True,
        'note': '脚本只报决策，重派由主理人执行；两种 classification 均已写 BLOCK trace 以纳入 retry_rate',
        'trace_written': False,
    }
    trace_error = None
    if write_trace:
        ok, detail = write_recovery_trace(work_root, chapter, report, started_at)
        report['trace_written'] = ok
        if not ok:
            trace_error = detail
    if trace_error:
        report['trace_error'] = trace_error

    out = work_root / '运行态' / f'section_recovery_{chapter}.json'
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                       encoding='utf-8')
    except OSError as e:
        log(f'恢复报告写入失败: {out}（{e}）', 'ERROR')
        return 2

    log(f'缺 {len(missing)} 节 ⇒ 不拼接；恢复报告: {out}', 'ERROR')
    for it in items:
        log(f"  · {it['节号']}: {it['classification']} — {it['evidence']}", 'ERROR')
    if baseline_status != 'ok':
        log(f'拼接清单基线状态={baseline_status}（不得静默当「从未产出」）', 'WARN')
    if trace_error:
        log(f'BLOCK trace 写入失败（不静默）: {trace_error}', 'ERROR')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 3


def main() -> int:
    ap = argparse.ArgumentParser(description="节级正文拼接器（pipeline §3.6 步骤③）")
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--chapter", required=True, help="如 ch01")
    ap.add_argument("--order", default=None,
                    help="逗号分隔节序（缺省从 chapter_design §C 解析）")
    ap.add_argument("--skip-check", action="store_true",
                    help="跳过节级自查（仅限主理人显式豁免并记录 interventions）")
    ap.add_argument("--no-trace", action="store_true",
                    help="缺节时不写 BLOCK trace（仅供 CI/离线排查；常态必须写以纳入 retry_rate）")
    args = ap.parse_args()

    work_root = Path(args.work_root).expanduser()
    ch_dir = work_root / "章节" / args.chapter
    sec_dir = ch_dir / "sections"
    if not sec_dir.is_dir():
        log(f"sections/ 不存在：{sec_dir}（无节级文件，无需拼接；整章推进模式直接用 draft.md）")
        return 0

    sec_files = sorted(sec_dir.glob("*.md"))
    if not sec_files:
        log(f"sections/ 为空：{sec_dir}", "ERROR")
        return 2

    # 节序：显式 > 设计解析 > 文件名自然序
    order: list[str] = []
    if args.order:
        order = [s.strip() for s in args.order.split(",") if s.strip()]
    else:
        design = ch_dir / "chapter_design.md"
        if design.is_file():
            order = parse_design_order(design)
    file_map = {RE_SECTION_FILE.match(f.name).group(1): f
                for f in sec_files if RE_SECTION_FILE.match(f.name)}
    if order:
        missing_on_disk = [s for s in order if s not in file_map]
        if missing_on_disk:
            log(f"节序中有 {len(missing_on_disk)} 节缺文件: {missing_on_disk}", "ERROR")
            return handle_recovery(work_root, ch_dir, args.chapter, order,
                                   sorted(file_map), missing_on_disk,
                                   write_trace=not args.no_trace)
        extra = [s for s in file_map if s not in order]
        if extra:
            log(f"磁盘上有节不在设计节序中（将被忽略，请确认）: {extra}", "WARN")
        ordered = [file_map[s] for s in order]
        order_used = order
    else:
        ordered = sec_files
        order_used = [RE_SECTION_FILE.match(f.name).group(1) for f in sec_files]
        log("未指定 --order 且设计解析失败 → 按文件名自然序拼接（建议显式给序）", "WARN")

    # 节级自查（步骤②前置——不过审不得拼接）
    if not args.skip_check:
        _discipline = read_discipline(work_root, args.chapter)
        _triggers = load_section7(work_root, _discipline, "number_triggers")
        all_problems: list[str] = []
        for f, s in zip(ordered, order_used):
            all_problems.extend(self_check_section(f, s, _triggers))
        if all_problems:
            log(f"节级自查未过（{len(all_problems)} 项）——禁止拼接，回 writer 修节：", "ERROR")
            for p in all_problems[:20]:
                log(f"  ✗ {p}", "ERROR")
            return 1

    # 拼接：frontmatter（draft 若已有则保留）+ 各节全文 + 拼接清单
    parts: list[str] = []
    for f in ordered:
        body = f.read_text(encoding="utf-8").strip()
        # 各节若自带 frontmatter，剥离（只保留 draft 级一份）
        fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", body, re.S)
        if fm:
            body = body[fm.end():]
        parts.append(body)
    draft = ch_dir / "draft.md"
    head = ""
    if draft.is_file():
        old = draft.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", old, re.S)
        if m:
            head = f"---\n{m.group(1)}\n---\n\n"
    draft.write_text(head + "\n\n".join(parts) + "\n", encoding="utf-8")

    # 拼接清单（返修定位锚：来源节号 → draft 内位置序）
    manifest = {
        "chapter": args.chapter,
        "assembled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "order": order_used,
        "sections": [{"节号": s, "文件": f"sections/{f.name}"} for s, f in zip(order_used, ordered)],
        "self_check": "passed" if not args.skip_check else "skipped(主理人豁免)",
    }
    (ch_dir / "拼接清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"拼接完成：{draft}（{len(ordered)} 节，顺序 {order_used}；清单：拼接清单.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
