# skill-mounting.md — 自定义/标准类 skill 挂载规范（v2.11.0 ★E1/E3/F3，2026-11-08）

> 立项依据：第六轮架构审计审计项 E（可插拔性）与 F（出版社交付挂载点）。
> 目标：让用户依据**某教材标准 / 出版社规范 / 课程标准**制作的「判据 skill」
> 能挂进本团队使用，且不与包内 10 个 skill 冲突、卸载无残留、永不越权当内容源。

## 1. 铁律（继承 B7，不可被挂载绕过）

1. 外部 skill **只作判据**（对照检查的尺子），**不作内容来源**——判据与内容源分离
   与「生成者/审查者分离」同级，任何挂载配置不得违反。
2. 判据冲突优先级（从高到低）：**profile §判定 > 用户文档（`学科标准/*.md`）>
   profile-overrides > 外部判据 skill > 包内默认**。外部 skill 永远排最后一级。
3. 挂载不改变 SSOT 归属：外部 skill 产物只落 `学科标准/external/`，
   禁写 `章节/`、`交付/`、`运行态/`（越界 = 拒收，同契约三原则②）。

## 2. 目录约定（平台机制对齐）

```
{WORK_ROOT}/学科标准/
├── external-skills.yaml          # 挂载清单（唯一登记处，主理人装配时读取）
└── external/                     # 外部 skill 本体目录（每 skill 一子目录）
    └── {namespace}-{skill-name}/
        ├── SKILL.md              # frontmatter 必填项见 §3
        └── （判据附表等资产文件）
```

- 平台对齐说明：WorkBuddy 用户级 skill 目录（`$HOME` 下 `.workbuddy/skills/`，
  即用户主目录的点目录）与项目级（`{workspace}/.workbuddy/skills/`）是**平台侧**
  挂载点；本规范管的是**团队侧**判据 skill 的登记与消费。两者并存：平台 skill
  由装配器按平台机制注入任务包；团队侧判据 skill 经本规范登记后被
  examiner/designer 按需读取。
  【已核验 2026-11-08】平台依赖声明机制 = plugin.json `dependencies.mcpServers`/
  `dependencies.connectors`，或插件根目录 `.mcp.json` 兜底（未声明时自动读取；
  每个server 可附 `x-workbuddy` 展示与鉴权元信息）；简单专家无需声明——来源：
  开放平台官方文档 open.workbuddy.cn/docs/expert「内置 MCP 与连接器依赖（可选）」。
  本包判据 skill 走本规范登记，不依赖该机制。

## 3. SKILL.md frontmatter 必填项（缺一 = 挂载校验 FAIL）

```yaml
---
name: {namespace}-{skill-name}     # 必须带 namespace 前缀（§4）
version: x.y.z                     # semver
discipline: {学科或 all}            # 目标学科；all = 通用判据
purpose: 判据                       # 只允许「判据」——内容源类 skill 拒绝挂载
criteria_refs:                      # 判据条目指针（供 examiner 定位核对段）
  - §1 交稿格式
  - §2 图表规范
source: {出版社名/标准号/自研}       # 来源声明（可溯源）
---
```

## 4. 命名隔离与冲突检测

- 外部 skill 名**必须**带 namespace 前缀（`{namespace}-{skill-name}`，
  namespace = 出版社缩写/机构缩写/用户自定义 ≥2 字符），与包内 10 skill
  （agent-harness-protocol / book-orchestration / citation-verify / learn-protocol /
  manuscript-delivery / multi-agent-patterns / scientific-figure / task-router /
  team-generation / textbook-pipeline-workflow）天然不重名。
- 机械检测：`scripts/check_external_skills.py` 逐条校验清单与目录——
  ① 重名（含与包内 skill 撞名）→ FAIL；② frontmatter 必填项缺失 → FAIL；
  ③ 清单登记了但目录缺失（或反之）→ FAIL（卸载残留检测）；
  ④ purpose ≠ 判据 → FAIL（铁律 §1.1）。
- 触发词冲突：外部 skill 不注册全局触发词（不经 task-router 路由），
  仅由主理人在审校/交付派工时按清单**显式引用**——零路由冲突面。

## 5. 消费路径（与 B7 三级的关系）

| 场景 | 走法 |
|---|---|
| 用户只有标准**文档** | 走既有 B7：`{WORK_ROOT}/学科标准/*.md`（不变） |
| 用户有标准**skill**（结构化判据） | 本规范：登记进 external-skills.yaml → 主理人在 VERIFY/BOOK_DELIVER 派工时把 skill 路径写进任务包 → examiner/designer 读它对照 |

冲突裁决按 §1.2 优先级；外部 skill 与 B7 文档同时存在且判据冲突时，
**以 B7 文档为准**并在审查报告 blocking 备注「外部判据 skill 条目 X 与用户文档冲突，按用户文档执行」。

## 6. 卸载无残留判据

删目录后跑 `check_external_skills.py`：清单条目与目录**双向一致**——
目录在清单不在 = 挂载登记残留（FAIL）；清单在目录不在 = 卸载残留（FAIL）。
两种残留都给出精确条目名与修复动作（删清单行 / 补目录）。

## 7. 隐性依赖附表（审计项 E4 实测清单，2026-11-08）

包内未声明 `.mcp.json` / `dependencies`（实测包根与市场根均无）。以下为
成员协议引用的**环境隐性依赖**（挂载环境须具备，否则按各自行内降级链）：

| 依赖 | 引用位置 | 降级行为 | 标注 |
|------|---------|---------|------|
| WebFetch | examiner / scout / citation-verify | 降 CrossRef / `[待核实]` | 实 |
| ToolSearch + DeferExecuteTool | 同上（MCP 前缀探测） | 降 WebFetch PubMed | 实 |
| ima 知识库 | team-lead / writer / scout | 降 Obsidian → 书籍 md → 外网 | 实 |
| Obsidian `$TB_VAULT_PATH` | scout / citation-verify | 降书籍 md / 外网 | 实 |
| markitdown | scout（书籍 PDF→md） | 书籍 md 不可用时降外网 | 实 |
| python3 + pytest | 全部 scripts + CI | 硬依赖（无降级） | 实 |
