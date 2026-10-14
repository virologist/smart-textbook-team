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
    ck.check("A6e", "A", "memberAgents 与 MEMBER_IDS 完全匹配",
             sorted(ti.get("memberAgents", [])) == sorted(MEMBER_IDS),
             f"{sorted(ti.get('memberAgents', []))}")

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
    ck.check("F21b", "F", "撰写师要求 examines ≥3 维度",
             "≥3 项可观察维度" in texts["subject-writer"])
    # F22 LEARN 三步曲 + 候补池（遗留-2）
    ck.check("F22a", "F", "主理人定义 LEARN 三步曲",
             ("LEARN 三步曲" in lead or ("三步曲" in lead and "候补池" in lead))
             and "数据收集" in lead and "规则草案" in lead)
    ck.check("F22b", "F", "主理人定义候补池路径 + yaml 格式",
             "学习/le候补" in lead and "signal_type" in lead)
    # F23 夹具归档（遗留-3）
    # 夹具在【包外】的 tb-writer 工作区，纯 clone 态/CI 天然不存在 ——
    # 归为环境观测项，避免把「本机有没有挂 OneDrive」误判成专家团内容缺陷。
    ck.check_env("F23a", "夹具归档于外部工作区 tests/fixtures/smart-textbook-team/（环境项）",
                 os.path.exists(os.path.join(FIXTURE_ROOT, "README.md")),
                 f"未找到: {FIXTURE_ROOT}（可用 STT_FIXTURE_ROOT 覆盖）")


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
