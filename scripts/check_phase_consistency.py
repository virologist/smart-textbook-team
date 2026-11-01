#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_phase_consistency.py — 相位字面量一致性门禁（ADR-04 状态机归一）

背景（K4 四方口径矛盾）
------------------------
`progress.py` 的 `PHASE_ORDER` 是相位枚举的**唯一权威**，但包内四份文档
（pipeline §轮次归属 / harness §6.3 / team-lead / examiner）各自复述了一份，
于是出现「13 态 + VERIFY-R1~R4」「VERIFY-R5」「PROOFREAD」三种描述并存，
外加两个全包 0 处写入的僵尸态。人读文档写 progress、脚本按 PHASE_ORDER 校验，
两边一错就必卡死。

本脚本把「只许引用、不许复述」变成机械判据：**凡是相位字面量，必须能在
`PHASE_ORDER`（或 `PHASE_ALIAS`）里找到**，否则 exit 1。

判据分层（为什么不是简单的 [A-Z][A-Z0-9-]{3,} 全量比对）
----------------------------------------------------------
实测本包 .md 里符合该正则的大写 token 有 **168 个**（PMID/SSOT/WORK_ROOT/E1-E5/
H15/P0-3/W4/R3/R1-R5…）。若把它们都要求「必须在 PHASE_ORDER 里」，CI 会长期
红灯，最后必然被人关掉——这比没有门禁更糟。

故本脚本用**相位词根收敛**：
  1. 先由 PHASE_ORDER / PHASE_ALIAS 反推词根集（BOOTSTRAP…LEARN）；
  2. 只把「词根」或「词根-R<数字>」形态认作相位字面量（含嵌在
     `ch##-VERIFY-R4-节1` 这类 task_id 里的写法）；
  3. 其余大写 token 一律不作为失败判据（可用 `--strict-unknown` 打开全量白名单模式，
     默认关闭——白名单不可能穷尽真实文档，宁可放过不可误杀）。

其余三层自检（防止判据本身失效后"静默全绿"）：
  A. PHASE_ORDER 必须等于 ADR-04 契约快照（防有人把权威源改回旧名后门禁跟着"自动一致"）；
  B. 每个别名目标必须在 PHASE_ORDER 内；
  C. 旧名（VERIFY-R4/R5）不得出现在 PHASE_ORDER 里，且必须登记在 LEGACY_PHASE。
  D. 扫描到的相位字面量总数必须 > 0（正则为空 = 判据坏掉，不得判 PASS）。

免检通道（历史记录按定义不可改写）
----------------------------------
  - 文件级：`CHANGELOG.md` / `skills/SKILL_CHANGELOG.md`（追加式历史流水）
  - 目录级：`03-code/`（批次交付说明，内含「旧名 → 新名」对照表与实跑输出原文，
    照抄原文是证据要求，加免检标记反而篡改证据）。需要时 `--include-delivery-docs` 纳入
  - 行级：任何含 `phase-consistency:ignore` 的行（用于正文里的旧名→新名对照）

用法:
  python3 scripts/check_phase_consistency.py --root .
  python3 scripts/check_phase_consistency.py --root . --verbose     # 附扫描统计
  python3 scripts/check_phase_consistency.py --root . --strict-unknown   # 白名单全量模式
  python3 scripts/check_phase_consistency.py --root . --include-delivery-docs  # 连 03-code/ 一起扫
  python3 scripts/check_phase_consistency.py --root . --json

退出码：0 一致 | 1 发现不一致 | 2 权威源不可用或判据自身失效
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

# ── ADR-04 契约快照 ────────────────────────────────────────────────────
# 与 progress.py 的 PHASE_ORDER 逐项比对的**期望值**。这不是第二份权威，
# 而是"权威源的指纹"：只用于发现权威源被悄悄改名/回滚。改相位必须两处同改，
# 且改这里就等于改契约——须同步 GATE2-designs.md §4 与本脚本的文档。
EXPECTED_PHASES = [
    # 全书域（ADR-01 全书层，批次 B5）
    'BOOK_BOOTSTRAP', 'BOOK_SPEC', 'CHAPTER_SCHEDULE', 'BOOK_CONSOLIDATION', 'BOOK_DELIVER',
    # 章域
    'BOOTSTRAP', 'INTAKE', 'CLARIFY', 'SPECIFY', 'RETRIEVE',
    'PRODUCE-R1', 'VERIFY-R1', 'PRODUCE-R2', 'VERIFY-R2',
    'PRODUCE-R3', 'VERIFY-R3', 'PROOFREAD-R4', 'PROOFREAD-R5',
    'CONSOLIDATION', 'VISUALIZE', 'ASSEMBLE',
    'DELIVER', 'LEARN',
]

