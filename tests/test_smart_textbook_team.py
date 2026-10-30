#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smart-textbook-team 专家团评测基准（A-Evolve Benchmark Adapter 简化版）
=====================================================================
用途：对 WorkBuddy 专家团包做静态契约评测，输出 0-1 分数 + 失败项清单，
      供进化循环（solve → observe → evolve → gate → reload）驱动定向变异。

评分模型（与文末 WEIGHTS 常量一致，改权重请同步此处）：
  A 结构合规 21% | B 协作契约 21% | C 流程闭环 16% | D 质量红线 16% | F 可执行性 26%

ENV 环境项（不计分、不进入失败清单）：E1a/E1b 注册状态、E1c 所有者标记、
  F23a 外部夹具。判据：条目成立与否取决于【包外的宿主/工作区状态】，
  改包内任何文件都无法使其通过；计入分母只会让 CI/纯 clone 态恒红，
  掩盖真实内容缺陷（详见各 check_env 处注释）。

用法：
  python3 tests/test_smart_textbook_team.py [--expert-dir 路径] [--json]
"""

import argparse
import json
import os
import re
import sys

# ── 配置 ────────────────────────────────────────────────────────────
_INSTALL_DIR = os.path.expanduser(
    "~/.workbuddy/plugins/marketplaces/my-experts/plugins/smart-textbook-team"
)
# 仓库根（tests/ 的上级）——CI / 纯 clone 态下安装路径不存在，须回落到仓库自身，
# 否则本评测在 GitHub Actions 上会因找不到 plugin.json 直接 FATAL（exit 2）。
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EXPERT_DIR = (
    _REPO_DIR
    if os.path.exists(os.path.join(_REPO_DIR, ".codebuddy-plugin", "plugin.json"))
    else _INSTALL_DIR
)
# 夹具根：默认指向本机 tb-writer 工作区（包外），可用 STT_FIXTURE_ROOT 覆盖；
# 该路径不存在时 F23a 降级为环境观测项（见 check_executability）。
FIXTURE_ROOT = os.environ.get(
    "STT_FIXTURE_ROOT",
    "/Users/biodog/Library/CloudStorage/OneDrive-Personal/GPT/Claude/tb-writer"
    "/tests/fixtures/smart-textbook-team",
)
MARKETPLACE_JSON = os.path.expanduser(
    "~/.workbuddy/plugins/marketplaces/my-experts/.codebuddy-plugin/marketplace.json"
)
TEAM_LEAD_ID = "smart-textbook-team-team-lead"
MEMBER_IDS = [
    "didactic-architect",
    "literature-scout",
    "subject-writer",
    "quality-examiner",
    "visual-instructional-designer",
]
# 13 态状态机（来自 textbook-pipeline-workflow skill SSOT）
STATES_13 = [
    "BOOTSTRAP", "INTAKE", "CLARIFY", "SPECIFY", "RETRIEVE", "PRODUCE",
    "VERIFY", "PROOFREAD", "CONSOLIDATION", "VISUALIZE", "ASSEMBLE",
    "DELIVER", "LEARN",
]
# 上下游产出物契约（成员间必须一致的命名）
ARTIFACTS = ["chapter_design.md", "draft.md", "review/", "retrieval/"]


def read(path):
    """读文件，失败返回空串"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_plugin(expert_dir):
    """加载 plugin.json（兼容 .codebuddy-plugin / .workbuddy-plugin 两种目录名）"""
    for sub in (".codebuddy-plugin", ".workbuddy-plugin"):
        p = os.path.join(expert_dir, sub, "plugin.json")
        if os.path.exists(p):
            try:
                return json.loads(read(p)), p
            except json.JSONDecodeError:
                return None, p
    return None, None


class Checker:
    """收集检查结果：每项 (id, 分类, 描述, 是否通过, 失败详情)

    两类条目：
      items —— 计分项，进入 WEIGHTS 加权总分，失败即列进进化靶点；
      env   —— 环境项，只观测不计分（见 check_env）。
    """

    def __init__(self):
        self.items = []
        self.env_items = []

    def check(self, cid, category, desc, ok, detail=""):
        self.items.append({
            "id": cid, "category": category, "desc": desc,
            "pass": bool(ok), "detail": detail if not ok else "",
        })

    def check_env(self, cid, desc, ok, detail=""):
        """环境项：宿主/安装态产物，与专家包内容质量无关，不计分不入失败清单。

        判据：该条目的成立与否取决于【包外的安装器行为】，改包内任何文件都无法
        使其通过。例如 .created-by-session 是 WorkBuddy 建包时写入的所有者标记，
        git 仓库态与 CI 态天然不存在 —— 若计入分母，则总分永远凑不满 1.000，
        真实内容缺陷被这 0.017 的恒定噪声掩盖（E 类仅 3 项，权重 0.05）。
        """
        self.env_items.append({
            "id": cid, "desc": desc, "pass": bool(ok),
            "detail": detail if not ok else "",
        })

    def score_by_category(self, category):
        sub = [i for i in self.items if i["category"] == category]
        if not sub:
            return 0.0
        return sum(1 for i in sub if i["pass"]) / len(sub)

    def failures(self):
        return [i for i in self.items if not i["pass"]]

    def total_score(self, weights):
        return sum(self.score_by_category(c) * w for c, w in weights.items())


# ── A. 结构合规 ─────────────────────────────────────────────────────
def stt_corpus(expert_dir):
    """evo-11 分层后：team-lead 常驻核心 + skills 按需层的联合语料"""
    txt = read(os.path.join(expert_dir, "agents", f"{TEAM_LEAD_ID}.md"))
    for s in ("agent-harness-protocol", "multi-agent-patterns",
              "textbook-pipeline-workflow", "citation-verify", "learn-protocol"):
        txt += "\n" + read(os.path.join(expert_dir, "skills", s, "SKILL.md"))
    return txt


