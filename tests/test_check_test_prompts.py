#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_check_test_prompts.py — test-prompts 门禁的回归测试（2026-11-10 批次 S1）

背景
----
`scripts/check_test_prompts.py` 把「Skill 契约评测用例集」从软约定变成机械判据
（T1 存在性 / T2 结构 / T3 条数 / T4 字段 / T5 引用真实性）。
门禁自身也要被守——否则它可能「判据写坏了 → 永远绿灯」，比没有门禁更糟。

本文件做两件事：
  ① 正向：真实包跑门禁必须 exit 0（不得误杀合法内容）；
  ② 负向：每条判据各注入**真实病灶形态**的破坏样本，门禁必须拦下
     （拦不下 = 该判据是假门禁）。

负向样本形态取自 2026-11-10 审计实测到的真实病灶：
  T1 删掉整个 test-prompts.json          → 审计发现的 6 个 Skill 的原始状态
  T2a skill 字段写成目录名之外的值      → skill 名写错，用例与 Skill 对不上
  T2b 顶层塞入额外键                    → 结构漂移，下游解析器读不到
  T3 只留 1 条用例                      → 覆盖不了三型场景
  T4a id 跳号/重复                      → 用例编号不稳定
  T4b expected 为空串                   → 空契约
  T5  expected 引用不存在的命令          → 假门禁：逼 Skill 满足不存在的机制

运行：python3 -m pytest tests/test_check_test_prompts.py -v
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PKG_ROOT / "scripts" / "check_test_prompts.py"


# ── 工具 ────────────────────────────────────────────────────────────────


def _load_mod():
    spec = importlib.util.spec_from_file_location("check_test_prompts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_mod()


@pytest.fixture()
def sandbox_pkg():
    """把包内相关目录复制到临时区，供破坏性实验使用。

    不用 pytest 内置 tmp_path —— 本包运行在 OneDrive 沙箱环境下，
    pytest 的 basetemp 创建会被宿主拦截（FileExistsError），
    而 tempfile.mkdtemp 走同一挂载点却正常。已实测。
    """
    d = tempfile.mkdtemp(prefix="stt_tp_")
    try:
        for sub in ("skills", "references", "scripts", "agents"):
            src = PKG_ROOT / sub
            if src.is_dir():
                shutil.copytree(src, Path(d) / sub)
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _tp(sandbox: Path, skill: str) -> Path:
    return Path(sandbox) / "skills" / skill / "test-prompts.json"


def _skill_dirs(sandbox: Path):
    sdir = Path(sandbox) / "skills"
    return sorted(d for d in sdir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def _fail_ids(res: dict) -> set[str]:
    return {f["id"] for f in res.get("fails", [])}


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ── ① 正向 ──────────────────────────────────────────────────────────────


def test_real_package_passes():
    """真实包跑门禁必须 exit 0 —— 门禁不得误杀合法内容。"""
    res = MOD.run(PKG_ROOT)
    assert res["ok"], f"真实包应全绿，实际失败：{res.get('fails')}"
    assert res["checked"] == 10, f"应有 10 个 Skill 目录，实际 {res['checked']}"


def test_all_ten_skills_have_test_prompts():
    """10 个 Skill 必须都有用例集（S1 的核心目标）。"""
    for sd in _skill_dirs(PKG_ROOT):
        assert (sd / "test-prompts.json").is_file(), f"{sd.name} 缺 test-prompts.json"


def test_each_file_has_three_prompts():
    """每个用例集至少 3 条（正常/异常/边界三型）。"""
    for sd in _skill_dirs(PKG_ROOT):
        data = json.loads((sd / "test-prompts.json").read_text(encoding="utf-8"))
        assert len(data["prompts"]) >= 3, f"{sd.name} 仅 {len(data['prompts'])} 条"


# ── ② 负向：T1 存在性 ──────────────────────────────────────────────────


def test_T1_missing_file_fails(sandbox_pkg):
    """删掉用例文件 → 必须判 T1 FAIL（审计发现的原始病灶形态）。"""
    p = _tp(sandbox_pkg, "book-orchestration")
    p.unlink()
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T1" in _fail_ids(res)
    assert any("book-orchestration" in f["detail"] for f in res["fails"])


# ── ② 负向：T2 结构 ────────────────────────────────────────────────────


def test_T2a_wrong_skill_name_fails(sandbox_pkg):
    """skill 字段写成别的名字 → 必须判 T2 FAIL。"""
    p = _tp(sandbox_pkg, "learn-protocol")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["skill"] = "learn-protocol-v2"
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T2" in _fail_ids(res)


def test_T2b_extra_top_level_key_fails(sandbox_pkg):
    """顶层塞入额外键 → 必须判 T2 FAIL（结构漂移）。"""
    p = _tp(sandbox_pkg, "task-router")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["metadata"] = {"author": "x"}
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T2" in _fail_ids(res)


def test_T2c_broken_json_fails(sandbox_pkg):
    """JSON 语法坏掉 → 必须判 T2 FAIL 而不是抛异常崩掉。"""
    p = _tp(sandbox_pkg, "team-generation")
    p.write_text('{"skill": "team-generation", "prompts": [', encoding="utf-8")
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T2" in _fail_ids(res)


# ── ② 负向：T3 条数 ────────────────────────────────────────────────────


def test_T3_too_few_prompts_fails(sandbox_pkg):
    """只留 1 条用例 → 必须判 T3 FAIL。"""
    p = _tp(sandbox_pkg, "scientific-figure")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"] = data["prompts"][:1]
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T3" in _fail_ids(res)


# ── ② 负向：T4 字段 ────────────────────────────────────────────────────


def test_T4a_duplicate_and_skipped_ids_fail(sandbox_pkg):
    """id 重复 + 跳号 → 必须判 T4 FAIL。"""
    p = _tp(sandbox_pkg, "manuscript-delivery")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][1]["id"] = 1          # 与第 1 条重复
    data["prompts"][2]["id"] = 9          # 跳号
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T4" in _fail_ids(res)


def test_T4b_empty_expected_fails(sandbox_pkg):
    """expected 为空串 → 必须判 T4 FAIL（空契约）。"""
    p = _tp(sandbox_pkg, "book-orchestration")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][0]["expected"] = "   "
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T4" in _fail_ids(res)


