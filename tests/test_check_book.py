#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_book.py — 全书门禁 5.1-5.5 测试（审计项 F1 候补落地，v2.11.1）

覆盖策略（与既有测试同风格：正向 + 反向例，不恒真放行、不静默吞错）：
  5.1 章清单：声明==磁盘 PASS / 缺章 FAIL / 孤儿章 FAIL / 字数偏差 >5% FAIL
  5.2 知识域：BOOK_SPEC 未执行 N/A / 缺 domain FAIL / 依赖成环 FAIL / 无环 PASS
  5.3 单章门禁：复用 check_manuscript（子进程）——夹具最小稿 strict 过/不过各一
  5.4 跨章七项：组装函数冒烟（含第 7 项术语依赖图接线断言，★N1 v2.11.5）
  5.5 合稿：docx 缺 N/A / 坏 zip FAIL / 图数不一致 FAIL / 字数达标 FAIL（★N1）
           / 全要素齐 PASS

本测试只测**纯函数与可独立构造的 IO**；5.4 各子函数在 test_cross_chapter_deps.py
已有覆盖（判据共源，不重复测）——此处测组装层接线（漏调第 7 项的回归由 M1 教训
驱动：文档称七项实现六项，组装层必须有断言锁住项数）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_book  # noqa: E402


# ── 夹具工厂 ──────────────────────────────────────────────────────────────

def make_spec(tmp_path: Path, chapters: list[dict], textbook: str = "测试教材",
              total: int = 20000) -> Path:
    """写 book-spec.md（与 load_book_spec 正则精确对齐的格式）。"""
    spec_dir = tmp_path / "运行态"
    spec_dir.mkdir(exist_ok=True)
    rows = "".join(
        f"- id: {c['id']}\n  word_budget: {c.get('word_budget', 10000)}\n"
        f"  difficulty: {c.get('difficulty', 'L1')}\n"
        f"  domain: {c.get('domain', '测试域')}\n"
        for c in chapters)
    p = spec_dir / "book-spec.md"
    p.write_text(
        f"textbook: {textbook}\ntotal_word_budget: {total}\n\n"
        f"## chapters\n\n{rows}", encoding="utf-8")
    return p


# ── 5.1 章清单完整 + 字数 ≤5% ─────────────────────────────────────────────

def test_5_1_all_present_passes(tmp_path):
    spec = {"textbook": "测试教材", "total_budget": 20000,
            "chapters": [{"id": "ch01"}, {"id": "ch02"}]}
    issues = check_book.check_5_1_chapter_list(spec, {"ch01": "x", "ch02": "y"})
    assert issues == [], f"两章齐备应 PASS，实得 {issues}"


def test_5_1_missing_chapter_fails(tmp_path):
    spec = {"textbook": "测试教材", "total_budget": 20000,
            "chapters": [{"id": "ch01"}, {"id": "ch02"}]}
    issues = check_book.check_5_1_chapter_list(spec, {"ch01": "x"})
    assert any(i["severity"] == "FAIL" and "ch02" in i["detail"] for i in issues), issues


def test_5_1_orphan_chapter_fails(tmp_path):
    spec = {"textbook": "测试教材", "total_budget": 20000,
            "chapters": [{"id": "ch01"}]}
    issues = check_book.check_5_1_chapter_list(spec, {"ch01": "x", "ch09": "孤儿章"})
    assert any(i["severity"] == "FAIL" and "ch09" in i["detail"] for i in issues), issues


def test_5_1_word_budget_deviation_fails(tmp_path):
    # 声明 20000、磁盘净字数总和 10000 → 偏差 50% > 5%
    spec = {"textbook": "测试教材", "total_budget": 20000,
            "chapters": [{"id": "ch01", "word_budget": 20000}]}
    issues = check_book.check_5_1_chapter_list(spec, {"ch01": "短稿"})
    assert any(i["severity"] == "FAIL" for i in issues), "50% 偏差必须 FAIL"


# ── 5.2 知识域 + 依赖无环 ────────────────────────────────────────────────

def test_5_2_unexecuted_is_na(tmp_path):
    # book-spec 存在但全部 domain 空 + 无 chapter-map → N/A（空 issues）
    make_spec(tmp_path, [{"id": "ch01", "domain": ""}])
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_2_domain_deps(spec, tmp_path)
    assert issues == [], "BOOK_SPEC 未执行应 N/A 不阻塞"


