#!/usr/bin/env python3
"""progress.py — 长任务续跑 checkpoint 写入与读取

工件路径:{WORK_ROOT}/运行态/progress.md
用途:章节跑完后被中断,重启时读此文件恢复 phase + 续 task_id。

状态机:章节生命周期由 13 态管线驱动,本工具记录已完成/待续/阻塞。
  **相位枚举的唯一权威是下方 PHASE_ORDER（23 相位 = 5 个 BOOK_* 全书相位 + 18 个章域相位）；
  其余文档只引用不复述**，一致性由 `scripts/check_phase_consistency.py` 机械校验（ADR-04）。
写入语义:按 phase 行 upsert(同 phase 更新状态/摘要/时间,不新增行);真正的 append-only 审计流是 trace.jsonl。init 幂等:文件已存在且章节一致时直接返回(不覆盖);章节不一致则 exit 2 硬失败(防止多章串档)。

状态取值:DONE / IN_PROGRESS / BLOCKED / BLOCKED_RESOLVED / SKIPPED。
  BLOCKED_RESOLVED = 该 phase 曾阻塞、现已解除,阶段可继续推进;
  它只改阶段行状态,不自动清"## 阻塞清单"(清哪一条由人判定)。
  (2026-10-29 修复:此前 CLI choices 未收录该值 → 该分支是死代码,阻塞登记后无法标解除)

用法:
  # 写入/更新一个 phase 完成状态（单章工作区可省略 --chapter）
  python3 scripts/progress.py --work-root /path/to/work update \\
      --phase SPECIFY --status DONE \\
      --summary "design-bloom 已完成,Bloom 分层 + 块级 DAG 已写入 chapter_design.md"

  # 多章工作区（章节级并行调度）：必须显式指定目标章
  python3 scripts/progress.py --work-root /path/to/work update \\
      --chapter ch03 --phase PRODUCE-R1 --status DONE \\
      --summary "ch03 骨架完成"

  # 读取当前状态
  python3 scripts/progress.py --work-root /path/to/work show

  # 迁移一个已存在的 progress.md（旧相位名 VERIFY-R4/R5 → PROOFREAD-R4/R5）
  python3 scripts/progress.py --work-root /path/to/work migrate [--dry-run]
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 相位枚举（**唯一权威源**，ADR-04 状态机归一）──────────────────────────
# 全包的相位名以本列表为准；四份文档（pipeline / harness / team-lead / examiner）
# 只许**引用**、不许复述，一致性由 scripts/check_phase_consistency.py 机械校验。
# 所以任何一处改名都必须改这里，并同步 progress.md 既有行（见 migrate 子命令）。
PHASE_ORDER = [
    # 全书域（ADR-01 全书层，2026-11-01 批次 B5）：BOOK_* 前缀与章域相位互不干扰
    'BOOK_BOOTSTRAP', 'BOOK_SPEC', 'CHAPTER_SCHEDULE', 'BOOK_CONSOLIDATION', 'BOOK_DELIVER',
    # 章域（18 相位）
    'BOOTSTRAP', 'INTAKE', 'CLARIFY', 'SPECIFY', 'RETRIEVE',
    'PRODUCE-R1', 'VERIFY-R1', 'PRODUCE-R2', 'VERIFY-R2',
    'PRODUCE-R3', 'VERIFY-R3', 'PROOFREAD-R4', 'PROOFREAD-R5',
    'CONSOLIDATION', 'VISUALIZE', 'ASSEMBLE',
    'DELIVER', 'LEARN',
]
# 全书域相位（BOOK_* 前缀派生，供 book 子命令与 check_book.py 识别）
BOOK_PHASES = [p for p in PHASE_ORDER if p.startswith('BOOK_')]

# ── ADR-04 改名（2026-11-01 批次 B1）────────────────────────────────────
# 病史：R4/R5 两轮属 PROOFREAD 态（pipeline §轮次归属 SSOT / examiner 契约），
# 却记成 VERIFY-R4 / VERIFY-R5。而全包**没有任何一处**以这两个名字写入 progress
# → 僵尸态；续跑按 PHASE_ORDER 顺序推进，第一个卡点就是它们（顺序 12、13），
# 中断即必死。
# 语义不变：只是改名归位，不新增/不删除任何相位，执行顺序仍为 R1→R2→R3→R4→R5。
LEGACY_PHASE = {
    'VERIFY-R4': 'PROOFREAD-R4',
    'VERIFY-R5': 'PROOFREAD-R5',
}

# ── D-6 修复（2026-10-30 批次 B）─────────────────────────────────────────
# pipeline skill §门禁3 明确要求「门禁 3 结论记入 运行态/progress.md 的
# **PRODUCE 行**摘要」，但 PHASE_ORDER 只有细粒度的 PRODUCE-R1/R2/R3，
# 实跑 `update --phase PRODUCE` → `ValueError: 未知 phase`
# → **门禁 3 的结论在协议层面无处可写**（结论落不了盘 = 门禁不可审计）。
#
# 现补粗粒度别名：PRODUCE/VERIFY/PROOFREAD 视为「该阶段当前轮次」的别名，
# 映射到该阶段**最后一个**轮次，使「记入 PRODUCE 行」的协议语义可执行。
# ADR-04 修正：VERIFY 原指向 VERIFY-R5 是语义错位（R4/R5 不属 VERIFY），
# 现指 VERIFY-R3（VERIFY 的末轮）；PROOFREAD 别名指向 R5（PROOFREAD 的末轮）。
PHASE_ALIAS = {
    'PRODUCE': 'PRODUCE-R3',
    'VERIFY': 'VERIFY-R3',
    'PROOFREAD': 'PROOFREAD-R5',
}

# ── D-01 终审整改（2026-11-01，#71 判据 Q2 机械执行体）───────────────────
# audience 四档枚举的 SSOT = references/audience-profiles.md §0/§1（表为唯一权威，
# 此处硬编码为执行副本——表改档位时须同步本列表，check_audience_terms 门禁同源）。
# 此前 init/book init 接受任意 audience 值（如「小学生」）EXIT=0 落盘非法值，
# 而 examiner R1 的「枚举越界 → blocking」是 LLM 层声明、无法反查——机械层先拦，
# 非法值不进运行态工件（判据 Q2 声明自此有机械反查落点）。
AUDIENCE_ENUM = ['高职专科', '职业本科', '学术本科', '研究生']
AUDIENCE_DEFAULT = '职业本科'  # 未声明回落默认档；回落须在 issues 显式声明（SSOT §0）


def validate_audience(audience: str) -> str | None:
    """audience 枚举断言（判据 Q2）：非法值返回错误信息，合法/空返回 None。

    空值放行（book init 缺省语义 = 未声明，由 SSOT §0 回落规则接管，
    不在本层静默替默认值——回落声明义务在成员，不静默）。
    """
    if not audience or audience in AUDIENCE_ENUM:
        return None
    return (f'audience 非法值: {audience}; 合法枚举 = {AUDIENCE_ENUM}'
            f'（SSOT = references/audience-profiles.md §1;未声明留空 → 回落 {AUDIENCE_DEFAULT}）')


class LegacyPhaseError(ValueError):
    """传入 ADR-04 改名前的旧相位（VERIFY-R4/VERIFY-R5）。

    刻意**不静默映射**：静默会让旧 WORK_ROOT 的 progress.md 永久留下旧名行，
    审计表里出现两套名字——正是本包"越修越乱"的那类历史包袱（ADR-04 明文禁止）。
    正确处置：先 `progress.py migrate` 把旧行改写掉，再按新名写入。
    """

    def __init__(self, phase: str, correct: str):
        self.phase = phase
        self.correct = correct
        super().__init__(
            f'已废弃的相位名 {phase} → 正确名是 {correct}'
            f'（R4/R5 属 PROOFREAD 态，不属 VERIFY）。'
            f'既有 progress.md 请先执行 `progress.py --work-root <WORK_ROOT> migrate` 改写旧行')


# ── 并发写基础设施（2026-11-04 P1-0）────────────────────────────────────
# 病史：章节级并行调度要求「多章同时写 progress.md」。此前 progress.py
# 的读-改-写既无锁、也非原子，多个章节并行 update 时会互相覆盖
# （实测 ch01/ch02 的 PRODUCE-R1 行被 ch03 覆盖，ch02/ch03 段丢行）。
# 现补：① 跨进程文件锁（fcntl.flock，退化时用原子建锁文件）② 原子替换写
# ③ 章段清单提取。
#
# 与 record_trace.py 的 flock 同源（harness §「flock 原子 append」条款）。

def _file_lock(path: Path):
    """跨进程排他锁（上下文管理器）。fcntl 不可用时退化为 O_EXCL 锁文件。"""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        lock_path = path.with_name(path.name + '.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = None
        try:
            import fcntl  # type: ignore
            fh = open(lock_path, 'w')
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        except ImportError:
            # 无 fcntl（Windows）：用 O_EXCL 锁文件做互斥 + 陈旧锁回收
            deadline = time.time() + 10.0
            while True:
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    break
                except FileExistsError:
                    if time.time() > deadline:
                        # 陈旧锁（持有者已崩溃）→ 强制回收，避免死锁
                        try:
                            lock_path.unlink()
                        except OSError:
                            pass
                        continue
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
        finally:
            if fh is not None:
                try:
                    import fcntl  # type: ignore
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                fh.close()

    return _cm()


def _atomic_write(path: Path, text: str) -> None:
    """原子替换写（同目录临时文件 + os.replace）。避免写到一半被读到半行。"""
    tmp = path.with_name(path.name + f'.tmp{os.getpid()}')
    tmp.write_text(text, encoding='utf-8')
    os.replace(str(tmp), str(path))


def _all_chapter_spans(text: str) -> list[str]:
    """列出 progress.md 中全部「# Progress · {ch}」章段（不含「全书」段）。"""
    out = []
    for m in re.finditer(r'^# Progress · (\S+)\s*$', text, re.M):
        name = m.group(1)
        if name != '全书':
            out.append(name)
    return out