def test_T4c_missing_field_fails(sandbox_pkg):
    """某条用例缺 expected 字段 → 必须判 T4 FAIL。"""
    p = _tp(sandbox_pkg, "citation-verify")
    data = json.loads(p.read_text(encoding="utf-8"))
    del data["prompts"][2]["expected"]
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T4" in _fail_ids(res)


# ── ② 负向：T5 引用真实性（本门禁最关键的一条）────────────────────────


def test_T5_fabricated_reference_fails(sandbox_pkg):
    """expected 引用不存在的命令 → 必须判 T5 FAIL。

    这是「假门禁」的核心防线：用例本身写错却逼 Skill 去满足不存在的机制，
    比缺用例更坏。
    """
    p = _tp(sandbox_pkg, "multi-agent-patterns")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][0]["expected"] = "先跑 check_nonexistent_gate.py --strict 再派活"
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T5" in _fail_ids(res)
    assert any("check_nonexistent_gate.py" in f["detail"] for f in res["fails"])


def test_T5_fabricated_gate_code_fails(sandbox_pkg):
    """expected 编造门禁编号 → 必须判 T5 FAIL。"""
    p = _tp(sandbox_pkg, "agent-harness-protocol")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][0]["expected"] = "按协议：门禁 9.99 不通过时升级"
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T5" in _fail_ids(res)