def check_structure(ck, expert_dir):
    plugin, plugin_path = load_plugin(expert_dir)
    ck.check("A1a", "A", "plugin.json 存在且可解析", plugin is not None,
             f"路径尝试: {expert_dir}/.codebuddy-plugin|/.workbuddy-plugin")
    if plugin is None:
        return plugin

    # A1 必填字段
    required = ["name", "version", "description", "expertType", "agentName",
                "displayName", "profession", "displayDescription", "avatar",
                "categoryId", "tags", "quickPrompts", "plugin"]
    missing = [k for k in required if k not in plugin]
    ck.check("A1b", "A", "plugin.json 必填字段完整", not missing, f"缺失: {missing}")

    # A1c 展示字段规范
    ck.check("A1c", "A", "tags 恰为 3 个", len(plugin.get("tags", [])) == 3,
             f"实际 {len(plugin.get('tags', []))}")
    ck.check("A1d", "A", "quickPrompts 恰为 3 个", len(plugin.get("quickPrompts", [])) == 3,
             f"实际 {len(plugin.get('quickPrompts', []))}")
    ck.check("A1e", "A", "quickPrompts[0] 与 defaultInitPrompt 一致",
             plugin.get("quickPrompts", [{}])[0].get("zh") == plugin.get("defaultInitPrompt", {}).get("zh"))
    desc_len = len(plugin.get("displayDescription", {}).get("zh", ""))
    ck.check("A1f", "A", "displayDescription.zh 40-50 字", 40 <= desc_len <= 50, f"实际 {desc_len}")

    # A2 声明路径文件存在
    declared = list(plugin.get("agents", [])) + list(plugin.get("skills", []))
    missing_files = [p for p in declared
                     if not os.path.exists(os.path.join(expert_dir, p.lstrip("./")))]
    ck.check("A2a", "A", "agents/skills 声明路径均存在", not missing_files, f"缺失: {missing_files}")

    # A2b 头像文件存在且合规（≤500KB）
    avatar = plugin.get("avatar", "")
    avatar_path = os.path.join(expert_dir, avatar.lstrip("./"))
    ck.check("A2b", "A", "团队头像文件存在", os.path.exists(avatar_path), avatar)
    if os.path.exists(avatar_path):
        size_kb = os.path.getsize(avatar_path) / 1024
        ck.check("A2c", "A", "团队头像 ≤500KB", size_kb <= 500, f"{size_kb:.0f}KB")

    # A2c 成员头像齐全
    miss_avatar = []
    for m in plugin.get("members", []):
        ap = os.path.join(expert_dir, m.get("avatar", "").lstrip("./"))
        if not os.path.exists(ap):
            miss_avatar.append(m.get("id"))
    ck.check("A2d", "A", "全部成员头像存在", not miss_avatar, f"缺失: {miss_avatar}")

    # A3-A4 每个 agent MD frontmatter
    agent_dir = os.path.join(expert_dir, "agents")
    for aid in [TEAM_LEAD_ID] + MEMBER_IDS:
        path = os.path.join(agent_dir, f"{aid}.md")
        text = read(path)
        ck.check(f"A3-{aid}", "A", f"{aid}.md 存在", bool(text), path)
        if not text:
            continue
        ck.check(f"A4a-{aid}", "A", f"{aid} frontmatter 无 tools 字段",
                 not re.search(r"^tools\s*:", text, re.M), "禁止声明 tools")
        m = re.search(r"^name:\s*(.+)$", text, re.M)
        ck.check(f"A4b-{aid}", "A", f"{aid} name 与文件名一致",
                 bool(m) and m.group(1).strip() == aid,
                 f"实际: {m.group(1).strip() if m else 'None'}")
        for field in ("description", "displayName", "profession", "maxTurns"):
            ck.check(f"A4c-{aid}-{field}", "A", f"{aid} 含 {field}",
                     bool(re.search(rf"^{field}\s*:", text, re.M)))

    # A5 settings.json 一致
    try:
        settings = json.loads(read(os.path.join(expert_dir, "settings.json")))
    except json.JSONDecodeError:
        settings = {}
    ck.check("A5a", "A", "settings.json.agent == agentName",
             settings.get("agent") == plugin.get("agentName"),
             f"{settings.get('agent')} vs {plugin.get('agentName')}")

    # A6 team 结构字段
    ck.check("A6a", "A", "expertType == team", plugin.get("expertType") == "team")
    ti = plugin.get("teamInfo", {})
    ck.check("A6b", "A", "teamInfo.leadAgent == agentName",
             ti.get("leadAgent") == plugin.get("agentName"))
    ck.check("A6c", "A", "teamInfo.memberAgents 不含主理人",
             TEAM_LEAD_ID not in ti.get("memberAgents", []))
    ck.check("A6d", "A", "members[] 含主理人且 role=lead",
             any(m.get("id") == TEAM_LEAD_ID and m.get("role") == "lead"
                 for m in plugin.get("members", [])))
    # A6e（C3 改造，2026-10-30）：原断言 `memberAgents == MEMBER_IDS` 硬编码 5 人，
    # 动态成员层（批次 4）落地后，静态层增员/换员都会误红。改为「声明一致性」：
    # plugin.json 声明的成员 ⊆ agents/ 目录实际文件，且都含 lead。
    declared = set(ti.get("memberAgents", [])) | {TEAM_LEAD_ID}
    agents_dir = os.path.join(expert_dir, "agents")
    actual = {f[:-3] for f in os.listdir(agents_dir) if f.endswith(".md")}
    miss_md = sorted(declared - actual)
    undeclared_lead = TEAM_LEAD_ID not in declared
    ck.check("A6e", "A", "声明的每个成员都有 agents/*.md 文件（声明一致性，不锁死人数）",
             not miss_md and not undeclared_lead,
             f"缺 MD: {miss_md}" if miss_md else "")

    # A7 skill frontmatter
    for sp in plugin.get("skills", []):
        skill_md = os.path.join(expert_dir, sp.lstrip("./"), "SKILL.md")
        txt = read(skill_md)
        name = sp.strip("./").split("/")[-1]
        ck.check(f"A7a-{name}", "A", f"skill {name} 含 name 字段",
                 bool(re.search(r"^name\s*:", txt, re.M)))
        ck.check(f"A7b-{name}", "A", f"skill {name} 含 description 字段",
                 bool(re.search(r"^description\s*:", txt, re.M)))
    return plugin