def progress_file(work_root: Path) -> Path:
    d = work_root / '运行态'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'progress.md'


def _chapter_section(chapter: str, textbook: str, audience: str, ts: str) -> str:
    """生成单章 progress 段（init_progress 与 book 模式多章追加共用）。"""
    return f"""# Progress · {chapter}

> 章节: {chapter} ｜ 教材: {textbook} ｜ 受众: {audience} ｜ 初始化: {ts}
> 续跑方式:重启后 `python3 scripts/progress.py --work-root $WORK_ROOT show` 查看当前 phase,
> 再 `team-lead: spawn 成员 -task_id={chapter}-<NEXT_PHASE>-state=resume`

## 阶段进度

| Phase | 状态 | 摘要 | 时间 |
|-------|------|------|------|
| BOOTSTRAP | DONE | 工作目录初始化 | {ts} |

## 阻塞清单 (H15 缺口)

（暂无）

## 下次恢复

```
spawn smart-textbook-team-team-lead
  → Phase A 续读此 progress.md
  → 进入下一个 phase
```
"""


def init_progress(work_root: Path, chapter: str, textbook: str, audience: str) -> Path:
    p = progress_file(work_root)
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if p.exists():
        existing = p.read_text(encoding="utf-8")
        if f"Progress · {chapter}" not in existing:
            if "# Progress · 全书" in existing:
                # ADR-01 全书模式（B5）：同一 WORK_ROOT 可承载多章，追加章段
                section = _chapter_section(chapter, textbook, audience, ts)
                p.write_text(existing.rstrip("\n") + "\n\n---\n\n" + section, encoding="utf-8")
                return p
            # P17 修复(2026-10-29):原实现只 WARN 后 return,调用方误以为 init 成功,
            # 随后 show 仍返回旧章 → 同一 WORK_ROOT 跑多章必然串档。改为硬失败。
            # B5（ADR-01）放宽：仅在「未做过 book init」的单章模式下保留硬失败。
            m = re.search(r'^# Progress · (\S+)', existing, re.M)
            cur = m.group(1) if m else '(未知)'
            print(
                f"ERROR  progress.md 已存在且章节不符:现有={cur} 请求={chapter}。"
                f"同一 WORK_ROOT 只服务一章;换章请另建 WORK_ROOT、先归档旧文件，"
                f"或先 `progress.py book init` 进入全书模式。",
                file=sys.stderr)
            sys.exit(2)
        return p
    p.write_text(_chapter_section(chapter, textbook, audience, ts), encoding='utf-8')
    return p


