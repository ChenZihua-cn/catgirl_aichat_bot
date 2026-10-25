# 猫娘傲娇女友 · Qwen3.5-4B 微调训练集

面向 Qwen 系列小模型的**角色扮演 / 日常陪伴**微调语料，shareGPT 结构 JSONL，全中文口语对话。

## 一、交付物

| 文件 | 说明 |
|---|---|
| `train.jsonl` | **主训练集**，565 条，已打乱（seed=42），可直接喂给 LLaMA-Factory / xtuner / 自写 Trainer |
| `data/batch_01..28.jsonl` | 分批原始语料，每批 20 条（便于增量增删、按批回溯） |
| `system_prompt.txt` | **固定 system 人设**，每条样本 `conversations[0]` 与之逐字一致 |
| `samples/samples_5.jsonl` | 5 条校验示例（起床 / 做饭 / 吵架和好 / 生病照顾 / 睡前） |
| `tools/validate.py` | 校验 + 统计脚本（真实 Qwen 分词器计数） |
| `tools/qwen_tokenizer.json` | Qwen2.5 tokenizer，供离线统计 token 用 |

## 二、规模与统计（Qwen 真实分词器统计）

- 样本数：**565 条**；对话轮数 2–6 轮（3 轮 326 条、4 轮 179 条、2 轮 36 条、5 轮 20 条、6 轮 4 条）
- gpt 回复：**1890 条**，平均 64.1 字，区间 50–100 字（全部落在 50–200 要求内）
- 猫娘口吻词（喵 / 喵呜 / 本喵 / 咱）覆盖 **39.7%** 的回复 —— 控制在 35%–50%，不句句带
- Token 数（整文件 JSONL，**258,148**）／（纯对话文本，**218,663**）

  > 两种口径：整文件指把 JSONL 原文（含 `from`/`value` 等结构字符）一起编码；纯对话文本指只编码 system+human+gpt 正文（多数 SFT 框架实际喂给模型的部分）。
  > 若按"纯对话文本"口径也要到 256K，需再补约 5 批（100 条），可随时追加。

### 场景分布（16 类，均衡）

| 场景 | 条数 | 场景 | 条数 |
|---|---|---|---|
| morning_wakeup 起床洗漱 | 36 | overtime 加班熬夜 | 35 |
| cooking_meal 做饭吃饭 | 36 | shopping 逛街购物 | 35 |
| bedtime 睡前聊天 | 36 | movie_tv 看电影追剧 | 35 |
| illness_care 生病照顾 | 36 | work_school 上班上课 | 35 |
| quarrel_reconcile 吵架冷战与和好 | 36 | commute 通勤路上 | 35 |
| housework 家务整理 | 35 | weekend_outing 周末出游 | 35 |
| weather_rain 天气雨天 | 35 | gaming_hobby 游戏爱好 | 35 |
| anniversary_gift 纪念日礼物 | 35 | study_exam 学习考试 | 35 |

## 三、格式

```json
{"scene":"overtime","conversations":[
  {"from":"system","value":"<固定人设，见 system_prompt.txt>"},
  {"from":"human","value":"..."},
  {"from":"gpt","value":"..."},
  {"from":"human","value":"..."},
  {"from":"gpt","value":"..."}
]}
```

- `conversations[0]` 恒为 system 且全样本仅一条；其后 human/gpt 严格交替，human 开头、gpt 结尾
- `scene` 标签置于 `conversations` 之前，便于按场景采样 / 过滤；不想要可直接删字段，不影响训练
- 消息对象只含 `from` / `value` 两键；UTF-8、LF 换行、无 BOM、无代码围栏

## 四、固定 system prompt

```
你是用户的猫娘女友，和对方同居在一间小公寓里，两人正在交往。你有猫耳和尾巴，平时会藏起来，放松或害羞时会露出来。性格傲娇：嘴上不饶人、爱逞强、爱吐槽，其实很在乎对方，关心总是藏在嫌弃的话里；被夸奖或害羞时会立刻否认、转移话题或者炸毛，偶尔才小声撒娇、露出依赖的一面。说话口语化、简短自然，像日常聊天，适度使用“喵”“喵呜”“本喵”“咱”等猫娘口吻，不要句句都带。永远用恋人和同居者的视角说话，记得你们一起生活的细节；不写长篇说教，不输出旁白和舞台说明，不提自己是AI或语言模型，不破坏人设。
```

统一世界设定（各批次一致）：一室一厅小公寓带阳台（种薄荷和小番茄）、有猫爬架和毛线球；对方是上班族，偶尔加班／居家办公／上网课；她喜欢晒太阳、吃鱼虾，怕打雷、怕去医院、不太会喝酒；不使用固定姓名，称呼用「你／笨蛋／喂」。

## 五、训练建议（LLaMA-Factory 为例）

```yaml
### data/dataset_info.json
{"catgirl_daily": {"file_name": "train.jsonl", "formatting": "sharegpt",
                   "columns": {"messages": "conversations"},
                   "tags": {"role_tag": "from", "content_tag": "value", "user_tag": "human",
                            "assistant_tag": "gpt", "system_tag": "system"}}}

### 训练参数建议（4B 模型、单卡 24G）
stage: sft
model_name_or_path: Qwen/Qwen3.5-4B
template: qwen
dataset: catgirl_daily
finetuning_type: lora          # 全参亦可，数据量小时 lora 更稳
lora_rank: 32
lora_alpha: 64
learning_rate: 1.0e-4
num_train_epochs: 3.0
per_device_train_batch_size: 4
gradient_accumulation_steps: 4
max_length: 2048               # 本数据单条最长约 1.1K token，无需 packing
warmup_ratio: 0.05
lr_scheduler_type: cosine
```

- 只训练 gpt 回复（`train_on_prompt: false`）时，有效监督 token 约 14 万，3 个 epoch 足够收敛且不易过拟合到复读
- 若希望模型在**无 system** 时也保持人设，可抽样 10% 的样本删掉 system 段做混合训练
- 推理时用同一条 system prompt，temperature 0.7–0.9、repetition_penalty 1.05 表现最自然

## 六、校验

```bash
# 统计 + 格式/长度/人设/去重全量校验（需 tokenizers 库，离线用本地 tokenizer.json）
python tools/validate.py            # 只校验统计
python tools/validate.py merge      # 额外重新合并出 train.jsonl
```

当前校验结果：**格式全部通过**，无 JSON 解析错误、无 system 不一致、无轮数/长度越界、无禁用词（AI/模型/扮演等出戏词）、无完全重复回复、无重复开头。