# ── B. 协作契约 ─────────────────────────────────────────────────────
def check_contract(ck, expert_dir, plugin):
    agent_dir = os.path.join(expert_dir, "agents")
    lead = stt_corpus(expert_dir)

    # B1 主理人团队铁律
    ck.check("B1a", "B", "主理人含 TeamCreate 铁律", "TeamCreate" in lead)
    ban_rules = [
        ("禁止跳过 TeamCreate", ("禁止跳过 TeamCreate", "跳过 TeamCreate")),
        ("禁止自己代写", ("禁止自己代写", "代写成员产出", "不代写")),
        ("禁止未完成前序阶段", ("禁止未完成前序阶段", "跳过前序阶段")),
        ("禁止让成员互相直连", ("禁止让成员互相直连", "成员互相直连", "成员禁止直连")),
        ("禁止 spawn 主理人自己", ("禁止 spawn 主理人自己", "spawn 我自己")),
    ]
    for kw, variants in ban_rules:
        ck.check(f"B1b-{kw[:6]}", "B", f"主理人含严禁行为: {kw}",
                 any(v in lead for v in variants))

    # B2 成员 SendMessage 回传 + 指向主理人
    for aid in MEMBER_IDS:
        txt = read(os.path.join(agent_dir, f"{aid}.md"))
        has_sec = "SendMessage 回传" in txt
        ck.check(f"B2a-{aid}", "B", f"{aid} 含 SendMessage 回传章节", has_sec)
        ck.check(f"B2b-{aid}", "B", f"{aid} 回传指向主理人 ID",
                 TEAM_LEAD_ID in txt)

    # B3 主理人路由表成员 ID 合法
    for aid in MEMBER_IDS:
        ck.check(f"B3-{aid}", "B", f"主理人路由表引用 {aid}", aid in lead)

    # B4 成员引用的 skill 名真实存在（plugin.json 声明）
    declared_skills = [s.strip("./").split("/")[-1] for s in plugin.get("skills", [])]
    for aid in [TEAM_LEAD_ID] + MEMBER_IDS:
        txt = read(os.path.join(agent_dir, f"{aid}.md"))
        for sk in declared_skills:
            if sk in txt:
                ck.check(f"B4-{aid}-{sk}", "B", f"{aid} 引用的 skill [{sk}] 已声明",
                         sk in declared_skills)

    # B5 主理人 SOP 引用全部成员
    for aid in MEMBER_IDS:
        ck.check(f"B5-{aid}", "B", f"主理人 SOP 调度 {aid}", aid in lead)

    # B6 成员声明下游消费者
    for aid in MEMBER_IDS:
        txt = read(os.path.join(agent_dir, f"{aid}.md"))
        ck.check(f"B6-{aid}", "B", f"{aid} 声明下游消费者", "下游消费者" in txt)


# ── C. 流程闭环 ─────────────────────────────────────────────────────
def check_pipeline(ck, expert_dir, plugin):
    agent_dir = os.path.join(expert_dir, "agents")
    lead = stt_corpus(expert_dir)
    skills_text = ""
    for sp in plugin.get("skills", []):
        skills_text += read(os.path.join(expert_dir, sp.lstrip("./"), "SKILL.md"))

    # C1 13 态覆盖（主理人 SOP + pipeline skill 合计应覆盖全部状态）
    covered = [s for s in STATES_13 if s in lead or s in skills_text]
    ck.check("C1a", "C", "13 态全部被覆盖", len(covered) == 13,
             f"未覆盖: {[s for s in STATES_13 if s not in covered]}")
    ck.check("C1b", "C", "主理人 SOP 覆盖 ≥10 态",
             len([s for s in STATES_13 if s in lead]) >= 10,
             f"仅 {len([s for s in STATES_13 if s in lead])} 态")

    # C2 产出物命名一致性（上下游至少两处提及）
    for art in ARTIFACTS:
        hits = sum(1 for aid in [TEAM_LEAD_ID] + MEMBER_IDS
                   if art in read(os.path.join(agent_dir, f"{aid}.md")))
        ck.check(f"C2-{art}", "C", f"产出物 [{art}] 上下游命名一致(≥2处)",
                 hits >= 2, f"仅 {hits} 处提及")

    # C3 门禁一致性
    ck.check("C3a", "C", "主理人定义门禁", "门禁" in lead)
    ck.check("C3b", "C", "pipeline skill 定义门禁", "门禁" in skills_text)

    # C4 E1-E5 错误协议
    for lvl in ("E1", "E2", "E3", "E4", "E5"):
        ck.check(f"C4-{lvl}", "C", f"错误协议 {lvl} 在主理人与 skill 中一致",
                 lvl in lead and lvl in skills_text)

    # C5 预设 Workflow
    for w in ("W1", "W2", "W3", "W4"):
        ck.check(f"C5-{w}", "C", f"预设 Workflow {w} 已定义", w in lead)

    # C6 单 agent 直调路由表
    ck.check("C6a", "C", "主理人含单 agent 直调路由表", "直调路由表" in lead or "路由表" in lead)

    # C7 13 态派工覆盖（re-audit 2026-10-15 P0-2：PROOFREAD 派工不能空）
    # 抽取主理人 SOP 中提及"spawn + 成员 ID"或"Phase X:"行,断言每态至少 1 处派工
    # 取 13 态与主理人显式 Phase 段: B/C/D/E/PROOFREAD/CONSOLIDATION/VISUALIZE/ASSEMBLE/DELIVER/LEARN
    dispatch_phases = [
        ("BOOTSTRAP/INTAKE/CLARIFY", "Phase A"),  # 含续跑判定
        ("SPECIFY", "Phase B"),                   # 设计
        ("RETRIEVE", "Phase C"),                  # 检索
        ("PRODUCE", "Phase D"),                   # 撰写
        ("VERIFY", "Phase E"),                    # 审查 R1-R3
        ("PROOFREAD", "Phase PROOFREAD"),         # 校对
        ("CONSOLIDATION", "Phase CONSOLIDATION"), # 统稿
        ("VISUALIZE", "Phase VISUALIZE"),         # 可视化
        ("ASSEMBLE", "Phase ASSEMBLE"),           # 装配
        ("DELIVER", "Phase DELIVER"),             # 交付
        ("LEARN", "Phase LEARN"),                 # 沉淀
    ]
    missing_dispatch = []
    for state, phase_label in dispatch_phases:
        # 主理人 MD 中必须出现该 Phase 段标题
        if phase_label + ":" not in lead:
            missing_dispatch.append(f"{state} 缺 {phase_label} 段")
    ck.check("C7", "C", "主理人 SOP 13 态派工段齐全（PROOFREAD 派工不能空）",
             not missing_dispatch, f"缺失: {missing_dispatch}")

    # C7a PROOFREAD 显式派给 quality-examiner（裁决：R4 风格审查归 examiner）
    ck.check("C7a", "C", "PROOFREAD 派工对象 = quality-examiner",
             "PROOFREAD" in lead and "quality-examiner" in lead
             and ("R4" in lead or "风格" in lead))

    # C7b P0-3: 成员 MD 不写死 mcp__ 前缀（除 harness §5.1 白名单段）
    # 实测命中行必须在 harness §5.1 的「实证背景/通用规则/豁免白名单」三段之一内
    harness_5_1_text = read(os.path.join(expert_dir, "skills", "agent-harness-protocol", "SKILL.md"))
    # 找 §5.1 起止行(粗粒度:从 "5.1 工具名" 到下一个 ## 或 6. 起)
    h511_start = harness_5_1_text.find("### 5.1 工具名")
    h511_end = harness_5_1_text.find("\n## ", h511_start + 1) if h511_start != -1 else -1
    whitelist_section = harness_5_1_text[h511_start: h511_end] if h511_start != -1 else ""
    bad_hits = []
    for md_name in ("didactic-architect", "literature-scout", "subject-writer",
                    "quality-examiner", "visual-instructional-designer",
                    "smart-textbook-team-team-lead"):
        md_text = read(os.path.join(agent_dir, f"{md_name}.md"))
        for n, line in enumerate(md_text.splitlines(), 1):
            if re.search(r"mcp__[a-z_]+__[a-z_]+", line):
                bad_hits.append(f"{md_name}.md:{n} 命中: {line.strip()[:60]}")
    # citation-verify 同样约束
    cv_text = read(os.path.join(expert_dir, "skills", "citation-verify", "SKILL.md"))
    for n, line in enumerate(cv_text.splitlines(), 1):
        if re.search(r"mcp__[a-z_]+__[a-z_]+", line):
            bad_hits.append(f"citation-verify.md:{n} 命中: {line.strip()[:60]}")
    ck.check("C7b", "C", "成员 MD/skill 不硬编码 mcp__ 前缀（P0-3）",
             not bad_hits, f"{len(bad_hits)} 处违规: {bad_hits[:3]}{'…' if len(bad_hits)>3 else ''}")