def test_5_2_missing_domain_fails(tmp_path):
    make_spec(tmp_path, [{"id": "ch01", "domain": ""}, {"id": "ch02", "domain": ""}])
    # 任一 domain 已填 → 全部必须有 domain；此处造 chapter-map 触发激活
    (tmp_path / "章节" / "_book").mkdir(parents=True)
    (tmp_path / "章节" / "_book" / "chapter-map.md").write_text(
        "| 章 | 知识域 | 成员 | 依赖章 |\n|---|---|---|---|\n"
        "| ch01 | a | w | — |\n| ch02 | b | w | ch01 |\n", encoding="utf-8")
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_2_domain_deps(spec, tmp_path)
    assert any(i["severity"] == "FAIL" for i in issues), "激活后缺 domain 必须 FAIL"


def test_5_2_dependency_cycle_fails(tmp_path):
    make_spec(tmp_path, [{"id": "ch01", "domain": "a"}, {"id": "ch02", "domain": "b"}])
    (tmp_path / "章节" / "_book").mkdir(parents=True)
    (tmp_path / "章节" / "_book" / "chapter-map.md").write_text(
        "| 章 | 知识域 | 成员 | 依赖章 |\n|---|---|---|---|\n"
        "| ch01 | a | w | ch02 |\n| ch02 | b | w | ch01 |\n", encoding="utf-8")
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_2_domain_deps(spec, tmp_path)
    assert any("环" in i["detail"] for i in issues), "ch01↔ch02 依赖环必须 FAIL"


def test_5_2_acyclic_passes(tmp_path):
    make_spec(tmp_path, [{"id": "ch01", "domain": "a"}, {"id": "ch02", "domain": "b"}])
    (tmp_path / "章节" / "_book").mkdir(parents=True)
    (tmp_path / "章节" / "_book" / "chapter-map.md").write_text(
        "| 章 | 知识域 | 成员 | 依赖章 |\n|---|---|---|---|\n"
        "| ch01 | a | w | — |\n| ch02 | b | w | ch01 |\n", encoding="utf-8")
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_2_domain_deps(spec, tmp_path)
    assert issues == [], f"无环 + 有 domain 应 PASS，实得 {issues}"


# ── 5.5 合稿（docx 缺 N/A / 坏 zip FAIL）────────────────────────────────

def test_5_5_no_docx_is_na(tmp_path):
    make_spec(tmp_path, [{"id": "ch01"}])
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_5_deliverable(tmp_path, spec, {"ch01": "x"})
    assert issues == [], "BOOK_DELIVER 未执行（无 docx）应 N/A"


def test_5_5_bad_zip_fails(tmp_path):
    make_spec(tmp_path, [{"id": "ch01"}], textbook="测试教材")
    spec = check_book.read_book_spec(tmp_path)
    (tmp_path / "交付").mkdir(exist_ok=True)
    (tmp_path / "交付" / "测试教材.docx").write_bytes("这不是 zip".encode("utf-8"))
    issues = check_book.check_5_5_deliverable(tmp_path, spec, {"ch01": "x"})
    assert any("BadZipFile" in i["detail"] or "非法" in i["detail"] for i in issues), issues


# ── CLI 烟测：book-spec 缺失 exit 2 ──────────────────────────────────────

def test_cli_missing_book_spec_exit_2(tmp_path):
    import subprocess
    pkg = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(pkg / "scripts" / "check_book.py"),
                        "--work-root", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"无 book-spec 应 exit 2，实得 {r.returncode}"


# ── 5.3 单章门禁（子进程复用 check_manuscript --strict）★N1 v2.11.5 ────────

_MIN_DRAFT_FM = ("---\n教材名: 测试教材\n章节号: {ch}\n章节标题: 测试章节\n"
                 "字数目标: {net}\n实际净字数: {net}\n版本: R1\n"
                 "学科profile: veterinary\n---\n\n")
_MIN_DRAFT_BODY = """# 第1章 测试章节

## 1.1 概述

这是本章概述内容，用于 5.3 夹具。[实]（PMID:38960123）

## 1.2 小结

本章小结内容，同样带可检索锚。[实]（PMID:38960123）

## 校稿结论

- **结论**：可交付
- **修订计数**：插入 0 处 / 删除 0 处
- **遗留待办**：无

## 参考文献

[1] 作者. 题名[J]. 刊名, 2020, 1(1): 1-2. (PMID:38960123)
"""


