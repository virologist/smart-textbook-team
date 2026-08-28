---
name: citation-verify
description: "Zero-tolerance citation verification for textbook writing: verify every PMID/DOI in draft text against PubMed/CrossRef, delete nonexistent references, flag mismatches, and mark unverifiable claims. Load when reviewing drafts (VERIFY R3) or whenever a citation's authenticity is in doubt."
version: 1.0.0
---

# citation-verify — 引用核验（零容忍防幻觉）

> 转换自 content-forge v5 `skills/knowledge/citation-verify`。教材红线：幻觉引用 = 死刑。

## 何时使用

- VERIFY R3 数据+引用核验轮（quality-examiner 必调）
- 任何时点对草稿中 PMID/DOI 真实性存疑
- 写作中 literature-scout 返回结果的自检

## 核验规则（零容忍）

1. 无 PMID 的引用 → 标注 `[待核实 PMID]`
2. PMID 在 PubMed 查无此文 → **立即删除该引用**，相关数据降级为 `[待核实]`
3. DOI 在 CrossRef 查无 → **立即删除该引用**
4. PMID/DOI 存在但作者/年份/结论不符 → 标注 `[待核实·reason=内容不符]` 并列差异

## 执行方法（按优先级降级）

### 方法 1：PubMed MCP 工具（如有）
```
mcp__PubMed__get_article_metadata / lookup_article_by_citation → 逐条比对
```

### 方法 2：PubMed 网页核验（无 MCP 时）
```
WebFetch https://pubmed.ncbi.nlm.nih.gov/?term={PMID}
→ 确认标题/作者/年份与草稿引用一致
```

### 方法 3：CrossRef API（DOI 核验）
```
WebFetch https://api.crossref.org/works/{DOI}
→ 确认 DOI 真实性与元数据一致
```

### 方法 4：全部失败
标注 `[待核实·reason=核验工具不可用]`，**不得默认通过**。

## 输出格式

逐条核验记录表：

```
| 引用位置 | 标识符 | 核验结果 | 动作 |
|---------|--------|---------|------|
| §2.1 行14 | PMID:38960123 | 通过（标题/作者/年份一致） | 保留 |
| §3.2 行8 | PMID:12345678 | 查无此文 | 删除引用+数据降级[待核实] |
| §4.1 表2 | DOI:10.xxxx/yyy | 作者不符 | 标注[待核实·reason=作者不符] |
```

汇总统计：`核验 N 条 | 通过 N | 删除 N | 标注待核实 N`——该统计进入交付时质量报告。

## 注意事项

- 中文文献（CNKI）无 PMID：核验标准引文格式（作者/期刊/年/卷期页）可检索到即可，标 `[实·CNKI]`
- 权威机构数据（WOAH/Merck/兽药典）：核验 URL 可访问且数据一致，标 `[实·机构]`
- 绝不因「看起来合理」而免检；逐条核验，无一例外
- 消费者：quality-examiner（R3 报告）、主理人（交付质量报告）
