# tool-orchestration — 全团工具编排总表（★G5 · v2.10）

> **本文件是全团「阶段 × 工具链 × 优先级 × 单点故障替补」的唯一权威源（SSOT）**。
> 各成员 MD 不再复制降级链全文，只引用本表行号；`check_doc_consistency.py`
> 对「本表 vs 成员 MD 引用行」做一致性计分。
> 治理规则：**新增/变更工具链只改本表 + 对应成员 MD 的一行引用**——此前降级链散落
> 5 处（scout 五层 / examiner R3 / harness §5 / citation-verify 方法 1–4d /
> scientific-figure 数据四级），每处各自为政，新增工具要改 5 处。

## 0. 通用铁律（先于一切具体链路）

1. **MCP 工具前缀禁止写死**（P0-3 裁决）：首次使用任何 MCP 工具必走
   `ToolSearch 关键词现查 → DeferExecuteTool 加载 schema → 用实际返回的工具名调用`；
   查不到 → 直接落本表「兜底」列，不得假设某前缀一定存在。
2. **静默失败判定**（harness §3.2）：空返回 / results=0 / 条数差 ≥50% 无截断说明 /
   内容与主题明显无关 / 授权错误被包装为正常返回——命中任一即按失败处理，换下一层。
3. **失败必须显式留痕**：每层失败 `record_trace.py` 记 `outcome=SILENT_FAILURE`
   或 issues 声明；连续 2 个工具同主题静默失败 → 升级 E2→E3。
4. **兜底穷尽 ≠ 默认通过**：全链失败一律标 `[待核实·reason=...]`，禁止编造。

## 1. 编排总表

| 行 | 环节 | P0 优先链路 | P1 次优先 | P2 兜底 | 单点故障替补 | 消费成员 |
|---|---|---|---|---|---|---|
| L1 | 本地知识检索（Tier 0） | ima 库级 `search_knowledge_base` → 库内文档级检索 | Obsidian `$TB_VAULT_PATH`（任务包显式路径为准） | 书籍 md `{WORK_ROOT}/知识库/books/*.md` | ★std-skill（v2.10 G6 第④形态，ToolSearch 现查「教材标准/教学标准」）→ 命中作本地源锚 | literature-scout |
| L2 | 学术检索（Tier 1） | PubMed/CrossRef MCP（ToolSearch 现查） | WebFetch `pubmed.ncbi.nlm.nih.gov/{PMID}/` | WebSearch 多引擎 | Semantic Scholar → bioRxiv → 全败标 `[待核实·reason=五层检索全部失败]` | literature-scout |
| L3 | 引用核验 | esummary（元数据+PMCID）→ efetch PMC 全文 | PubMed 页面 WebFetch | CrossRef API `api.crossref.org/works/{DOI}` | 中文法规走 L4；全败标 `[待核实·reason=核验工具不可用]`，**禁默认通过** | quality-examiner |
| L4 | 法规/标准核验 | citation-verify 方法 4d 专属链（标准号+发文机关+现行版次） | WOAH / Merck 兽医手册 / 农业农村部公报 | CNKI / 万方 / 兽药典官方 | 标 `[待核实·reason=法规源不可达]` | literature-scout + quality-examiner |
| L5 | 数值触发词（门禁 3.1 / 跨章指标） | profile §7 `number_triggers`（ADR-02 下沉） | 通用数值正则（`数字+单位`）兜底 | — | profile 缺失 → 回落默认 + issues 显式声明回落，**禁静默** | assemble_sections / check_cross_chapter |
| L6 | 绘图数据来源 | 正文 `[实]` 数据（图文同源） | 检索摘要 `知识库/retrieval/*.md` | 权威机构原始数据（WOAH/统计局，注出处+访问日期） | 推导/模拟数据必须标「示意数据（基于 XX 假设推导）」，**禁把示意画成实测样式** | visual-instructional-designer |
| L7 | 绘图执行 | notebook 内联数据 + conda bio 环境 | 系统 python3 + matplotlib | jupyter 不可用 → 降级导出 .py + issues 声明「notebook 未执行，产物待补」 | `check_manuscript --exec-notebooks` 失败 → 4.10e FAIL 不交付 | visual-instructional-designer |
| L8 | 文献级定位（R7 深核） | efetch 全文 XML（切 ref-list） | 摘要级 `rettype=abstract` | 题录级（EuropePMC/出版商页） | 摘要级文献的数值结论标注「摘要级（数值不能由摘要单独确证）」 | quality-examiner（R3/R7） |

## 2. 预算削减优先级（引用 harness §3.1，此处只放锚）

预算紧张时的保障顺序 **P0 RETRIEVE → P1 PRODUCE → P2 VERIFY R1/R3 → P3 VISUALIZE → P4 PROOFREAD R4**，
细则与削减动作 SSOT = `skills/agent-harness-protocol/SKILL.md` §3.1，本表不复制。

## 3. 一致性计分（check_doc_consistency 增项）

| 计分项 | 判据 |
|---|---|
| C-TOOL-1 | 本表 L1–L8 行存在且每行 7 列齐全 |
| C-TOOL-2 | `agents/literature-scout.md` 含「编排总表 L1/L2/L4」引用行且不含与本表冲突的五层顺序 |
| C-TOOL-3 | `agents/quality-examiner.md` 含「编排总表 L3/L8」引用行 |
| C-TOOL-4 | 本表与 harness §5 降级链描述一致（PubMed→PubMed页→CrossRef→WebSearch→待核实） |

## 4. Changelog

- v1.0.0 [2026-11-05] 初版（★G5 v2.10）：8 行编排总表 + 通用铁律 4 条 + 一致性计分 4 项；
  各成员 MD 的复制段自此改为引用本表行号