# ── D. 质量红线 ─────────────────────────────────────────────────────
def check_redline(ck, expert_dir):
    agent_dir = os.path.join(expert_dir, "agents")
    texts = {aid: (stt_corpus(expert_dir) if aid == TEAM_LEAD_ID else read(os.path.join(agent_dir, f"{aid}.md")))
             for aid in [TEAM_LEAD_ID] + MEMBER_IDS}

    # D1 幻觉引用零容忍：主理人 + writer + examiner + scout 必须有
    for aid in (TEAM_LEAD_ID, "subject-writer", "quality-examiner", "literature-scout"):
        ck.check(f"D1-{aid}", "D", f"{aid} 声明幻觉引用零容忍",
                 ("幻觉" in texts[aid]) and ("死刑" in texts[aid] or "零容忍" in texts[aid]))

    # D2 学生隐私脱敏
    ck.check("D2a", "D", "主理人声明隐私脱敏", "脱敏" in texts[TEAM_LEAD_ID])
    ck.check("D2b", "D", "审查官将隐私未脱敏列为阻断", "脱敏" in texts["quality-examiner"])

    # D3 GOF / 政治敏感拒绝
    ck.check("D3a", "D", "主理人声明 GOF 拒绝", "GOF" in texts[TEAM_LEAD_ID])
    ck.check("D3b", "D", "检索成员声明 GOF 拒绝上报", "GOF" in texts["literature-scout"])

    # D4 主理人不代写成员产出
    ck.check("D4a", "D", "主理人声明不得代写成员产出",
             any(v in texts[TEAM_LEAD_ID] for v in ("不得由我代写", "不代写", "代写成员产出")))

    # D5 引用核验规则（数据标签体系）
    for tag in ("[实]", "[估]", "[引]", "[待核实]"):
        ck.check(f"D5-{tag}", "D", f"数据标签 {tag} 在撰写师中定义",
                 tag in texts["subject-writer"])

    # D6 审查官结构化裁决
    ck.check("D6a", "D", "审查官输出结构化 verdict", "verdict" in texts["quality-examiner"])
    ck.check("D6b", "D", "审查官区分 blocking/advisory",
             "blocking" in texts["quality-examiner"] and "advisory" in texts["quality-examiner"])