def book_spec_path(work_root: Path) -> Path:
    return work_root / '运行态' / 'book-spec.md'


def init_book(work_root: Path, textbook: str, chapters: list[str],
              audience: str = '', word_budget: int = 0) -> Path:
    """全书层初始化（ADR-01 批次 B5）：写 book-spec.md + progress.md「Progress · 全书」段。

    book-spec.md 是 BOOK_BOOTSTRAP 产物（章清单/每章字数/难度梯度/目标学段），
    由 check_book.py 5.1/5.2 校验；「Progress · 全书」段承载 BOOK_* 相位 + 章节矩阵。
    幂等：book-spec.md 已存在且章清单一致 → 直接返回；不一致 → exit 2（防串书）。
    """
    spec = book_spec_path(work_root)
    spec.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    per = word_budget // len(chapters) if (word_budget and chapters) else 0
    ch_lines = []
    for i, ch in enumerate(chapters, 1):
        ch_lines.append(f"  - id: {ch}\n    word_budget: {per}\n"
                        f"    difficulty: L{i}\n    domain: \n")
    body = (f"---\n"
            f"textbook: {textbook}\n"
            f"audience: {audience}\n"
            f"total_word_budget: {word_budget or per * len(chapters)}\n"
            f"chapters:\n" + "".join(ch_lines) +
            f"---\n\n"
            f"# 全书规格（book-spec · BOOK_BOOTSTRAP 产物）\n\n"
            f"> 初始化: {ts} ｜ 由 `progress.py book init` 生成。\n"
            f"> 每章字数预算 / 难度梯度 / 知识域由主理人在 BOOK_SPEC 相位补全\n"
            f"> （check_book.py 5.1/5.2 校验）。\n")
    if spec.exists():
        old = spec.read_text(encoding='utf-8')
        old_chs = re.findall(r'^\s*- id: (\S+)', old, re.M)
        if old_chs == chapters:
            return spec
        print(f"ERROR  book-spec.md 已存在且章清单不符:现有={old_chs} 请求={chapters}",
              file=sys.stderr)
        sys.exit(2)
    spec.write_text(body, encoding='utf-8')

    # progress.md「Progress · 全书」段（prepend；已存在则不动）
    p = progress_file(work_root)
    matrix = "\n".join(f"| {ch} | — | — |" for ch in chapters)
    book_section = (f"# Progress · 全书\n\n"
                    f"> 教材: {textbook} ｜ 章: {', '.join(chapters)} ｜ 初始化: {ts}\n\n"
                    f"## 阶段进度\n\n"
                    f"| Phase | 状态 | 摘要 | 时间 |\n"
                    f"|-------|------|------|------|\n"
                    f"| BOOK_BOOTSTRAP | DONE | 全书初始化（book-spec.md 已落盘） | {ts} |\n\n"
                    f"## 章节矩阵\n\n"
                    f"| 章 | 相位 | 门禁 |\n"
                    f"|----|------|------|\n"
                    f"{matrix}\n\n---\n\n")
    if p.exists():
        existing = p.read_text(encoding='utf-8')
        if "# Progress · 全书" not in existing:
            p.write_text(book_section + existing, encoding='utf-8')
    else:
        p.write_text(book_section, encoding='utf-8')
    return spec


