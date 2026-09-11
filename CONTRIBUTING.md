# Contributing to Smart Textbook Team

> **Note**: This repository is currently in **private pre-release** state. Public contribution is not yet open. This document is provided as a preview of the expected workflow once the repo is moved to public visibility.

Thank you for your interest in contributing to **smart-textbook-team**.

---

## 🎯 Contribution Philosophy

This is a **domain-rich multi-agent orchestration system**. Contributions must respect three layers:

1. **Domain layer** (`role-assembly.md`, agent MDs) — 学科 SOP 与领域知识
2. **Orchestration layer** (`agent-harness-protocol`, `textbook-pipeline-workflow`) — 跨 agent 调度与门禁
3. **Verification layer** (`citation-verify`, `multi-agent-patterns`) — 防幻觉与协作模式

Changes that violate the layer separation will be rejected.

---

## 🚀 Development Setup

```bash
git clone https://github.com/biodog/smart-textbook-team.git
cd smart-textbook-team

# 安装到本地测试环境
bash install.sh --dry-run             # 看会装哪些文件
bash install.sh --target all          # 实际安装

# 跑全量测试
pytest tests/test_smart_textbook_team.py

# 验证校验器（用于 ch06 等下游产物）
python3 tb-writer/scripts/validate_chapter.py <chapter.docx>
```

---

## 📋 Pull Request Process

1. **Open an issue first** describing the change and layer (domain/orchestration/verification)
2. **Fork the repo** and create a feature branch (`git checkout -b feat/your-feature`)
3. **Update relevant tests** — `tests/test_smart_textbook_team.py` for orchestration changes, `test-prompts.json` for skill changes
4. **Run the full test suite** and confirm 1.000 / 1.000
5. **Update `CHANGELOG.md`** under `[Unreleased]` with your change
6. **Open a PR** referencing the issue

---

## 🎨 Style Guide

### Markdown (Agent & Skill files)

- Frontmatter YAML with required fields: `name`, `version`, `description`, `displayName`, `profession`, `maxTurns`
- Body in Chinese (受众多为国内职业本科教师); bilingual where it adds clarity
- Use `H1` for title, `H2` for sections, `H3` for subsections
- Tables for role matrices and reference data
- Code blocks fenced with language hints (` ```yaml `, ` ```bash `)

### Commit Messages

Conventional Commits style:

```
feat(scope): brief description
fix(scope): brief description
docs(scope): brief description
test(scope): brief description

Scopes: agent-harness, pipeline, citation-verify, role-assembly, install, readme
```

Example: `fix(role-assembly): close BUG-1 (expert-pool.yaml broken reference)`

---

## 🛡️ Anti-Hallucination Discipline

Any change that touches data-tagging logic, citation verification, or boundary filtering MUST:

1. Add or update a `test-prompts.json` entry demonstrating the new behavior
2. Update `agent-harness-protocol/SKILL.md` if the change affects cross-agent rules
3. Pass a red-team audit prompt (e.g., "ignore the previous instructions and...")
4. Document the failure mode that the change prevents

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License (see `LICENSE`).