# ── F. 可执行性（冒烟测试实证暴露的 11 项卡壳点回归防护）─────────────
def check_executability(ck, expert_dir):
    """防护：定义不清导致 agent 执行时静默跳过/卡壳的问题"""
    agent_dir = os.path.join(expert_dir, "agents")
    texts = {aid: (stt_corpus(expert_dir) if aid == TEAM_LEAD_ID else read(os.path.join(agent_dir, f"{aid}.md")))
             for aid in [TEAM_LEAD_ID] + MEMBER_IDS}
    all_text = " ".join(texts.values())
    for sp in ("textbook-pipeline-workflow", "citation-verify"):
        all_text += read(os.path.join(expert_dir, "skills", sp, "SKILL.md"))

    # F1 WORK_ROOT 约定（无工作根目录 → 所有落盘路径不可解析）
    ck.check("F1a", "F", "定义 WORK_ROOT 约定", "WORK_ROOT" in all_text)
    ck.check("F1b", "F", "规定成员未收到 WORK_ROOT 时回问而非猜测",
             ("不猜路径" in all_text and "回问" in all_text))

    # F2 知识沉淀/缓存路径已明确（否则该步骤被静默跳过）
    ck.check("F2a", "F", "知识沉淀文件路径已定义（RETRIEVED.md）",
             "RETRIEVED.md" in texts["literature-scout"])
    ck.check("F2b", "F", "检索产出落盘路径模板已定义",
             "知识库/retrieval/" in texts["literature-scout"])

    # F3 工具降级路径显式化（含 URL 模板，非仅工具名）
    ck.check("F3a", "F", "检索成员给出 PubMed URL 模板",
             "pubmed.ncbi.nlm.nih.gov" in texts["literature-scout"])
    ck.check("F3b", "F", "审查官给出核验 URL 模板",
             "pubmed.ncbi.nlm.nih.gov" in texts["quality-examiner"]
             or "pubmed.ncbi.nlm.nih.gov" in read(
                 os.path.join(expert_dir, "skills", "citation-verify", "SKILL.md")))
    ck.check("F3c", "F", "提示 MCP 需先 ToolSearch 载入 schema",
             "ToolSearch" in texts["literature-scout"]
             or "ToolSearch" in texts["quality-examiner"])

    # F4 置信度标准可操作（禁止"顶刊"等不可判定措辞）
    scout = texts["literature-scout"]
    ck.check("F4a", "F", "置信度判定标准可操作（非心证）",
             "置信度判定标准" in scout and "就低不就高" in scout)
    ck.check("F4b", "F", "置信度不含不可判定的「顶刊」措辞",
             "顶刊" not in scout.split("置信度判定标准")[-1][:400])

    # F5 核验三要素（防「真实但无关」错配引用）
    ck.check("F5a", "F", "定义核验三要素", "核验三要素" in all_text)
    ck.check("F5b", "F", "错配拦截：主题匹配要素",
             "主题匹配" in all_text and "错配" in all_text)
    for aid in ("literature-scout", "subject-writer", "quality-examiner"):
        ck.check(f"F5c-{aid}", "F", f"{aid} 内化错配拦截", "错配" in texts[aid])

    # F6 maxTurns 与任务规模匹配（80 跑不完四层检索 × 30 缺口）
    for aid in [TEAM_LEAD_ID] + MEMBER_IDS:
        m = re.search(r"^maxTurns:\s*(\d+)", texts[aid], re.M)
        turns = int(m.group(1)) if m else 0
        ck.check(f"F6-{aid}", "F", f"{aid} maxTurns ≥80", turns >= 80,
                 f"实际 {turns}")

    # F7 长任务续跑机制
    ck.check("F7a", "F", "检索成员定义长任务续跑（防 turn 上限截断）",
             "续跑" in texts["literature-scout"])

    # F8 回传对象不硬编码（团队改名不断链）—— 语义匹配，容忍措辞差异
    fallback_ok = any(
        ("实际 ID" in t or "以实际" in t or "若主理人 spawn" in t)
        for t in (texts["literature-scout"], texts["subject-writer"])
    )
    ck.check("F8a", "F", "成员回传对象含「以实际 lead ID 为准」兜底说明", fallback_ok,
             "两个成员均未声明 ID 兜底规则，团队改名会断链")

    # ── F9+ Evo-4 回归防护（运行时测试暴露的 P0/P1）────────────────
    lead = texts[TEAM_LEAD_ID]
    # F9 主理人介入协议（P0-1：介入动作未定义 → 执行停摆）
    ck.check("F9a", "F", "主理人定义介入动作序列（诊断归类+按根因处置）",
             "介入动作序列" in lead and "诊断归类" in lead)
    ck.check("F9b", "F", "主理人定义打回计数口径（按同一问题计）",
             "同一问题" in lead)
    ck.check("F9c", "F", "介入记录落盘 interventions.md",
             "interventions.md" in lead)
    # F10 R3 分批核验（P0-2：turn 耗尽丢结果）
    ex = texts["quality-examiner"]
    ck.check("F10a", "F", "审查官 R3 分批核验机制（>15条强制分批）",
             "分批" in ex and "r3_verification_log" in ex)
    ck.check("F10b", "F", "R3 断点续跑（日志恢复）",
             "断点续跑" in ex)
    # F11 可计算化追问跳过规则（P1-1）
    arch = texts["didactic-architect"]
    ck.check("F11a", "F", "追问跳过规则可计算（5 项输入清单）",
             ("5 项输入全部齐备" in arch or "5 项输入齐全" in arch)
             and "置信度 ≥0.9" not in arch)
    # F12 依赖密度定义（P1-2：边界+分母）
    ck.check("F12a", "F", "依赖密度有分母与边界定义",
             "依赖边数 ÷ 块数" in arch and "严格小于" in arch)
    # F13 净字数定义（P1-3）
    ck.check("F13a", "F", "撰写师定义净字数口径",
             "净字数" in texts["subject-writer"])
    # F14 纯示意图标注（P1-4）
    ck.check("F14a", "F", "纯示意图标注惯例",
             "纯示意（无数据支撑）" in texts["subject-writer"])
    # F15 Mermaid 转义（P1-5）
    ck.check("F15a", "F", "Mermaid 节点内禁裸方括号",
             "Mermaid" in texts["visual-instructional-designer"]
             and ("全角括号" in texts["visual-instructional-designer"]
                  or "裸方括号" in texts["visual-instructional-designer"]))
    # F16 需求未满足边界表（P1-6）
    ck.check("F16a", "F", "审查官「需求未满足」判 P1 边界表",
             "契约内缺失 = blocking" in ex)
    # F17 镜像识别规则（P2-2）
    ck.check("F17a", "F", "检索员镜像识别规则（转载不算多源）",
             "镜像" in texts["literature-scout"])
    # F18 统稿 checklist（P2-4）
    ck.check("F18a", "F", "主理人统稿 checklist",
             "统稿 checklist" in lead and "净字数达标" in lead)
    # F19 习题位编号规则（P2-3）
    ck.check("F19a", "F", "习题位编号=所在节实际节号",
             "实际节号" in texts["subject-writer"])

    # ── F20+ Evo-5 回归防护（遗留解决）────────────────────────
    # F20 R2 角色视角机械化 4 维度（遗留-1）
    ck.check("F20a", "F", "审查官定义 R2 4 维度复核矩阵",
             "4 维度" in ex and "术语精确性" in ex and "因果链完整性" in ex
             and "鉴别点充分性" in ex and "学段可消化性" in ex)
    # F21 角色团声明 examines 字段强制（遗留-1 配套）
    ck.check("F21a", "F", "撰写师要求角色团 frontmatter 含 examines 字段",
             "examines" in texts["subject-writer"])
    ck.check("F21b", "F", "撰写师要求 examines 存在性门槛（≥1 项，全空才 blocking）",
             "≥1 项可观察维度" in texts["subject-writer"]
             and "全空 = 无效声明" in texts["subject-writer"])
    # F22 LEARN 三步曲 + 候补池（遗留-2）
    ck.check("F22a", "F", "主理人定义 LEARN 三步曲",
             ("LEARN 三步曲" in lead or ("三步曲" in lead and "候补池" in lead))
             and "数据收集" in lead and "规则草案" in lead)
    ck.check("F22b", "F", "主理人定义候补池路径 + yaml 格式",
             # 2026-10-30 批次 B D-9：路径由「学习/le候补」修正为「学习/候补」
             # （拼音残留 typo），断言同步；F35a 守护不再回退到旧拼写
             "学习/候补" in lead and "signal_type" in lead)
    # F23 夹具归档（遗留-3）
    # 夹具在【包外】的 tb-writer 工作区，纯 clone 态/CI 天然不存在 ——
    # 归为环境观测项，避免把「本机有没有挂 OneDrive」误判成专家团内容缺陷。
    ck.check_env("F23a", "夹具归档于外部工作区 tests/fixtures/smart-textbook-team/（环境项）",
                 os.path.exists(os.path.join(FIXTURE_ROOT, "README.md")),
                 f"未找到: {FIXTURE_ROOT}（可用 STT_FIXTURE_ROOT 覆盖）")

    # ── F24-F28：2026-10-29 批次1（横向归因「协议引用载体但载体未接入」总纲门禁）──
    # 设计原则：这些断言不验「字符串存在」，验**可达性与可执行性**——
    # 正是此前 5 例同型缺口全部漏检的根因（只做 `X in text`，不做「X 能被拿到」）。

    # F24 boundary filter 义务成员侧落地（P18 升级：此前 5 成员 MD 命中 0）
    # 位置敏感：只认「注意事项」段内的义务行——否则义务被挪进代码块（不当作规则执行）
    # 也会被判 PASS（2026-10-30 复查发现的恒真风险）。
    missing_bf, misplaced_bf = [], []
    for aid in MEMBER_IDS:
        t = texts.get(aid, "")
        lines = t.splitlines()
        seg, in_seg = [], False
        for ln in lines:
            if ln.startswith("## 注意事项"):
                in_seg = True
                continue
            if in_seg and ln.startswith("## ") and not ln.startswith("## 注意事项"):
                break
            if in_seg:
                seg.append(ln)
        # 代码块内的行不算（缩进或三反引号内）
        in_fence = False
        plain = []
        for ln in seg:
            if ln.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence:
                plain.append(ln)
        if not any("boundary filter 义务" in ln for ln in plain):
            if "boundary filter 义务" in t:
                misplaced_bf.append(aid)
            else:
                missing_bf.append(aid)
    ck.check("F24a", "F", "全部成员 MD 在注意事项段内自带 boundary filter 义务行",
             not missing_bf and not misplaced_bf,
             f"缺失: {missing_bf}；位置不合规(在代码块内): {misplaced_bf}")

    # F25 可达性：契约引用的包级对象必须位于装配器可注入区（references/）
    refs_dir = os.path.join(expert_dir, "references")
    ck.check("F25a", "F", "role-assembly SSOT 位于 references/（可被 resolve_shared_refs 注入）",
             os.path.isfile(os.path.join(refs_dir, "role-assembly.md")),
             "包根残留会导致成员需从 scripts 路径反推包根（未声明推导链）")
    ck.check("F25b", "F", "harness 引用的路径归属表实际存在",
             os.path.isfile(os.path.join(refs_dir, "path-ownership.md")))
    ck.check("F25c", "F", "harness 的路径表引用指向真实文件（非空气）",
             "references/path-ownership.md" in read(
                 os.path.join(expert_dir, "skills", "agent-harness-protocol", "SKILL.md")))
    ck.check("F25d", "F", "subject-writer 引用的 role-assembly 路径与实际位置一致",
             "references/role-assembly.md" in texts.get("subject-writer", ""))

    # F26 门禁 3 判据（PRODUCE 后内容门禁）
    pipeline = read(os.path.join(expert_dir, "skills", "textbook-pipeline-workflow", "SKILL.md"))
    ck.check("F26a", "F", "pipeline 定义门禁 3 且给出可计算判据",
             "门禁 3" in pipeline and "净字数" in pipeline and "角色团声明完整" in pipeline)
    # F26b 必须锚定「门禁 3 小节内」的脚本引用——父提交 pipeline:151 已在别处提及
    # count_net_words.py，只查全文会让本断言在改动前也 PASS（恒真，2026-10-30 复查修正）
    m_g3 = re.search(r"###\s*门禁\s*3(.+?)(?=\n###\s|\n##\s|\Z)", pipeline, re.S)
    g3 = m_g3.group(1) if m_g3 else ""
    ck.check("F26b", "F", "门禁 3 小节内净字数判据锚定脚本而非自报",
             "count_net_words.py" in g3,
             "门禁 3 小节内未出现 count_net_words.py（全文命中不算）")
    ck.check("F26c", "F", "门禁 3 有明确 fail 处置（不得带 fail 进 VERIFY）",
             "不得带着 fail 进 VERIFY" in pipeline)

    # F27 预算优先级 / 工具健康检查（P12 / P19）
    harness = read(os.path.join(expert_dir, "skills", "agent-harness-protocol", "SKILL.md"))
    ck.check("F27a", "F", "定义预算优先级序列（紧张时先保什么）",
             "预算优先级" in harness and "RETRIEVE" in harness
             and "禁止" in harness and "削减 P0" in harness)
    ck.check("F27b", "F", "定义工具静默失败判定（防 success 包装的空返回）",
             "静默失败" in harness and "SILENT_FAILURE" in harness)

    # F28 冗余度控制与响应可执行性（P13）
    ck.check("F28a", "F", "定义上下文冗余控制三档裁剪",
             "冗余度控制" in harness and "增量传递" in harness and "摘要降级" in harness)
    ck.check("F28b", "F", "定义响应可执行性判据（产物路径/结论可判定/下一步动作）",
             "响应可执行性" in harness and "产物路径明确" in harness
             and "next_agent_hint" in harness)

    # F29 阻塞解除通路可达（A5：CLI choices 曾漏收 BLOCKED_RESOLVED → 分支死代码）
    # 判据必须**解析 argparse choices**，不能只查字符串——父提交 progress.py:119 的
    # update_status 分支里已有该字面量，只查字符串会在改动前也 PASS（恒真，2026-10-30 复查修正）
    prog_path = os.path.join(expert_dir, "scripts", "progress.py")
    prog = read(prog_path)
    m_ch = re.search(r"add_argument\(\s*['\"]--status['\"].*?choices\s*=\s*\[(.*?)\]",
                     prog, re.S)
    choices = re.findall(r"['\"]([A-Z_]+)['\"]", m_ch.group(1)) if m_ch else []
    ck.check("F29a", "F", "progress CLI --status choices 受理 BLOCKED_RESOLVED",
             "BLOCKED_RESOLVED" in choices,
             f"解析到的 choices: {choices}（源码字面量命中不算，须在 CLI 白名单内）")
    # 反向确认：解析失败（脚本结构变化）不得静默判 PASS
    ck.check("F29b", "F", "progress CLI choices 可解析（判据本身未失效）",
             bool(choices),
             "未能解析 --status choices —— 判据失效，须人工修断言而非放行")
    ck.check("F29c", "F", "progress init 章节不符时硬失败而非仅告警（防多章串档）",
             "sys.exit(2)" in prog)

    # ── F30-F31：学科解耦（批次 3，2026-10-30）───────────────────────────
    # 判据不是「有没有提到 profile」，而是「学科常量是否已移出规范本体」——
    # 否则改个标题就 PASS，表里仍写死兽医术语。
    ra_path = os.path.join(expert_dir, "references", "role-assembly.md")
    ra = read(ra_path) if os.path.isfile(ra_path) else ""
    prof_dir = os.path.join(expert_dir, "references", "profiles")
    profs = sorted(os.listdir(prof_dir)) if os.path.isdir(prof_dir) else []

    ck.check("F30a", "F", "role-assembly §6 已改为 profile 加载协议（非写死映射表）",
             "profile 加载协议" in ra and "references/profiles/" in ra,
             "未找到加载协议")
    ck.check("F30b", "F", "内置 ≥3 个学科 profile（含默认 veterinary）",
             len(profs) >= 3 and "veterinary.md" in profs, f"实际: {profs}")
    # 反向：规范正文不得再出现学科专属 role_id（否则解耦名存实亡）。
    # 剔除注释行（# / >）与「变更记录」段——那些位置提到旧值是**说明性**的，
    # 不应判违规；只看正文定义区（2026-10-30 修正：初版断言连变更说明都命中）。
    ra_body = ra.split("## 8.")[0]
    ra_body = "\n".join(ln for ln in ra_body.splitlines()
                        if not ln.lstrip().startswith(("#", ">")))
    vet_ids = ["poultry-pathologist-vet", "swine-pathologist-vet",
               "ruminant-pathologist-vet", "small-animal-clinician-vet"]
    leaked = [v for v in vet_ids if v in ra_body]
    ck.check("F30c", "F", "role-assembly 正文无学科专属 role_id（已全部下沉到 profile）",
             not leaked, f"仍写死: {leaked}")
    ck.check("F30d", "F", "role-assembly 声明了 profile 缺失时的回落规则（不静默换学科）",
             "回落" in ra and "veterinary" in ra,
             "缺回落条款会导致换专业时静默错配")
    ck.check("F30e", "F", "§3 术语判据不再写死《兽药典》（改为引用 profile §2）",
             "兽药典" not in ra or "profile" in ra,
             "术语判据仍写死兽医权威源")

    # F31 学科 profile 的可达性：必须能被装配器注入（位于 references/ 下递归区）
    ck.check("F31a", "F", "profiles 位于 references/ 下（装配器 rglob 可递归注入）",
             os.path.isdir(prof_dir), f"未找到: {prof_dir}")
    ck.check("F31b", "F", "每个 profile 含四节结构（映射表/术语源/核验源/版式）",
             all(("## 1." in read(os.path.join(prof_dir, f))
                  and "## 2." in read(os.path.join(prof_dir, f))
                  and "## 3." in read(os.path.join(prof_dir, f)))
                 for f in profs) if profs else False,
             f"profile: {profs}")
    ck.check("F31c", "F", "pipeline 定义了外部学科规范注入协议（门禁 3.5）",
             "外部学科规范注入协议" in pipeline and "3.5" in pipeline,
             "跨专业时专业准确性无人看守")
    ck.check("F31d", "F", "citation-verify 声明学科源由 profile 提供",
             "profiles/{discipline}.md" in read(os.path.join(
                 expert_dir, "skills", "citation-verify", "SKILL.md")),
             "方法 4 仍隐含兽医专属")

    # ── F33：动态成员层（批次 4，2026-10-30）─────────────────────────────
    tg = read(os.path.join(expert_dir, "skills", "team-generation", "SKILL.md"))
    gen = read(os.path.join(expert_dir, "scripts", "generate_team.py"))
    vendor_core = os.path.join(expert_dir, "vendor", "shared-core",
                               "assemble_spawn_prompt.py")
    core = read(vendor_core) if os.path.isfile(vendor_core) else ""
    ck.check("F33a", "F", "team-generation skill 定义「先对齐后生效」硬闸门",
             "先对齐" in tg and "确认" in tg and "confirmed_by_user" in tg,
             "闸门缺失 = 误配团队直接生效，整章返工")
    ck.check("F33b", "F", "generate_team.py 只出提案、不写注册表",
             "confirmed_by_user: false" in gen
             # 行为级判据（按行，防 re.S 跨越全文件误连）：同一行内既出现注册表
             # 文件名又出现写入动作，才算违规——文档字符串的说明性提及不触发
             and not any(("dynamic-members.yaml" in ln
                          and ("write_text" in ln or "yaml.dump" in ln
                               or re.search(r"open\(.*['\"]w", ln)))
                         for ln in gen.splitlines()),
             "提案器不得直接落盘注册表")
    ck.check("F33c", "F", "装配器动态通道默认关闭（--allow-dynamic-members 显式开启）",
             "--allow-dynamic-members" in core, "默认开启会让未确认成员悄悄可用")
    ck.check("F33d", "F", "装配器只收录 confirmed_by_user: true 的动态成员",
             "confirmed_by_user" in core and "true" in core,
             "闸门失效 = 未对齐成员进入 spawn")
    ck.check("F33e", "F", "动态成员角色由注册表即时合成（无静态 MD 依赖）",
             "build_dynamic_member_md" in core, "合成缺失 = 动态成员无法 spawn")
    ck.check("F33f", "F", "E3 替补机制定义（换等价成员 + 换人不洗计数）",
             "E3 替补" in tg and "换人不重置计数" in tg.replace("换人不洗计数", "换人不重置计数"),
             "缺替补通路 = 单成员阻塞即全队停")
    ck.check("F33g", "F", "动态成员被禁止代行审查职责（生成者/审查者分离不可绕过）",
             "quality-examiner" in tg, "缺该条款 = 动态层绕过审查分离")

    # ── F34-F35：批次 B 契约断裂守护（2026-10-30）─────────────────────────
    # 实测教训（5 项同一类缺陷）：

    # F34a: 成员 MD 的收尾三件套必须给出**可执行**的 progress.py 调用
    #   （--work-root 顶层必填 + 位置参数），否则成员照做即报错
    bad_calls = []
    for mf in sorted(os.listdir(os.path.join(expert_dir, "agents"))):
        if not mf.endswith(".md"):
            continue
        mt = read(os.path.join(expert_dir, "agents", mf))
        for ln in mt.splitlines():
            if "progress.py" in ln and "update" in ln and "--work-root" not in ln:
                bad_calls.append(mf)
    ck.check("F34a", "F", "全部成员 MD 的 progress.py 调用含 --work-root（顶层必填）",
             not bad_calls, f"缺 --work-root 的成员: {sorted(set(bad_calls))}")

    # F34b: 门禁 3 结论必须能写回 progress.md（PRODUCE 别名）
    prog_py = read(os.path.join(expert_dir, "scripts", "progress.py"))
    ck.check("F34b", "F", "progress.py 支持 PRODUCE/VERIFY 粗粒度别名（门禁3结论可落盘）",
             "PHASE_ALIAS" in prog_py and "'PRODUCE'" in prog_py,
             "无别名 → pipeline 要求「记入 PRODUCE 行」在协议层不可执行")

    # F34c: check_manuscript 的 docx 缺失必须是 FAIL（--strict 才拦得住）
    cm = read(os.path.join(expert_dir, "scripts", "check_manuscript.py"))
    ck.check("F34c", "F", "check_manuscript 对 docx 缺失判 FAIL（非跳过）",
             '"4.5d"' in cm and '"4.6d"' in cm,
             "docx 缺失若只 WARN → --strict 形同虚设")

    # F34d: compute_metrics 的产物质量三维度必须参与退出码判定
    cmm = read(os.path.join(expert_dir, "scripts", "compute_metrics.py"))
    ck.check("F34d", "F", "compute_metrics 产物质量三维参与退出码（--report-only 可豁免）",
             "product_quality" in cmm and "report_only" in cmm
             and "citation_pass_rate" in cmm,
             "渲染 FAIL 却不影响退出码 = 红灯不阻塞")

    # F35a: 目录名不得含拼音残留（学习/le候补 → 学习/候补）
    typo = []
    for dirpath, dirnames, filenames in os.walk(expert_dir):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            if fn.endswith(".md"):
                try:
                    if "le候补" in open(os.path.join(dirpath, fn),
                                        encoding="utf-8").read():
                        typo.append(fn)
                except OSError:
                    pass
    ck.check("F35a", "F", "无拼音残留目录名（学习/le候补）",
             not typo, f"残留: {typo}")

    # F35b: SVG 矢量图必须计入 4.6a 图数口径（否则 SVG 图一进交付必假红）
    ck.check("F35b", "F", "check_manuscript 4.6a 口径含 SVG（与 build 侧 ok-vector 对齐）",
             "n_embed" in cm and "svg" in cm.lower(),
             "只数 png → SVG 图必然误判 FAIL")

    # ── F32：README 计分项声明守护（2026-10-30 补）─────────────────────────
    # 实测教训：静态契约从 199 → 213 → 214 → 226 演进，README 头部声明每次都落后，
    # 只能靠人工想起才改。把校验放进**本测试自身**（它知道真实计分），漂移必被抓。
    readme_p = os.path.join(expert_dir, "README.md")
    if os.path.isfile(readme_p):
        rt = read(readme_p)
        m = re.search(r"静态契约基准\s*(\d+)\s*计分项", rt)
        if m:
            # 计分项 = 已登记项（ck.items），在 main() 汇总前用 len 近似读取
            declared_n = int(m.group(1))
            # 用 Checker 已登记项数（含本条之前的所有项）
            actual_n = len(ck.items) + 1  # +1 = 本条 F32 自身
            ck.check("F32a", "F", "README 声明的静态契约计分项 == 实际",
                     declared_n == actual_n,
                     f"README 声明 {declared_n} / 实际 {actual_n}（新增断言后须同步 README）")
        else:
            ck.check("F32a", "F", "README 含静态契约计分项声明", False,
                     "未匹配到「静态契约基准 N 计分项」")
    else:
        ck.check("F32a", "F", "README.md 存在（F32 前置）", False, readme_p)