# 不参与扫描的目录 / 文件（历史流水与缓存）
SKIP_DIRS = {'.git', '.pytest_cache', 'node_modules', '__pycache__', '.venv',
             # 批次交付说明目录：内含「旧名 → 新名」对照表与实跑输出原文，
             # 照抄原文是证据要求，给它加免检标记反而会篡改证据。
             # 需要连它一起查时加 --include-delivery-docs。
             '03-code'}
SKIP_FILES = {'CHANGELOG.md', 'SKILL_CHANGELOG.md'}
IGNORE_MARK = 'phase-consistency:ignore'

# --strict-unknown 用的非相位大写词白名单（常见项；不追求穷尽，
# 该模式默认关闭，仅在被明确要求"连未知大写词也查"时启用）
UNKNOWN_WHITELIST = {
    # 工件 / 协议术语
    'WORK', 'ROOT', 'WORK_ROOT', 'SSOT', 'SKILL', 'STATUS', 'PHASE', 'NEXT',
    'CLOSED', 'OPEN', 'HALF', 'RESOLVED', 'BLOCKED', 'RESULT', 'ERROR',
    'FAIL', 'PASS', 'WARN', 'DONE', 'BLOCK', 'NEED', 'INPUT', 'TODO',
    'SPOOFED', 'SENDER', 'POISON', 'DETECTED', 'SILENT', 'FAILURE',
    'DEGRADE', 'FATIGUE', 'SCOPE', 'WRITE', 'BEFORE', 'PAGE', 'REPO',
    'VENDOR', 'EXPERT', 'README', 'LICENSE', 'CONTRIBUTING', 'CHANGELOG',
    'AGENTS', 'DOCX', 'YAML', 'JSON', 'HTML', 'ASCII', 'IEEE', 'CNKI',
    # B3（ADR-02）：WAHIS/ICTV/WOAH/USDA/ELISA 属兽医/动卫/生物学科常量，已下沉 profile；
    # 通用层白名单只留跨学科缩写（ISBN/UNEP/ASTM 等）。
    'ISBN', 'UNEP', 'ASTM',
    'TZUV', 'MUST', 'EXTRA', 'FENCE', 'TABLE', 'MEMBER', 'ARTIFACT',
    'ORDINARY', 'TOKENS', 'USED', 'MANUSCRIPT', 'EXECUTABLE', 'PUPPETEER',
    'VAULT', 'CENTRE', 'CENTER', 'UPPERCASE', 'VERSION', 'ISO8601',
    'YYYY', 'YYYYMMDD', 'YYYY-MM-DD', 'ECMAS', 'PROGRESS',
    # 编号 / 标签形态（E1-E5 / W1-W4 / P0-P4 / R1-R5 / H15 / 问题号）
    'E1', 'E2', 'E3', 'E4', 'E5', 'W1', 'W2', 'W3', 'W4',
    'P0', 'P1', 'P2', 'P3', 'P4', 'R1', 'R2', 'R3', 'R4', 'R5', 'H15',
}
_UNKNOWN_PATTERNS = [
    re.compile(r'^[EWP]\d(-[A-Z]*\d+)?$'),      # E1-E5 / W1-W4 / P0-3 / P1-P3
    re.compile(r'^R\d-R\d$'),                    # R1-R3
    re.compile(r'^[A-Z]-\d+$'),                  # C-10 / P2-6
    re.compile(r'^P\d-\d+$'),                    # P2-6
    re.compile(r'^(LE|ESC|BUG|G|E|F|D|C|A|B)[-_]?[A-Z]*[-_]?\d+[A-Za-z0-9-]*$'),  # 编号族
]