def book_status(work_root: Path) -> int:
    """全书进度矩阵（ADR-01 B5）：读 book-spec.md + progress.md，输出各章相位。"""
    spec = book_spec_path(work_root)
    if not spec.exists():
        print("(book-spec.md 不存在 — 全书未初始化，先 `progress.py book init`)")
        return 1
    txt = spec.read_text(encoding='utf-8')
    m = re.search(r'^textbook: (.+)$', txt, re.M)
    textbook = m.group(1).strip() if m else '(未知)'
    chs = re.findall(r'^\s*- id: (\S+)', txt, re.M)
    p = progress_file(work_root)
    progress_txt = p.read_text(encoding='utf-8') if p.exists() else ''
    print(f"全书 · {textbook}（{len(chs)} 章）")
    print("-" * 44)
    print(f"{'章':<8}{'相位':<20}{'门禁'}")
    for ch in chs:
        # 从章段「## 阶段进度」表里取最后一个非空相位
        seg = re.search(rf'^# Progress · {re.escape(ch)}\s*\n(.*?)(?=^# Progress · |\Z)',
                        progress_txt, re.S | re.M)
        phase = '—'
        if seg:
            rows = re.findall(r'^\| ([A-Z][A-Z0-9-]*) \| ([A-Z_]+) \|', seg.group(1), re.M)
            if rows:
                phase = rows[-1][0]
        print(f"{ch:<8}{phase:<20}—")
    return 0