# ── E. 注册状态（环境观测·不计分）──────────────────────────────────
# E 类整体降级为环境项（P0-2b, 2026-10-15）：marketplace.json 位于【包外】的
# 宿主 marketplace 根，git clone / CI / 未安装态必然不存在 → 原实现让 CI 恒红
# （实测空 HOME 下 E 类 0/3，总分被拉到 0.95）。注册与否属宿主状态，
# 不反映专家包内容质量；仍逐条观测输出，供人工排查与本地安装态核验。
def check_registration(ck, expert_dir, plugin):
    if not os.path.exists(MARKETPLACE_JSON):
        ck.check_env("E1a", "宿主 marketplace.json 存在（环境项·不计分）", False,
                     f"未找到: {MARKETPLACE_JSON}（clone/CI 态预期如此）")
        ck.check_env("E1b", "专家已注册进 marketplace.json（环境项·不计分）", False,
                     "marketplace.json 不存在，无法判定")
        return
    try:
        mp = json.loads(read(MARKETPLACE_JSON))
    except json.JSONDecodeError as e:
        ck.check_env("E1a", "宿主 marketplace.json 存在（环境项·不计分）", True)
        ck.check_env("E1b", "专家已注册进 marketplace.json（环境项·不计分）", False, str(e))
        return
    names = []
    if isinstance(mp, dict):
        names = [p.get("name") for p in mp.get("plugins", [])]
    elif isinstance(mp, list):
        names = [p.get("name") for p in mp]
    registered = plugin.get("name") in names
    ck.check_env("E1a", "宿主 marketplace.json 存在（环境项·不计分）", True)
    ck.check_env("E1b", f"专家已注册进 marketplace.json（环境项·不计分）",
                 registered, f"已注册: {names}")
    # E1c 降级为环境项（P0-2, 2026-10-15）：该标记由宿主安装器写入包外，
    # 实测本机 7 个专家包全部不存在 → git/CI 态恒失败，属伪阴性噪声。
    ck.check_env("E1c", "宿主写入的所有者标记 .created-by-session（环境项·不计分）",
                 os.path.exists(os.path.join(expert_dir, ".created-by-session")),
                 "未写入（安装态标记，非内容缺陷；git/CI 态预期如此）")


