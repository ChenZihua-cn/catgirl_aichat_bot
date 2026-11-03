# 最终全量审查（任务 #11）

触发：Merge/构建完成后、交付前，`train.jsonl` 冻结。结构校验只能做前置，不能替代本审查。

## 输入

- `train.jsonl`：完整文件，必须从第 1 行读到 EOF。
- `system_prompt.txt`：判断人设是否漂移。
- `SPEC.md`：判断格式、长度、callback、分布。
- `PROMPT.md`：判断是否符合本轮写作规则。

不要给审校子代理 validator 摘要、REPORT 结论或抽样清单。

## 一个审校子代理，顺序读完整文件

- 只读；只写 `review/final_review.jsonl` 和 `review/final_review.md`。
- 用 Read 的 offset/limit 从第 1 行读到 EOF；不抽样、不用脚本代替阅读。
- 每块 50–100 行，或约 40k token，以先到者为准；绝不把一行 JSON 拆到两个块。
- 每读完一块，把问题追加到 running issue log，再读下一块；不要把全文都留在上下文里。
- 必须报告 `first_id`、`last_id`、`rows_read`；主代理用冻结行数核对，不一致即无效。
- 上下文放不下时，由同一个审校角色带同一份 issue log 继续分块读；不换人、不抽样。
- `system` 重复段可跳过阅读，但首行/末行要核对。

## 每块记录

```json
{"id":"cg_0001","severity":"blocker|major|minor",
 "category":"over_split|fragment|order|persona|repetition|callback|human|distribution|scene_source|near_duplicate|cot|factual|other",
 "issue":"一句话问题","evidence":"原文引用，<=80字",
 "suggestion":"改 prompt / 重生成 / 单点 fix / 接受"}
```

severity：

- blocker：人设崩坏、编造记忆、整段重复、气泡无法独立发送、system/角色泄漏。
- major：明显不自然、连续模板、分布严重偏斜、human 太书面。
- minor：个别措辞、标点、emoji、单条略长。

## 汇总与门禁

`final_review.md` 必须包含：

- 总行数、实际读到的首末 id、是否完整读完；
- 各 severity/category 计数；
- 最严重的 10 个 id；
- Top 5 系统性问题；
- 结论 `pass / fix-then-pass / fail`。

门禁：

- 0 blocker 才能交付；major 必须修复，或在汇总里写明接受理由。
- 单点修改只重审改过的行；系统性问题（同类 >5%）改 `PROMPT.md`、升版本、重跑 golden，并重新做完整全量审查。
- 通过后才更新 REPORT/README/AGENTS 并交付。

## 上下文预算

最终约 2,000–3,500 行；100 行/块约 20–35 块。审校子代理开始时确认总行数，结束时确认 `rows_read` 与冻结行数一致；缺少这个确认，审查不能算完成。