def test_T5_substring_of_real_filename_fails(sandbox_pkg):
    """★逃逸防线：假名是真实文件名的**子串**时也必须判 FAIL（2026-11-10 实测）。

    病史：T5 首版用「整池字符串 + 子串包含」判定 ⇒ `check_foo.py` 是
    `check_doc_consistency.py` 的子串 ⇒ 假名被判「存在」⇒ **假阴性逃逸**。
    修复：标识符改为**精确集合匹配**（文件名查文件系统，其余查 token 集合）。

    ★假名纪律（2026-11-10 二次实测教训）：假名必须**动态生成**并与全包字符串
    保证不相交——病历文档（CHANGELOG 等）只要提到某个固定假名，该假名就会
    进入证据池变成「真实 token」，反向例即失效（观测者效应，首版反向例实测踩中）。
    """
    fake = "check_zz" + uuid.uuid4().hex[:12] + "_probe.py"
    assert fake[: -len("_probe.py")] + "_probe.py" == fake
    # 自校验：假名与包内证据池不相交（防止本测试自身退化成假门禁）
    file_names, tokens = MOD.build_pool(sandbox_pkg)
    assert fake not in file_names and fake not in tokens, "假名意外与包内字符串相交"

    p = _tp(sandbox_pkg, "multi-agent-patterns")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][0]["expected"] = f"先跑 {fake} --strict 再派活"
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"], "子串假名未被拦截 —— T5 又退回了子串匹配"
    assert "T5" in _fail_ids(res)
    assert any(fake in f["detail"] for f in res["fails"])


def test_T5_gate_self_file_excluded_from_evidence_pool(sandbox_pkg):
    """★逃逸防线二：门禁**自身文件**不得成为证据池（机制级验证）。

    病史：门禁 docstring 写着「如 `check_foo.py`」这类反例示例名，曾被抽成
    token 放进证据池 ⇒ 用例里写该假名反而「查得到」⇒ 假阴性逃逸。
    修复：GATE_SELF_NAME 文件不参与 token 抽取。

    ★本测试为何不用固定名直接断言（2026-11-10 三次实测教训——观测者效应）：
    固定假名只要被写进任何**合法病历文档**（CHANGELOG / SKILL_CHANGELOG——
    记录病历是文档的正常职责，不能为此把它们排除出池），该假名就会重新变成
    「真实 token」，基于固定名的断言随机失效。
    因此测试流程为：沙箱内清除携带假名的病历文档 → 使「假名唯一出处 = 门禁
    自身」严格成立 → 再断言门禁排除机制 + 端到端拦截。
    """
    gate_src = (PKG_ROOT / "scripts" / "check_test_prompts.py").read_text(encoding="utf-8")
    m = re.search(r"如 `([A-Za-z0-9_\-]+\.py)`", gate_src)
    assert m, "门禁 docstring 反例名形态变更，本测试需同步更新"
    docstring_fake = m.group(1)

    # ① 沙箱内清除携带假名的病历文档（使前提严格成立）
    for cand in (Path(sandbox_pkg) / "skills" / "SKILL_CHANGELOG.md",
                 Path(sandbox_pkg) / "CHANGELOG.md"):
        if cand.exists():
            t = cand.read_text(encoding="utf-8")
            if docstring_fake in t:
                cand.unlink()

    # ② 机制断言：现在「假名唯一出处 = 门禁自身」，它不得出现在 token 池
    file_names, tokens = MOD.build_pool(sandbox_pkg)
    assert docstring_fake not in file_names, "假名已是真实文件名，测试前提失效"
    assert docstring_fake in gate_src, "前提失效：门禁文本里已无该反例名"
    assert docstring_fake not in tokens, (
        "门禁自身文本进入了证据池 —— GATE_SELF_NAME 排除机制失效")

    # ③ 端到端：唯一证据来源是门禁自身的假名，写进用例必须被判 FAIL
    p = _tp(sandbox_pkg, "task-router")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][0]["expected"] = f"先跑 {docstring_fake} --strict 再派活"
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"], "门禁自身 docstring 的反例名成了证据 —— 自证逃逸未修"
    assert "T5" in _fail_ids(res)


