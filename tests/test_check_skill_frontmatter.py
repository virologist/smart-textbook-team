#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_check_skill_frontmatter.py — frontmatter 门禁的回归测试（2026-11-10 批次 S7）

背景
----
`scripts/check_skill_frontmatter.py` 把「Skill frontmatter 完整性 + 版本演进记录」
从软约定变成机械判据（F1 版本必填 / F2 记录节存在 / F3 版本对齐 /
F4 name 对齐 / F5 边界完整）。
门禁自身也要被守——否则它可能「判据写坏了 → 永远绿灯」，比没有门禁更糟。

本文件做两件事：
  ① 正向：真实包跑门禁必须 exit 0（不得误杀合法内容）；
  ② 负向：每条判据各注入**真实病灶形态**的破坏样本，门禁必须拦下
     （拦不下 = 该判据是假门禁）。

负向样本形态取自 2026-11-10 审计/实测到的真实病灶：
  F1a 删掉 version 行                  → 版本位静默腐化，下游全对不上
  F1b version 写成 `1.8`（非法 semver）→ 版本位格式腐化
  F2a 整个变更记录节删掉               → 10 个 skill 中 3 个的原始状态
  F2b 节名改成别名表之外的「更新日志」  → 节名漂移（门禁找不到节）
  F3a 变更记录里没有当前 version       → 实测 manuscript-delivery 的真实病灶
                                          （frontmatter v1.4.0 / 记录最新 v1.3.0）
  F3b 条目格式坏（缺 `v` 前缀）        → 有条目但形态不对，仍算对不上
  F4  name 改成别的                    → name 与目录名分离 = 平台索引键失配
  F5a 删掉 frontmatter 起始 `---`      → frontmatter 边界不完整
  F5b 删掉 description                 → 平台加载时无描述

另加 2 条守卫：
  · 不存在的 skills 目录 → 返回 error 而非崩溃
  · 门禁**只看 frontmatter + 变更记录节**，不检查正文内容
    （越界即职责重叠；正文归 check_doc_consistency 等门禁）

运行：python3 -m pytest tests/test_check_skill_frontmatter.py -v
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PKG_ROOT / "scripts" / "check_skill_frontmatter.py"

# 破坏性实验的靶子：选本批次由 S7 补齐「变更记录」节的三个 Skill
# （learn-protocol / textbook-pipeline-workflow / agent-harness-protocol）——
# 它们不受其他并行批次改动影响，破坏实验不会与他人的编辑竞争。
TARGETS = ("learn-protocol", "textbook-pipeline-workflow", "agent-harness-protocol")


# ── 工具 ────────────────────────────────────────────────────────────────


