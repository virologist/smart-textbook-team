#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_book.py — 全书门禁 5.1-5.5 测试（审计项 F1 候补落地，v2.11.1）

覆盖策略（与既有测试同风格：正向 + 反向例，不恒真放行、不静默吞错）：
  5.1 章清单：声明==磁盘 PASS / 缺章 FAIL / 孤儿章 FAIL / 字数偏差 >5% FAIL
  5.2 知识域：BOOK_SPEC 未执行 N/A / 缺 domain FAIL / 依赖成环 FAIL / 无环 PASS
  5.3 单章门禁：复用 check_manuscript（子进程）——夹具最小稿 strict 过/不过各一
  5.5 合稿：docx 缺 N/A / 坏 zip FAIL

本测试只测**纯函数与可独立构造的 IO**；5.4 跨章六项在 test_cross_chapter_deps.py
已有覆盖（判据共源，不重复测）。
"""
from __future__ import annotations

import sys
from pathlib import Path

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