def test_T5_real_command_still_passes(sandbox_pkg):
    """正向对照：真实存在的命令名**不得**被误杀（防过度拦截）。"""
    p = _tp(sandbox_pkg, "citation-verify")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["prompts"][0]["expected"] = "跑 scripts/verify_citations_r7.py 核验，再出表"
    _write(p, data)
    res = MOD.run(sandbox_pkg)
    assert res["ok"], f"真实命令被误杀：{res.get('fails')}"


# ── ② 负向：新增 Skill 未提供用例集 ────────────────────────────────────


def test_new_skill_without_prompts_fails(sandbox_pkg):
    """新增一个没有用例集的 Skill → 必须判 T1 FAIL（防止新增 Skill 漏配）。"""
    new = Path(sandbox_pkg) / "skills" / "brand-new-skill"
    new.mkdir(parents=True, exist_ok=True)
    (new / "SKILL.md").write_text("---\nname: brand-new-skill\n---\n\n占位。\n", encoding="utf-8")
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "T1" in _fail_ids(res)
    assert any("brand-new-skill" in f["detail"] for f in res["fails"])


# ── ② 负向：豁免机制护栏（2026-11-10 批次 D-2）─────────────────────────


def test_exempt_skill_with_valid_reason_passes(sandbox_pkg, monkeypatch):
    """合法豁免：删除某 skill 的用例文件 + 登记有效豁免 → 门禁绿（豁免生效）。"""
    p = _tp(sandbox_pkg, "book-orchestration")
    p.unlink()
    monkeypatch.setitem(MOD.EXEMPT_SKILLS, "book-orchestration",
                        "测试用：纯参考型 skill，无可评测的 prompt 契约")
    res = MOD.run(sandbox_pkg)
    assert res["ok"], f"合法豁免未生效：{res.get('fails')}"
    assert "book-orchestration" in res.get("exemptions", [])


def test_exempt_for_nonexistent_skill_fails(sandbox_pkg, monkeypatch):
    """护栏①：为包内不存在的 skill 登记豁免 → 必须判 FAIL（禁预留占位）。"""
    monkeypatch.setitem(MOD.EXEMPT_SKILLS, "ghost-skill", "不存在的 skill 的豁免占位")
    res = MOD.run(sandbox_pkg)
    assert not res["ok"], "为不存在的 skill 预留豁免未被拦 —— 护栏①失效"
    assert any("ghost-skill" in f["detail"] and "不存在" in f["detail"] for f in res["fails"])


def test_exempt_with_empty_reason_fails(sandbox_pkg, monkeypatch):
    """护栏②：豁免理由为空串 → 豁免不生效，该 skill 照常判 T1 FAIL。"""
    p = _tp(sandbox_pkg, "learn-protocol")
    p.unlink()
    monkeypatch.setitem(MOD.EXEMPT_SKILLS, "learn-protocol", "   ")
    res = MOD.run(sandbox_pkg)
    assert not res["ok"], "空理由豁免生效了 —— 护栏②失效"
    assert any("豁免理由为空" in f["detail"] for f in res["fails"])


# ── ② 负向：门禁自身不可被绕过 ────────────────────────────────────────


def test_gate_reports_correct_fail_count(sandbox_pkg):
    """失败计数必须准确（防止门禁自己算错数而漏报）。"""
    p = _tp(sandbox_pkg, "book-orchestration")
    p.unlink()
    q = _tp(sandbox_pkg, "task-router")
    data = json.loads(q.read_text(encoding="utf-8"))
    data["prompts"] = data["prompts"][:1]
    _write(q, data)
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert res["total_fails"] == len(res["fails"])
    assert res["total_fails"] >= 2
    assert res["by_id"].get("T1", 0) == 1
    assert res["by_id"].get("T3", 0) == 1


def test_missing_skills_dir_returns_error():
    """skills 目录不存在 → 返回 error 而非崩溃。"""
    d = tempfile.mkdtemp(prefix="stt_tp_empty_")
    try:
        res = MOD.run(Path(d))
        assert res.get("error")
        assert not res["ok"]
    finally:
        shutil.rmtree(d, ignore_errors=True)