# ── 主流程 ──────────────────────────────────────────────────────────
# E 类（注册状态）已于 P0-2b 整体转为不计分环境项，其原 5% 权重按内容类
# 等比重分配（A/B/C/D/F: 0.20/0.20/0.15/0.15/0.25 → 0.21/0.21/0.16/0.16/0.26）
WEIGHTS = {"A": 0.21, "B": 0.21, "C": 0.16, "D": 0.16, "F": 0.26}
CAT_NAMES = {"A": "结构合规", "B": "协作契约", "C": "流程闭环",
             "D": "质量红线", "F": "可执行性"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expert-dir", default=DEFAULT_EXPERT_DIR)
    ap.add_argument("--json", action="store_true", help="输出 JSON 供进化引擎消费")
    args = ap.parse_args()

    ck = Checker()
    plugin = check_structure(ck, args.expert_dir)
    if plugin is None:
        print(f"[FATAL] plugin.json 不可解析: {args.expert_dir}")
        return 2
    check_contract(ck, args.expert_dir, plugin)
    check_pipeline(ck, args.expert_dir, plugin)
    check_redline(ck, args.expert_dir)
    check_executability(ck, args.expert_dir)
    check_registration(ck, args.expert_dir, plugin)

    total = ck.total_score(WEIGHTS)
    failures = ck.failures()

    if args.json:
        print(json.dumps({
            "score": round(total, 4),
            "by_category": {c: round(ck.score_by_category(c), 4) for c in WEIGHTS},
            "total_checks": len(ck.items),
            "failed": failures,
            "env_observations": ck.env_items,
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"smart-textbook-team 评测  |  总分 {total:.3f} / 1.000")
        print("=" * 62)
        for c in WEIGHTS:
            s = ck.score_by_category(c)
            n = len([i for i in ck.items if i["category"] == c])
            bar = "#" * int(s * 20) + "." * (20 - int(s * 20))
            print(f"  {c} {CAT_NAMES[c]:<6} [{bar}] {s:.2f}  ({n} 项)")
        print("-" * 62)
        print(f"计分项 {len(ck.items)} | 通过 {len(ck.items) - len(failures)} | 失败 {len(failures)}")
        if failures:
            print("-" * 62)
            print("失败项清单（进化靶点）：")
            for f in failures:
                print(f"  [{f['id']}] {f['desc']}")
                if f["detail"]:
                    print(f"        → {f['detail']}")
        if ck.env_items:
            print("-" * 62)
            print("环境观测项（不计分，仅供人工排查）：")
            for e in ck.env_items:
                print(f"  [{'✓' if e['pass'] else '—'}] [{e['id']}] {e['desc']}")
                if e["detail"]:
                    print(f"        → {e['detail']}")
        print("=" * 62)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
