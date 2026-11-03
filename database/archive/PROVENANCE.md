# 原始数据归档说明

2026-10-29 合并训练集时，从仓库原路径复制到这里，并拍平成一层 `a_*` / `b_*` / `nekoqa_*` 文件，避免和「训练集目录」混淆。`archive/` 下文件只读，不要直接改；需要调整口径请改 `tools/build.py` 后重建。

## 对应关系

| 归档路径 | 原路径 | 原始量 | 说明 |
|---|---|---|---|
| `a_batch_01..18_*.jsonl` | `database/catgirl_dataset/batches/` | 18 批 / 360 条 | 小咪＋过往背景版 |
| `a_system_prompt.txt` | `database/catgirl_dataset/system_prompt.txt` | 606 字 | 已被新的合并人设取代，仅留档 |
| `b_batch_01..28.jsonl` | `database/qwen_catgirl_ft/data/` | 28 批 / 560 条 | 公寓日常版 |
| `b_samples_5.jsonl` | `database/qwen_catgirl_ft/samples/samples_5.jsonl` | 5 条 | 这 5 条不在批次里，补齐后才是 565 |
| `b_system_prompt.txt` | `database/qwen_catgirl_ft/system_prompt.txt` | 245 字 | 旧通用人设，仅留档 |
| `nekoqa_10k.json` | `database/NekoQA-10K.json` | 10,066 条 instruction/output | 外源单轮问答，md5 `c812fc7987629b84f4880dbfa81eb77d` |

旧 system prompt 的 md5：小咪版 `8cfef2e2a9609865891ac189eead6485`，通用版 `6b7e8091643f78a4d3cc4847dab5154f`。

`train.jsonl` 里的 `source` 字段仍使用 `catgirl_dataset` / `qwen_catgirl_ft` / `nekoqa` 作为来源标签，只用于溯源与降采样，不是目录名。

## 旧目录

原 `database/catgirl_dataset/`、`database/qwen_catgirl_ft/` 和 `database/NekoQA-10K.json` 已在 2026-10-29 删除。它们此前都在 git 中，可从提交 `ffe7b1e` 恢复；本目录保留了训练所需的全部原始对话数据。

未归档的旧文件（README、REPORT、SPEC、tools）只用于生成与校验，已被 `database/README.md`、`database/SPEC.md`、`database/tools/build.py` 取代。