def _load_mod():
    spec = importlib.util.spec_from_file_location("check_skill_frontmatter", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_mod()


@pytest.fixture()
def sandbox_pkg():
    """把包内 skills 目录复制到临时区，供破坏性实验使用。

    不用 pytest 内置 tmp_path —— 本包运行在 OneDrive 沙箱环境下，
    pytest 的 basetemp 创建会被宿主拦截（FileExistsError），
    而 tempfile.mkdtemp 走同一挂载点却正常。已实测。
    """
    d = tempfile.mkdtemp(prefix="stt_fm_")
    try:
        src = PKG_ROOT / "skills"
        if src.is_dir():
            shutil.copytree(src, Path(d) / "skills")
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _skill_md(sandbox: Path, skill: str) -> Path:
    return Path(sandbox) / "skills" / skill / "SKILL.md"


def _skill_dirs(sandbox: Path):
    sdir = Path(sandbox) / "skills"
    return sorted(d for d in sdir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def _fail_ids(res: dict) -> set[str]:
    return {f["id"] for f in res.get("fails", [])}


def _fail_skills(res: dict) -> set[str]:
    """失败项涉及的 Skill 名集合（skill 名在独立字段，不混在 detail 里）。"""
    return {f["skill"] for f in res.get("fails", [])}


def _skill_fails(res: dict, skill: str) -> list[dict]:
    """只取某个 Skill 的失败项（避免他人并行改动污染断言）。"""
    return [f for f in res.get("fails", []) if f["skill"] == skill]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def _drop_line(text: str, pattern: str) -> str:
    """删掉第一行匹配 pattern 的行。"""
    out, hit = [], False
    for line in text.splitlines(keepends=True):
        if not hit and re.search(pattern, line):
            hit = True
            continue
        out.append(line)
    assert hit, f"未找到待删行：{pattern}"
    return "".join(out)


def _sub_line(text: str, pattern: str, repl: str) -> str:
    """替换第一行匹配 pattern 的行。"""
    out, hit = [], False
    for line in text.splitlines(keepends=True):
        if not hit and re.search(pattern, line):
            out.append(repl if repl.endswith("\n") else repl + "\n")
            hit = True
            continue
        out.append(line)
    assert hit, f"未找到待改行：{pattern}"
    return "".join(out)


# ── ① 正向 ──────────────────────────────────────────────────────────────


def test_real_package_passes():
    """真实包跑门禁必须 exit 0 —— 门禁不得误杀合法内容。"""
    res = MOD.run(PKG_ROOT)
    assert res["ok"], f"真实包应全绿，实际失败：{res.get('fails')}"
    assert res["checked"] == 10, f"应有 10 个 Skill 目录，实际 {res['checked']}"


def test_all_ten_skills_have_version():
    """10 个 Skill 必须都有 frontmatter.version（F1）。"""
    for sd in _skill_dirs(PKG_ROOT):
        res = MOD.check_skill_dir(sd)
        assert "F1" not in {f["id"] for f in res}, f"{sd.name} 未通过 F1：{res}"


def test_all_ten_skills_have_changelog_section():
    """10 个 Skill 必须都有版本演进记录节（F2）。"""
    for sd in _skill_dirs(PKG_ROOT):
        res = MOD.check_skill_dir(sd)
        assert "F2" not in {f["id"] for f in res}, f"{sd.name} 未通过 F2：{res}"


def test_version_aligned_with_changelog():
    """每个 Skill 的变更记录里必须有当前版本条目（F3）。"""
    for sd in _skill_dirs(PKG_ROOT):
        res = MOD.check_skill_dir(sd)
        assert "F3" not in {f["id"] for f in res}, f"{sd.name} 未通过 F3：{res}"


def test_gate_ignores_body_content():
    """门禁不得检查正文内容（越界即职责重叠）。

    正文随便改 → 门禁仍须全绿（本门禁只管 frontmatter + 变更记录节）。
    """
    with tempfile.TemporaryDirectory(prefix="stt_fm_body_") as d:
        sandbox = Path(d)
        shutil.copytree(PKG_ROOT / "skills", sandbox / "skills")
        p = _skill_md(sandbox, "learn-protocol")
        text = _read(p)
        # 正文注入任意内容（含看起来像标题的行，但不在变更记录节内）
        text += "\n## 随便一个标题\n\n本段正文可以随意改写，门禁不判。\n"
        _write(p, text)
        res = MOD.run(sandbox)
        assert not _skill_fails(res, "learn-protocol"), \
            f"正文改动不应触发 learn-protocol 的门禁，实际：{_skill_fails(res, 'learn-protocol')}"


# ── ② 负向：F1 版本必填 ────────────────────────────────────────────────


def test_F1a_missing_version_fails(sandbox_pkg):
    """删掉 version 行 → 必须判 F1 FAIL（版本位静默腐化）。"""
    p = _skill_md(sandbox_pkg, "learn-protocol")
    _write(p, _drop_line(_read(p), r"^version:"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F1" in {f["id"] for f in _skill_fails(res, "learn-protocol")}
    assert "learn-protocol" in _fail_skills(res)


def test_F1b_invalid_semver_version_fails(sandbox_pkg):
    """version 写成 `1.8`（非法 semver）→ 必须判 F1 FAIL。"""
    p = _skill_md(sandbox_pkg, "textbook-pipeline-workflow")
    _write(p, _sub_line(_read(p), r"^version:", "version: 1.6"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    fails = _skill_fails(res, "textbook-pipeline-workflow")
    assert "F1" in {f["id"] for f in fails}
    assert any("semver" in f["detail"] for f in fails)


# ── ② 负向：F2 记录节存在 ──────────────────────────────────────────────


def test_F2a_missing_changelog_section_fails(sandbox_pkg):
    """删掉整个变更记录节 → 必须判 F2 FAIL（审计发现的原始病灶形态）。"""
    p = _skill_md(sandbox_pkg, "textbook-pipeline-workflow")
    text = _read(p)
    idx = text.index("## 变更记录")
    _write(p, text[:idx].rstrip("\n") + "\n")
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F2" in {f["id"] for f in _skill_fails(res, "textbook-pipeline-workflow")}
    assert "textbook-pipeline-workflow" in _fail_skills(res)


def test_F2b_illegal_section_name_fails(sandbox_pkg):
    """节名改成别名表之外的「更新日志」→ 必须判 F2 FAIL（节名漂移）。"""
    p = _skill_md(sandbox_pkg, "agent-harness-protocol")
    _write(p, _sub_line(_read(p), r"^## 变更记录\s*$", "## 更新日志"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F2" in {f["id"] for f in _skill_fails(res, "agent-harness-protocol")}


def test_F2c_numbered_alias_title_is_accepted(sandbox_pkg):
    """`## 7. Changelog` 这类别名标题必须被认（防误杀既有合法写法）。"""
    p = _skill_md(sandbox_pkg, "learn-protocol")
    text = _read(p)
    idx = text.index("## 变更记录")
    text = text[:idx] + "## 7. Changelog\n" + text[idx + len("## 变更记录"):]
    _write(p, text)
    res = MOD.run(sandbox_pkg)
    assert not _skill_fails(res, "learn-protocol"), \
        f"编号前缀别名标题应被接受，实际：{_skill_fails(res, 'learn-protocol')}"


# ── ② 负向：F3 版本与记录对齐 ──────────────────────────────────────────


def test_F3a_no_entry_for_current_version_fails(sandbox_pkg):
    """变更记录里没有当前 version → 必须判 F3 FAIL。

    这是「补了节但内容与版本对不上」的防线：只判节存在会把
    实测到的 manuscript-delivery 病灶（frontmatter v1.4.0 / 记录最新 v1.3.0）放行。
    """
    p = _skill_md(sandbox_pkg, "learn-protocol")
    text = _read(p)
    cur = MOD.split_frontmatter(text.splitlines())[0]["version"]
    assert cur, "前提不成立：靶子原本应带 version"
    _write(p, _sub_line(_read(p), r"^version:", "version: 9.9.9"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    fails = _skill_fails(res, "learn-protocol")
    assert "F3" in {f["id"] for f in fails}
    assert any("9.9.9" in f["detail"] for f in fails)


def test_F3b_malformed_entry_fails(sandbox_pkg):
    """条目格式坏（缺 `v` 前缀）→ 必须判 F3 FAIL（有条目但形态不对）。"""
    p = _skill_md(sandbox_pkg, "textbook-pipeline-workflow")
    text = _read(p)
    ver = MOD.split_frontmatter(text.splitlines())[0]["version"]
    _write(p, _sub_line(_read(p), r"^- v" + re.escape(ver) + r" ", f"- {ver} "))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F3" in {f["id"] for f in _skill_fails(res, "textbook-pipeline-workflow")}


def test_F3c_bold_version_entry_is_accepted(sandbox_pkg):
    """`- **v1.6.0** [...]` 这类加粗版本号必须被认（防误杀合法写法）。"""
    p = _skill_md(sandbox_pkg, "textbook-pipeline-workflow")
    text = _read(p)
    ver = MOD.split_frontmatter(text.splitlines())[0]["version"]
    _write(p, _sub_line(_read(p), r"^- v" + re.escape(ver) + r" ",
                         f"- **v{ver}** "))
    res = MOD.run(sandbox_pkg)
    assert not _skill_fails(res, "textbook-pipeline-workflow"), \
        f"加粗版本号条目应被接受，实际：{_skill_fails(res, 'textbook-pipeline-workflow')}"


# ── ② 负向：F4 name 与目录名一致 ───────────────────────────────────────


def test_F4_wrong_name_fails(sandbox_pkg):
    """name 改成别的 → 必须判 F4 FAIL（name = 平台索引键）。"""
    p = _skill_md(sandbox_pkg, "learn-protocol")
    _write(p, _sub_line(_read(p), r"^name:", "name: learn-protocol-v2"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    fails = _skill_fails(res, "learn-protocol")
    assert "F4" in {f["id"] for f in fails}
    assert any("learn-protocol-v2" in f["detail"] for f in fails)


# ── ② 负向：F5 frontmatter 边界完整 ────────────────────────────────────


def test_F5a_missing_frontmatter_start_fails(sandbox_pkg):
    """删掉 frontmatter 起始 `---` → 必须判 F5 FAIL（边界不完整）。"""
    p = _skill_md(sandbox_pkg, "textbook-pipeline-workflow")
    text = _read(p)
    assert text.startswith("---\n")
    _write(p, text[len("---\n"):])
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F5" in {f["id"] for f in _skill_fails(res, "textbook-pipeline-workflow")}


def test_F5b_missing_description_fails(sandbox_pkg):
    """删掉 description → 必须判 F5 FAIL。"""
    p = _skill_md(sandbox_pkg, "agent-harness-protocol")
    _write(p, _drop_line(_read(p), r"^description:"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F5" in {f["id"] for f in _skill_fails(res, "agent-harness-protocol")}


# ── ② 负向：新增 Skill 未配齐 frontmatter ──────────────────────────────


def test_new_skill_without_version_fails(sandbox_pkg):
    """新增一个没有 version 的 Skill → 必须判 F1 FAIL（防止新增 Skill 漏配）。"""
    new = Path(sandbox_pkg) / "skills" / "brand-new-skill"
    new.mkdir(parents=True, exist_ok=True)
    (new / "SKILL.md").write_text(
        "---\nname: brand-new-skill\ndescription: \"占位。\"\n---\n\n占位。\n",
        encoding="utf-8")
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert "F1" in {f["id"] for f in _skill_fails(res, "brand-new-skill")}
    assert "brand-new-skill" in _fail_skills(res)


# ── ② 负向：门禁自身不可被绕过 ────────────────────────────────────────


def test_gate_reports_correct_fail_count(sandbox_pkg):
    """失败计数必须准确（防止门禁自己算错数而漏报）。"""
    p = _skill_md(sandbox_pkg, "learn-protocol")
    _write(p, _drop_line(_read(p), r"^version:"))
    q = _skill_md(sandbox_pkg, "textbook-pipeline-workflow")
    _write(q, _sub_line(_read(q), r"^name:", "name: wrong-name"))
    res = MOD.run(sandbox_pkg)
    assert not res["ok"]
    assert res["total_fails"] == len(res["fails"])
    # 计数只针对本用例注入的两个靶子 Skill（他人并行改动不影响此断言）
    assert res["by_id"].get("F1", 0) == 1
    assert res["by_id"].get("F4", 0) == 1


def test_missing_skills_dir_returns_error():
    """skills 目录不存在 → 返回 error 而非崩溃。"""
    d = tempfile.mkdtemp(prefix="stt_fm_empty_")
    try:
        res = MOD.run(Path(d))
        assert res.get("error")
        assert not res["ok"]
    finally:
        shutil.rmtree(d, ignore_errors=True)
