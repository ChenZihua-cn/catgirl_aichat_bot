# Qwen3.5-4B · 猫娘傲娇女友微调数据集

## 文件

| 文件 | 说明 |
|---|---|
| `system_prompt.txt` | 固定 system prompt（人设原文，360 条样本逐字一致） |
| `samples_5.jsonl` | 5 条格式校验样本（起床/做饭/生病/冷战/睡前） |
| `train.jsonl` | 全量训练集，360 条，按批次顺序合并 |
| `train_shuffled.jsonl` | 不跟踪；由 `finalize.py` 以 seed=42 生成 |
| `batches/batch_*.jsonl` | 17 个批次，每批 20 条，可单独增删 |
| `REPORT.json` | 批次级统计（条数/token/累计/回复字数/轮次分布） |
| `tools/` | `stats.py`（统计+校验）、`normalize.py`（统一 system）、`finalize.py`（合并导出）、`expand_short.py`、`fix_lines.py` |

## 格式

shareGPT 结构，每行一个 JSON 对象：

```json
{"id":"cg_0001","scene":"起床","conversations":[
  {"from":"system","value":"<固定人设>"},
  {"from":"human","value":"..."},
  {"from":"gpt","value":"..."}
]}
```

- 顶层字段：`id`（全局唯一）、`scene`（中文场景标签）、`conversations`
- `conversations` 首条必须为 `system`，内容与 `system_prompt.txt` 完全一致；其余 human/gpt 严格交替，末轮为 gpt
- 样本对话 2–6 轮（`batch_16_微信短聊` 为微信体，4–8 个短来回）

## 规模与分布

- 样本总数：**360** 条；预估 token 总量：**约 318K**（中文按 0.72 token/字启发式估算，真实 Qwen tokenizer 通常在 ±10% 内）
- 12 个日常场景各 25 条：起床 / 做饭吃饭 / 家务 / 通勤 / 上班上课 / 加班 / 逛街 / 看电影 / 生病照顾 / 吵架冷战 / 和好 / 睡前聊天
- `batch_16_微信短聊`（20 条，单条约 10 字微信体）、`batch_17_接梗日常`（20 条，2018–2024 网络热梗）
- `batch_18_校园回忆`（20 条）：高一活泼（社团/运动会/月考/游学）×4、高二青春暧昧（前后桌/晚自习停电/艺术节弹琴/冬天捂手）×4、高三备考（三模天台/蒙被子刷题/成人礼/百日誓师画猫）×4、大学 ×8（报到/模拟法庭/课堂争论/话剧社与乐团/看展/律所实习/考试周/本硕连读）
- 轮次分布：2 轮 25、3 轮 43、4 轮 60、5 轮 70、6 轮 41、微信体 4–8 回合约 20

## 人设背景（已写入 system_prompt.txt）

家境好、富养长大、从小家教严，学过钢琴、看得懂画展和话剧；高中时和用户就是同班同学，高二起关系暧昧，高三一起熬备考；大学读法学院本硕实验班（六年本硕连读），课业重，参加过话剧社和管弦乐团；现已毕业工作，与用户同居。回忆类样本（batch_18）会自然提到这段过去。

## 风格要点

- 傲娇 = 「做了一半 + 嘴上否认另一半」：先把关心的事做了/说了，再立刻否认动机
- 猫娘语气词（喵/喵呜/本喵/咱）稀疏使用，禁止句句带「喵」
- 关心用行动表达（端水、留饭、熨衬衫、接下班），不说教、不复读人设、无 AI 出戏声明
- 短批次说明：`batch_09~12`（生病/吵架/和好/睡前）回复偏短（平均 39–53 字），是为「冷战/和好」场景刻意的冷淡短句；`batch_16` 是 10 字微信体。若需全库统一 50–200 字，删掉这两个风格批次即可
- 若要回到 256K 左右：删掉 `batch_13~15`（约 75K）或 `batch_18` + `batch_09~12`（约 40K），按 REPORT.json 里的 token 数自选组合

## 复现/再生成

```bash
# 统计与校验（含 system 一致性、role 交替、末轮 gpt、字数区间）
EST_TOKENIZER=heuristic python tools/stats.py "batches/*.jsonl"

# 新增批次后：统一 system + 合并导出
python tools/normalize.py "batches/batch_XX_*.jsonl"
python tools/finalize.py
```

## 已知取舍

- token 数为启发式估算（环境无法访问 HuggingFace 下载 Qwen tokenizer，`EST_TOKENIZER=real` 可在线时切换）
- 超 200 字的 3 条回复已在 `finalize.py` 中自动修剪到 200 以内
- `batch_16/17` 与主集的长度风格不同，是有意保留的多样性；如训练时希望长度分布更集中，可按 REPORT.json 里的均字筛选