def _make_ch_fixture(tmp_path: Path, ch: str = "ch01", net: int = 60,
                     body: str | None = None) -> None:
    """写最小合格章夹具（与 CI 三章端到端同构的最小单章版）。"""
    d = tmp_path / "章节" / ch
    d.mkdir(parents=True, exist_ok=True)
    (d / "review").mkdir(exist_ok=True)
    (d / "review" / "r3_verification_log.md").write_text(
        "| 位置 | 标识符 | 结果 | 动作 |\n|------|--------|------|------|\n"
        "| §1.1 | PMID:38960123 | 通过 | 保留 |\n"
        "| §1.2 | PMID:38960123 | 通过 | 保留 |\n", encoding="utf-8")
    text = body if body is not None else (_MIN_DRAFT_FM.format(ch=ch, net=net)
                                          + _MIN_DRAFT_BODY)
    (d / "draft.md").write_text(text, encoding="utf-8")


def test_5_3_min_fixture_passes(tmp_path):
    """最小合格稿 assemble → strict 过 → 5.3 无 issue（判据共源链路真实可过）。

    净字数按 CI 三章端到端同款手法：先 assemble 一次实测交付 md 字数，
    回写 book-spec 预算 → 5.3 的 4.7 字数判据天然达标。
    """
    make_spec(tmp_path, [{"id": "ch01"}], total=60)
    _make_ch_fixture(tmp_path, net=60)
    r = subprocess.run([sys.executable,
                        str(Path(__file__).resolve().parent.parent / "scripts"
                              / "build_manuscript.py"),
                        "--work-root", str(tmp_path), "--chapter", "ch01",
                        "--assemble"], capture_output=True, text=True)
    assert r.returncode == 0, f"assemble 失败：{(r.stderr or r.stdout)[-200:]}"
    # 4.7 的 target = 交付 md frontmatter 的「字数目标」→ 用交付态实测净字数
    # 回写交付 md frontmatter（CI 三章端到端「按实测回写」同款手法）
    import re as _re2
    import count_net_words
    delivered = next((tmp_path / "交付").glob("*_ch01.md"))
    probe = count_net_words.count_net_words(
        delivered.read_text(encoding="utf-8"))["net_final"]
    dt = delivered.read_text(encoding="utf-8")
    delivered.write_text(_re2.sub(r"^字数目标:\s*\d+",
                                  f"字数目标: {probe}", dt, count=1, flags=_re2.M),
                         encoding="utf-8")
    issues = check_book.check_5_3_per_chapter(tmp_path, ["ch01"])
    assert issues == [], f"最小合格稿 5.3 应零 issue，实得 {issues}"


def test_5_3_broken_frontmatter_fails(tmp_path):
    """删交付 md 的 frontmatter → 5.3 必须拦（负向；操作对象与 CI 负向①一致）。"""
    import re as _re
    make_spec(tmp_path, [{"id": "ch01"}], total=60)
    _make_ch_fixture(tmp_path, net=60)
    r = subprocess.run([sys.executable,
                        str(Path(__file__).resolve().parent.parent / "scripts"
                              / "build_manuscript.py"),
                        "--work-root", str(tmp_path), "--chapter", "ch01",
                        "--assemble"], capture_output=True, text=True)
    assert r.returncode == 0, f"assemble 失败：{(r.stderr or r.stdout)[-200:]}"
    delivered = next((tmp_path / "交付").glob("*_ch01.md"))
    t = delivered.read_text(encoding="utf-8")
    delivered.write_text(_re.sub(r"\A---\s*\n.*?\n---\s*\n", "", t, flags=_re.S),
                         encoding="utf-8")
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_3_per_chapter(tmp_path, ["ch01"])
    assert any(i["severity"] == "FAIL" for i in issues), \
        f"删 frontmatter 未被 5.3 拦截：{issues}"


# ── 5.4 组装层接线（七项齐全断言，★N1——M1 漏调第 7 项的回归锁）────────────

def test_5_4_wires_seventh_check(tmp_path):
    """第 7 项（术语依赖图）必须出现在 5.4 组装输出中：未声明 exports/imports
    的章要产生 WARN——若组装层漏调该项（M1 病灶），断言立即红。"""
    make_spec(tmp_path, [{"id": "ch01"}])
    spec = check_book.read_book_spec(tmp_path)
    issues = check_book.check_5_4_cross_chapter(tmp_path, {"ch01": "# 第1章\n\n正文"})
    assert any(i["type"] == "术语依赖图" for i in issues), \
        "5.4 未触发第 7 项（术语依赖图）——组装层接线断裂（M1 病灶回归）"