def _upsert_book_phase(text: str, phase: str, status: str, summary: str, ts: str) -> str | None:
    """在「Progress · 全书」段的阶段进度表里 upsert 一个 BOOK_* 行；无全书段返回 None。"""
    m = re.search(r'(^# Progress · 全书\s*\n)(.*?)(?=^# Progress · |\Z)', text, re.S | re.M)
    if not m:
        return None
    head, body = m.group(1), m.group(2)
    pattern = re.compile(rf'^\| {re.escape(phase)} \| .*? \|.*? \|.*? \|$', re.MULTILINE)
    new_row = f'| {phase} | {status} | {summary} | {ts} |'
    if pattern.search(body):
        body = pattern.sub(new_row, body)
    else:
        m2 = re.search(r'\n## 章节矩阵', body)
        if m2:
            body = body[:m2.start()] + '\n' + new_row + body[m2.start():]
        else:
            body = body.rstrip('\n') + '\n' + new_row + '\n'
    return head + body


def _chapter_section_span(text: str, chapter: str) -> tuple[int, int]:
    """定位「# Progress · {chapter}」段的字符区间 [start, end)。

    2026-11-04 P1-0（实测病灶）：此前 update_phase 的章域正则**全局匹配**，
    三章并行写同一 phase 时后写者把自己的行写进了**第一章**的段里，
    并把前两章的行覆盖掉（实测：ch01/ch02 的 PRODUCE-R1 记录被 ch03 覆盖，
    ch02/ch03 段根本没有该行）。并行调度的前提就是「按章定位」，
    故此处改为按段边界切片。

    返回 (start, end)：end 为下一段「# Progress · 」标题的起始位置（末段取 len(text)）。
    找不到该章段 → 抛 ValueError（调用方转 exit 2）。
    """
    pat = re.compile(rf'^# Progress · {re.escape(chapter)}\s*$', re.M)
    m = pat.search(text)
    if not m:
        raise ValueError(
            f'progress.md 无「# Progress · {chapter}」段——请先 '
            f'`progress.py --work-root <WORK_ROOT> init --chapter {chapter} ...`'
            f'（多章工作区需逐章 init；init 幂等，可重复执行）')
    nxt = re.search(r'^# Progress · ', text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return m.start(), end


def _upsert_chapter_phase(text: str, chapter: str, phase: str,
                          status: str, summary: str, ts: str) -> str:
    """在「# Progress · {chapter}」段内 upsert 该 phase 行（段内定位，不越段）。"""
    start, end = _chapter_section_span(text, chapter)
    seg = text[start:end]
    pattern = re.compile(
        rf'^\| {re.escape(phase)} \| .*? \|.*? \|.*? \|$',
        re.MULTILINE,
    )
    new_row = f'| {phase} | {status} | {summary} | {ts} |'
    if pattern.search(seg):
        seg = pattern.sub(new_row, seg)
    else:
        # 插入到本段「阶段进度」表的最后一行之后
        # （不能沿用全局的「## 阻塞清单」锚点——那会插到别的章段里）
        rows = list(re.finditer(r'^\| [A-Z][A-Z0-9-]* \| .*? \|.*? \|.*? \|$',
                                seg, re.MULTILINE))
        if rows:
            pos = rows[-1].end()
            seg = seg[:pos] + '\n' + new_row + seg[pos:]
        else:
            seg = seg.rstrip('\n') + f'\n{new_row}\n'
    return text[:start] + seg + text[end:]


def update_phase(work_root: Path, phase: str, status: str, summary: str,
                 chapter: str = '') -> Path:
    # ADR-04：旧名先拦（不静默映射），再解析粗粒度别名
    if phase in LEGACY_PHASE:
        raise LegacyPhaseError(phase, LEGACY_PHASE[phase])
    # D-6：粗粒度别名（PRODUCE/VERIFY/PROOFREAD）先解析为该阶段当前轮次
    phase = PHASE_ALIAS.get(phase, phase)
    if phase not in PHASE_ORDER:
        raise ValueError(f'未知 phase: {phase}; 合法值: {PHASE_ORDER}'
                         f'（别名: {sorted(PHASE_ALIAS)}）')
    p = progress_file(work_root)
    if not p.exists():
        raise FileNotFoundError(f'progress.md 不存在: {p}; 请先 init')

    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    if phase.startswith('BOOK_'):
        # 全书域：写到「Progress · 全书」段
        with _file_lock(p):
            text = p.read_text(encoding='utf-8')
            new_text = _upsert_book_phase(text, phase, status, summary, ts)
            if new_text is None:
                raise FileNotFoundError(f'progress.md 无「Progress · 全书」段: {p}; 请先 book init')
            _atomic_write(p, new_text)
    else:
        # 章域：按章定位段内 upsert（2026-11-04 P1-0；此前全局匹配 → 并行写互相覆盖）
        with _file_lock(p):
            text = p.read_text(encoding='utf-8')
            if chapter:
                new_text = _upsert_chapter_phase(text, chapter, phase, status, summary, ts)
            else:
                # 未指定 --chapter：向后兼容单章模式，但**必须唯一命中一个章段**，
                # 否则会静默写错章（旧实现正是这样造成三章互相覆盖）。
                spans = _all_chapter_spans(text)
                if len(spans) == 1:
                    new_text = _upsert_chapter_phase(text, spans[0], phase, status, summary, ts)
                elif not spans:
                    raise ValueError(
                        'progress.md 无任何「# Progress · {chapter}」段——请先 init')
                else:
                    raise ValueError(
                        f'progress.md 含 {len(spans)} 个章段（{", ".join(spans)}）；'
                        f'多章工作区必须显式指定 --chapter <章>，否则无法定位写入目标'
                        f'（此前无参调用会写进第一章段 → 覆盖其他章记录）')
            _atomic_write(p, new_text)

    # 阻塞清单:由调用方用 `block` 子命令 / 手工维护"## 阻塞清单"段,此处不自动增删。
    # BLOCKED_RESOLVED(2026-10-29 可达性修复)= 该 phase 曾阻塞、现已解除:
    # 语义是"阶段状态可恢复推进",不自动改阻塞清单(解除哪一条由人判定,避免误清)。
    if status in ('BLOCKED', 'BLOCKED_RESOLVED'):
        pass

    # 注意：写入已在上面的 _atomic_write(p, new_text) 完成——
    # 旧实现末尾还有一句 p.write_text(text, ...)，它用**未修改的旧 text**
    # 覆盖了 new_text 的结果（2026-11-04 P1-0 实测：新写的 phase 行凭空消失）。
    # 故此处**不再重复写文件**，只回报结果。
    print(f'OK  progress[{phase} → {status}]')
    return p


def migrate_progress(work_root: Path, dry_run: bool = False) -> int:
    """把既有 progress.md 里的旧相位名改写为新名（ADR-04 回退/迁移通路）。

    改名是原子操作，但**已交付的 WORK_ROOT** 里的 progress.md 仍留着 VERIFY-R4/R5，
    直接报错会让在跑的章节续不上。本子命令提供一次性改写，可持续保留一个版本。

    改写范围：整个文件（含阶段表行与摘要文字），只替换**完整 token**，
    不动 `VERIFY-R40` 这类更长的串。幂等：已无旧名时打印 0 处并 exit 0。

    退出码：0 成功（含无需改写）| 2 progress.md 不存在
    """
    # 注意：此处**不走 progress_file()**——那个函数会 mkdir 建目录，
    # 迁移一个不存在的 WORK_ROOT 时不该留下空壳。
    p = work_root / '运行态' / 'progress.md'
    if not p.exists():
        print(f'ERROR  progress.md 不存在: {p}（先 init，或确认 --work-root 是否正确）',
              file=sys.stderr)
        return 2
    text = p.read_text(encoding='utf-8')
    new_text = text
    counts = {}
    for old, new in LEGACY_PHASE.items():
        # 前后不许粘连字母数字/连字符，避免误伤 VERIFY-R40 之类
        pat = re.compile(rf'(?<![A-Za-z0-9-]){re.escape(old)}(?![A-Za-z0-9-])')
        n = len(pat.findall(new_text))
        if n:
            new_text = pat.sub(new, new_text)
        counts[old] = n
    total = sum(counts.values())
    detail = ', '.join(f'{k}→{LEGACY_PHASE[k]} ×{v}' for k, v in counts.items() if v)
    if dry_run:
        print(f'DRY-RUN  migrate: 需改写 {total} 处' + (f'（{detail}）' if detail else ''))
        return 0
    if total == 0:
        print('OK  migrate: 无需改写（旧相位名 0 处）')
        return 0
    p.write_text(new_text, encoding='utf-8')
    print(f'OK  migrate: 改写 {total} 处（{detail}）→ {p}')
    return 0


def add_blocking(work_root: Path, item: str, source: str) -> Path:
    """H15 缺口登记"""
    return _mutate_blocking(work_root, item, source, resolve=False)


def resolve_blocking(work_root: Path, item: str, note: str = '') -> Path:
    """H15 缺口解除（G4 修复 2026-10-31：此前只有 block 无 resolve——
    回填复核后阻塞无法机械清零，progress 残留清单致续跑编排者反复补检索，螺旋只进不出）。

    匹配规则：item 与已有条目**精确子串匹配**（按登记时间倒序取最新一条命中项），
    就地改写为 RESOLVED 行（保留审计痕迹，不物理删除）。
    """
    return _mutate_blocking(work_root, item, note, resolve=True)


def _mutate_blocking(work_root: Path, item: str, source: str, resolve: bool) -> Path:
    p = progress_file(work_root)
    text = p.read_text(encoding='utf-8')
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    if not resolve:
        line = f'- [{ts}] {item} (来源: {source})'
        m = re.search(r'## 阻塞清单 \(H15 缺口\)\n\n（暂无）', text)
        if m:
            text = text.replace('（暂无）', line, 1)
        else:
            m = re.search(r'(## 阻塞清单 \(H15 缺口\)\n)', text)
            if m:
                insert_at = m.end()
                tail = text[insert_at:]
                end_match = re.search(r'\n## ', tail)
                if end_match:
                    pos = insert_at + end_match.start()
                    text = text[:pos] + line + '\n' + text[pos:]
                else:
                    text += '\n' + line + '\n'
        p.write_text(text, encoding='utf-8')
        print(f'OK  blocking 登记: {item}')
        return p

    # resolve 分支：找含 item 子串的最新未解除行，追加 RESOLVED 标记
    lines = text.splitlines(keepends=True)
    hit_idx = None
    for i in range(len(lines) - 1, -1, -1):
        l = lines[i]
        if l.strip().startswith('- [') and item in l and 'RESOLVED' not in l:
            hit_idx = i
            break
    if hit_idx is None:
        print(f'ERROR  未找到可解除的阻塞项（item 子串不匹配或已 RESOLVED）: {item}',
              file=sys.stderr)
        sys.exit(2)
    lines[hit_idx] = lines[hit_idx].rstrip('\n') + f' → RESOLVED [{ts}] {source}\n'
    p.write_text(''.join(lines), encoding='utf-8')
    print(f'OK  blocking 解除: {item}')
    return p


def rejects_status(work_root: Path) -> int:
    """ADR-05 §5.2（批次 B4）：读 运行态/reject-counts.json 输出打回计数。

    计数由 `record_trace.py --reject-key "<correlation_id>|<问题指纹>"` 机械累加
    （跨 task_id 累计,禁止借改名续命）;计数 ≥2 的 key 已触发介入协议——
    本命令是编排者的可视入口,≥2 的 key 显式标注。

    #70 评审申诉通道（2026-11-01 批次 1）：`appeal|` 前缀键是申诉计数
    （判据 A2:同一指纹申诉 ≤1 次）,显示「申诉已用」标注;**不参与介入协议
    INTERVENTION 判定**（介入阈值只认无前缀打回键,两语义隔离——申诉误缠诉
    不等于质量问题打回）。
    """
    import json
    counts_file = work_root / '运行态' / 'reject-counts.json'
    if not counts_file.is_file():
        print('REJECTS=0（无打回记录）')
        print('INTERVENTION=0')
        return 0
    try:
        counts = json.loads(counts_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f'ERROR  reject-counts.json 损坏: {e}', file=sys.stderr)
        return 2
    threshold = 2  # SSOT = pipeline §介入协议「打回数 = 2」
    intervention = []
    for key in sorted(counts, key=lambda k: (-int(counts[k]), k)):
        n = int(counts[key])
        if key.startswith('appeal|'):
            # 申诉键：只显示「申诉已用」标注，不进介入判定（判据 A2）
            print(f'  {key}: {n}  ← 申诉已用（该指纹禁再申诉）')
            continue
        mark = f'  ← 介入协议已触发（≥{threshold}）' if n >= threshold else ''
        print(f'  {key}: {n}{mark}')
        if n >= threshold:
            intervention.append(key)
    print(f'REJECTS={len(counts)}')
    print(f'INTERVENTION={1 if intervention else 0}')
    return 0


def show(work_root: Path) -> int:
    p = progress_file(work_root)
    if not p.exists():
        print('(progress.md 不存在 — 章节未初始化)')
        return 1
    print(p.read_text(encoding='utf-8'))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-root', required=True)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_init = sub.add_parser('init', help='初始化 progress.md')
    p_init.add_argument('--chapter', required=True, help='如 ch06')
    p_init.add_argument('--textbook', required=True)
    p_init.add_argument('--audience', required=True)

    p_up = sub.add_parser('update', help='更新某 phase 状态')
    p_up.add_argument('--phase', required=True)
    p_up.add_argument('--status', required=True, choices=[
        'DONE', 'IN_PROGRESS', 'BLOCKED', 'BLOCKED_RESOLVED', 'SKIPPED'])
    p_up.add_argument('--summary', required=True)
    p_up.add_argument('--chapter', default='',
                      help='目标章（如 ch03）。多章工作区**必须**显式指定——'
                           '否则无法定位写入章段（此前无参调用会写进第一章段，'
                           '并行时互相覆盖）。单章工作区可省略。')

    p_blk = sub.add_parser('block', help='登记 H15 缺口')
    p_blk.add_argument('--item', required=True)
    p_blk.add_argument('--source', required=True)

    p_res = sub.add_parser('resolve', help='解除 H15 缺口（G4：回填复核后机械清零，防螺旋死锁）')
    p_res.add_argument('--item', required=True, help='登记时的 item 子串')
    p_res.add_argument('--note', default='回填复核通过', help='解除依据（如：检索已回填并复核）')

    p_mig = sub.add_parser(
        'migrate', help='把既有 progress.md 的旧相位名（VERIFY-R4/R5）改写为 PROOFREAD-R4/R5')
    p_mig.add_argument('--dry-run', action='store_true', help='只报告需改写处数，不落盘')

    # 全书层（ADR-01 批次 B5）：book 子命令组 + book-status
    p_book = sub.add_parser('book', help='全书层命令（book init）')
    sub_book = p_book.add_subparsers(dest='book_cmd', required=True)
    p_book_init = sub_book.add_parser('init', help='初始化全书（book-spec.md + Progress·全书 段）')
    p_book_init.add_argument('--textbook', required=True)
    p_book_init.add_argument('--chapters', required=True, help='逗号分隔，如 ch01,ch02,ch03')
    p_book_init.add_argument('--audience', default='', help='目标学段')
    p_book_init.add_argument('--word-budget', type=int, default=0, help='全书总字数目标（默认均分）')

    sub.add_parser('show', help='读取并打印 progress.md')
    sub.add_parser('book-status', help='输出全书进度矩阵（各章相位）')
    sub.add_parser('rejects', help='输出打回计数（ADR-05:读运行态/reject-counts.json,≥2 触发介入）')
    args = ap.parse_args()
    wr = Path(args.work_root)

    if args.cmd == 'init':
        err = validate_audience(args.audience)  # D-01: 判据 Q2 机械断言（非法值 exit 2 不落盘）
        if err:
            print(f'ERROR  {err}', file=sys.stderr)
            return 2
        init_progress(wr, args.chapter, args.textbook, args.audience)
        print('OK  progress.md initialized')
    elif args.cmd == 'book':
        if args.book_cmd == 'init':
            chapters = [c.strip() for c in args.chapters.split(',') if c.strip()]
            if not chapters:
                print('ERROR  --chapters 不能为空', file=sys.stderr)
                return 2
            err = validate_audience(args.audience)  # D-01: 同 init（空值放行走回落）
            if err:
                print(f'ERROR  {err}', file=sys.stderr)
                return 2
            init_book(wr, args.textbook, chapters, args.audience, args.word_budget)
            print('OK  book initialized')
    elif args.cmd == 'update':
        # 结构化失败出口：旧名/未知名一律 stderr + 退出码 2，不抛裸 traceback
        try:
            update_phase(wr, args.phase, args.status, args.summary,
                         chapter=args.chapter)
        except (FileNotFoundError, ValueError) as e:  # LegacyPhaseError 是 ValueError 子类
            print(f'ERROR  {e}', file=sys.stderr)
            return 2
    elif args.cmd == 'block':
        add_blocking(wr, args.item, args.source)
    elif args.cmd == 'resolve':
        resolve_blocking(wr, args.item, args.note)
    elif args.cmd == 'migrate':
        return migrate_progress(wr, dry_run=args.dry_run)
    elif args.cmd == 'show':
        return show(wr)
    elif args.cmd == 'book-status':
        return book_status(wr)
    elif args.cmd == 'rejects':
        return rejects_status(wr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