class Gate:
    """收集失败项并按统一格式输出（文件:行号: 错误值 → 正确值）"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.notes: list[str] = []

    def fail(self, where: str, msg: str) -> None:
        self.errors.append(f'{where}: {msg}' if where else msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def load_progress_module(root: Path):
    """从 <root>/scripts/progress.py 导入权威枚举（import 而非复述）。"""
    src = root / 'scripts' / 'progress.py'
    if not src.is_file():
        raise FileNotFoundError(f'权威源不存在: {src}')
    spec = importlib.util.spec_from_file_location('_stt_progress', src)
    if spec is None or spec.loader is None:
        raise ImportError(f'无法为 {src} 建立模块 spec')
    mod = importlib.util.module_from_spec(spec)
    # 不写入 sys.modules：避免污染其它脚本同名导入，且 progress.py 导入期无副作用
    spec.loader.exec_module(mod)
    for attr in ('PHASE_ORDER', 'PHASE_ALIAS', 'LEGACY_PHASE'):
        if not hasattr(mod, attr):
            raise AttributeError(f'{src} 缺少 {attr}——权威源结构已变，门禁须同步')
    return mod


def phase_roots(phases) -> list[str]:
    """由相位名反推词根（PRODUCE-R1 → PRODUCE），按长度降序保证正则最长优先。"""
    roots = {re.sub(r'-R\d+$', '', p) for p in phases}
    return sorted(roots, key=len, reverse=True)


def build_phase_re(roots) -> re.Pattern:
    """词根 + 可选 -R<n> 后缀；尾部负向断言放行 `RETRIEVED`/`PROOFREADS` 之类的更长单词。"""
    alt = '|'.join(re.escape(r) for r in roots)
    return re.compile(rf'(?<![A-Za-z_])({alt})(?:-?R(\d))?(?![A-Za-z])')


def iter_md_files(root: Path, include_delivery: bool = False):
    for p in sorted(root.rglob('*.md')):
        rel_parts = p.relative_to(root).parts
        skip_dirs = SKIP_DIRS - ({'03-code'} if include_delivery else set())
        if any(part in skip_dirs for part in rel_parts):
            continue
        if p.name in SKIP_FILES:
            continue
        yield p


def check_authority(mod, gate: Gate) -> None:
    """A/B/C 三层：权威源自洽 + 与契约快照一致。"""
    order = list(mod.PHASE_ORDER)
    alias = dict(mod.PHASE_ALIAS)
    legacy = dict(mod.LEGACY_PHASE)

    if order != EXPECTED_PHASES:
        missing = [p for p in EXPECTED_PHASES if p not in order]
        extra = [p for p in order if p not in EXPECTED_PHASES]
        # 顺序也校验：PHASE_ORDER 的顺序就是续跑推进顺序，乱序 = 续跑跳步
        detail = []
        if missing:
            detail.append(f'缺 {missing}')
        if extra:
            detail.append(f'多 {extra}')
        if not detail:
            detail.append('项集相同但顺序不同')
        gate.fail('scripts/progress.py', f'PHASE_ORDER 与 ADR-04 契约快照不一致（{"；".join(detail)}）')

    for src, dst in alias.items():
        if dst not in order:
            gate.fail('scripts/progress.py', f'PHASE_ALIAS[{src}] = {dst} 不在 PHASE_ORDER 内（别名指向不存在的相位）')
        # 别名只允许「粗粒度词根」（如 PRODUCE/VERIFY/PROOFREAD）；若别名键本身带
        # -R<n> 后缀，等于用别名给轮次改名，会把改名再次藏进第二套名字里。
        if re.search(r'-R\d+$', src):
            gate.fail('scripts/progress.py',
                      f'PHASE_ALIAS 键 {src} 带轮次后缀——别名只允许粗粒度词根，不得用作轮次改名')
        if src in legacy:
            gate.fail('scripts/progress.py',
                      f'PHASE_ALIAS 键 {src} 是 LEGACY_PHASE 里的废弃名（旧名只能报错，不得复活为别名）')
        if src not in {re.sub(r'-R\d+$', '', p) for p in order}:
            gate.fail('scripts/progress.py',
                      f'PHASE_ALIAS 键 {src} 不是任何相位名的词根（疑似笔误或多余别名）')

    for old, new in legacy.items():
        if old in order:
            gate.fail('scripts/progress.py', f'LEGACY_PHASE 的旧名 {old} 仍在 PHASE_ORDER 内（改名未完成，双名并存）')
        if new not in order:
            gate.fail('scripts/progress.py', f'LEGACY_PHASE[{old}] = {new} 不在 PHASE_ORDER 内')


def check_docs(root: Path, mod, gate: Gate, strict_unknown: bool, verbose: bool,
               include_delivery: bool = False):
    """扫描全部 .md 的相位字面量，返回 (文件数, 字面量数)。"""
    order = set(mod.PHASE_ORDER)
    valid = order | set(mod.PHASE_ALIAS) | set(mod.PHASE_ALIAS.values())
    legacy = dict(mod.LEGACY_PHASE)
    roots = phase_roots(list(mod.PHASE_ORDER) + list(mod.PHASE_ALIAS))
    phase_re = build_phase_re(roots)
    unknown_re = re.compile(r'[A-Z][A-Z0-9-]{3,}')

    files = 0
    literals = 0
    unknown_hits = 0
    for path in iter_md_files(root, include_delivery=include_delivery):
        files += 1
        rel = path.relative_to(root).as_posix()
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError as e:  # 编码/权限问题不得静默放过
            gate.fail(rel, f'无法读取（{e}）')
            continue
        for lineno, line in enumerate(lines, 1):
            if IGNORE_MARK in line:
                continue
            for m in phase_re.finditer(line):
                root_word, rnd = m.group(1), m.group(2)
                literal = f'{root_word}-R{rnd}' if rnd else root_word
                literals += 1
                if literal in valid:
                    continue
                # 不一致：给出"正确值"
                correct = legacy.get(literal)
                if correct is None:
                    siblings = [p for p in mod.PHASE_ORDER if p.startswith(root_word + '-R')]
                    correct = ('、'.join(siblings) if siblings
                               else f'{root_word} 无轮次子相位')
                gate.fail(f'{rel}:{lineno}', f'{literal} → {correct}')
            if strict_unknown:
                for tok in unknown_re.findall(line):
                    if tok in valid or tok in UNKNOWN_WHITELIST:
                        continue
                    if any(pat.match(tok) for pat in _UNKNOWN_PATTERNS):
                        continue
                    if phase_re.fullmatch(tok):
                        continue
                    unknown_hits += 1
                    gate.fail(f'{rel}:{lineno}', f'未登记的大写标识符 {tok}（--strict-unknown 模式）')
    if verbose:
        gate.note(f'扫描 {files} 个 .md，识别相位字面量 {literals} 处'
                  + (f'，未登记大写标识符 {unknown_hits} 处' if strict_unknown else ''))
    return files, literals


def main() -> int:
    ap = argparse.ArgumentParser(description='相位字面量一致性门禁（权威源 = scripts/progress.py）')
    ap.add_argument('--root', default='.', help='专家包根目录（含 scripts/ 与 *.md）')
    ap.add_argument('--strict-unknown', action='store_true',
                    help='同时校验未登记的大写标识符（白名单模式，默认关闭：误杀风险高于收益）')
    ap.add_argument('--include-delivery-docs', action='store_true',
                    help='连 03-code/（批次交付说明，含旧名对照与实跑原文）一起扫')
    ap.add_argument('--verbose', action='store_true', help='打印扫描统计')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出（供 CI 采集）')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    gate = Gate()

    try:
        mod = load_progress_module(root)
    except (FileNotFoundError, ImportError, AttributeError, SyntaxError) as e:
        # 权威源不可用 = 门禁无法判定，必须 exit 2 而非静默 PASS
        print(f'ERROR  无法加载权威源: {e}', file=sys.stderr)
        if args.json:
            print(json.dumps({'status': 'error', 'error': str(e)}, ensure_ascii=False))
        return 2

    check_authority(mod, gate)
    files, literals = check_docs(root, mod, gate, args.strict_unknown, args.verbose,
                                 include_delivery=args.include_delivery_docs)

    # 判据自检：扫不到任何相位字面量说明正则/路径出了问题（本包必然 >0），不得判 PASS
    if literals == 0:
        gate.fail('', '扫描到 0 处相位字面量——判据可能已失效（检查 --root 与正则），拒绝判 PASS')

    total = len(mod.PHASE_ORDER)
    if gate.errors:
        print(f'FAIL  相位不一致 {len(gate.errors)} 处（权威源 PHASE_ORDER 共 {total} 相位）')
        for e in gate.errors:
            print(f'  - {e}')
        for n in gate.notes:
            print(f'  · {n}')
        if args.json:
            print(json.dumps({'status': 'fail', 'errors': gate.errors,
                              'scanned_files': files, 'literals': literals},
                             ensure_ascii=False))
        return 1

    print(f'PASS  相位一致：{total} 相位 / {files} 个 .md / {literals} 处相位字面量 / 0 不一致')
    for n in gate.notes:
        print(f'  · {n}')
    if args.json:
        print(json.dumps({'status': 'pass', 'scanned_files': files,
                          'literals': literals, 'phases': total}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