def test_5_4_seventh_check_cycle_fails(tmp_path):
    """imports 成环 → 第 7 项升级 FAIL（组装层真实消费依赖闭包）。"""
    make_spec(tmp_path, [{"id": "ch01"}, {"id": "ch02"}])
    spec = check_book.read_book_spec(tmp_path)
    d1 = tmp_path / "章节" / "ch01"
    d2 = tmp_path / "章节" / "ch02"
    d1.mkdir(parents=True, exist_ok=True)
    d2.mkdir(parents=True, exist_ok=True)
    fm = ("---\n教材名: T\n章节号: {ch}\n章节标题: t\n字数目标: 1\n"
          "实际净字数: 1\n版本: R1\n学科profile: veterinary\n"
          "exports: [术语A]\nimports: [{dep}]\n---\n\n正文")
    (d1 / "draft.md").write_text(fm.format(ch="ch01", dep="术语B"), encoding="utf-8")
    (d2 / "draft.md").write_text(fm.format(ch="ch02", dep="术语A"), encoding="utf-8")
    issues = check_book.check_5_4_cross_chapter(
        tmp_path, {"ch01": (d1 / "draft.md").read_text(encoding="utf-8"),
                   "ch02": (d2 / "draft.md").read_text(encoding="utf-8")})
    dep_fail = [i for i in issues
                if i["type"] == "术语依赖图" and i["severity"] == "FAIL"]
    assert dep_fail, f"依赖成环未被第 7 项判 FAIL：{issues}"


# ── 5.5 图数一致 / 字数达标子判据（★N1——此前零测试）─────────────────────

def _make_docx(path: Path, media_count: int) -> None:
    """构造含指定数量 word/media/ 的最小合法 zip（5.5 图数判据的 IO 夹具）。"""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i in range(media_count):
            z.writestr(f"word/media/image{i + 1}.png", "png-bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())


def test_5_5_figure_count_mismatch_fails(tmp_path):
    """各章 2 个图位对 vs docx media 1 张 → 图数一致 FAIL。"""
    make_spec(tmp_path, [{"id": "ch01"}], total=60)
    spec = check_book.read_book_spec(tmp_path)
    chapters = {"ch01": "正文 图1-1 与 图1-2 两张图"}
    _make_docx(tmp_path / "交付" / "测试教材.docx", media_count=1)
    issues = check_book.check_5_5_deliverable(tmp_path, spec, chapters)
    assert any(i["type"] == "5.5 图数一致" and i["severity"] == "FAIL"
               for i in issues), f"图数不一致未被拦：{issues}"


def test_5_5_figure_count_match_passes(tmp_path):
    """图位对 == media 数 → 该子判据零 issue（正向）。"""
    make_spec(tmp_path, [{"id": "ch01"}], total=60)
    spec = check_book.read_book_spec(tmp_path)
    chapters = {"ch01": "正文 图1-1 与 图1-2 两张图"}
    _make_docx(tmp_path / "交付" / "测试教材.docx", media_count=2)
    issues = check_book.check_5_5_deliverable(tmp_path, spec, chapters)
    assert not any(i["type"] == "5.5 图数一致" for i in issues), \
        f"图数一致却报 issue：{issues}"


def test_5_5_word_budget_deviation_fails(tmp_path):
    """各章净字数和 vs total_budget 偏差 >5% → 字数达标 FAIL。"""
    make_spec(tmp_path, [{"id": "ch01"}], total=200)
    spec = check_book.read_book_spec(tmp_path)
    chapters = {"ch01": "只有六个字"}  # 净字数远小于 200
    _make_docx(tmp_path / "交付" / "测试教材.docx", media_count=0)
    issues = check_book.check_5_5_deliverable(tmp_path, spec, chapters)
    assert any(i["type"] == "5.5 字数达标" and i["severity"] == "FAIL"
               for i in issues), f"字数偏差未被拦：{issues}"


def test_5_5_all_green_passes(tmp_path):
    """docx 可开 + 图数一致 + 字数达标 → 5.5 三项全过（正向终态）。"""
    import count_net_words
    body = "正文 图1-1 " + "这是用于凑净字数的正文内容。" * 20
    net = count_net_words.count_net_words(body)["net_final"]
    make_spec(tmp_path, [{"id": "ch01"}], total=net)
    spec = check_book.read_book_spec(tmp_path)
    chapters = {"ch01": body}
    _make_docx(tmp_path / "交付" / "测试教材.docx", media_count=1)
    issues = check_book.check_5_5_deliverable(tmp_path, spec, chapters)
    assert issues == [], f"全要素齐应零 issue，实得 {issues}"
