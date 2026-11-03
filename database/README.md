# 猫娘小咪 · 微信短聊训练集

本目录（仓库根下的 `database/`）是仓库**唯一**的人设训练语料目录，下列文件与子目录直接位于 `database/` 下，没有再嵌套一层。语料按微信短聊组织：每轮 assistant 回复拆成 1–4 个气泡，气泡之间用 `\n\n` 连接；`\n\n` 在 Qwen3.5 分词器里是单 token（id 271），不改词表、不需要服务端开关。`train.jsonl` 由 `tools/build_wechat.py` 从 `distill/` 下的冻结素材确定性重建。

## 文件

| 文件 | 说明 |
|---|---|
| `train.jsonl` | **主训练集**，1,652 条，seed=42 打乱，可直接喂 LLaMA-Factory / xtuner / 自写 Trainer |
| `samples_5.jsonl` | 5 条格式校验样本（每场景一条） |
| `system_prompt.txt` | 唯一 system 人设（740 字），所有行逐字一致；无空行，不会污染气泡分隔 |
| `SPEC.md` | 格式、气泡、CoT、分布与构建规范 |
| `REPORT.json` | 构建统计：来源/场景/气泡/长度/分布/CoT |
| `distill/PROMPT.md` | 数据写作规则（wechat-v1.3） |
| `distill/COT_PROMPT.md` | 隐藏 CoT 写作规则 |
| `distill/source/legacy_train.jsonl` | 冻结的 3,228 条旧语料，只读 |
| `distill/accepted/` | 改写/新会话的接受池（rewrite 3,228 / new 300） |
| `distill/seeds/` | 300 个新会话 seed（p001–p300） |
| `distill/cot.jsonl` | CoT 源映射：`{"id","cot"}`，对应 `train.jsonl` 顶层 `cot` |
| `distill/batches/` | 分批生成、校验、复审的中间产物 |
| `distill/review/` | pilot 复审、最终全量审查（`final_review.md`）、单点 fixes、`drop_final_major.ids` |
| `archive/` | 原始批次、原始 system prompt、NekoQA 原始 JSON，只读 |
| `tools/` | 构建、分批校验、CoT 校验/合并、accepted 替换 |

## 规模

- 样本 **1,652** 条，assistant 轮 **5,577** 轮，气泡 **9,756** 个
- 单/双/三/四气泡：2,340 / 2,303 / 926 / 8；单气泡占 **41.96%**
- 气泡长度 2–40 字，平均 9.9；整轮 2–79 字，平均 18.9
- emoji 轮次 **18.5%**；问句结尾 **26.5%**；猫娘口癖 **23.26%**；本喵 **6.2%**
- `long`（知识/诗歌/建议）**66 行，4.0%**，低于 5% 上限
- 每条样本带一条隐藏 CoT（8–24 字，平均 10.9；规则上限 40），对应**最后一条 gpt 回复**；1,652/1,652 全覆盖
- 20 个中文场景全部非空

### 来源构成

| 来源 | 条数 | 说明 |
|---|---|---|
| `qwen_catgirl_ft` | 561 | 公寓日常改写，全部保留 |
| `catgirl_dataset` | 240 | 小咪背景集改写 |
| `nekoqa` | 551 | 猫娘问答改写；受 40% 上限约束，最终占 33.35% |
| `distill_new` | 300 | 新写的微信短聊会话，每会话 1 次可验证 callback |
| **合计** | **1,652** | |

改写池已覆盖全部旧语料：接受 3,228 条（A/B 809 + NekoQA 2,419）。最终集只使用有 CoT 的候选；重建时 `--drop-missing-cot` 共排除 1,876 条——1,861 条 NekoQA 未生成 CoT，另有 15 条最终审查淘汰行（`distill/review/drop_final_major.ids`）不再保留 CoT。交付 1,652 条。

### 场景分布

| 场景 | 条数 | 场景 | 条数 |
|---|---:|---|---:|
| 日常问答 | 565 | 做饭吃饭 | 77 |
| 看电影 | 76 | 加班 | 76 |
| 通勤 | 75 | 逛街 | 76 |
| 起床 | 75 | 家务 | 74 |
| 上班上课 | 72 | 生病照顾 | 61 |
| 吵架和好 | 58 | 睡前聊天 | 57 |
| 周末出游 | 51 | 天气雨天 | 49 |
| 学习考试 | 49 | 游戏爱好 | 49 |
| 纪念日礼物 | 49 | 校园回忆 | 32 |
| 微信短聊 | 16 | 接梗日常 | 15 |

### NekoQA 的已知问题（重要）

`nekoqa` 原本是「猫娘口径的知识问答/情感建议」，包含百科题、写诗、职业建议、无厘头假设，不是日常聊天。转换只清洗格式（括号/星号动作、`主人/宝宝` 称呼、`的说`、元提问、角色错位、他人名字泄漏），去不掉内容取向。构建默认把它压到最终行数的 **40% 以下**（本集 33.35%）；需要更纯的日常风格时，可直接按 `source != "nekoqa"` 过滤。

## 格式

一行一个 JSON 对象：

```json
{"id":"cg_0001","source":"qwen_catgirl_ft","scene":"起床",
 "cot":"又拖到这么晚，胃肯定空了。先把饭热着，别让他看出来我一直在等。",
 "conversations":[
  {"from":"system","value":"<system_prompt.txt 原文>"},
  {"from":"human","value":"..."},
  {"from":"gpt","value":"第一口气泡\n\n第二口气泡"}
 ]}
```

- `id` 全局唯一；`source` 用于溯源/降采样；`scene` 为中文标签
- `conversations[0]` 恒为 system 且全行仅一条；其后 human/gpt 严格交替，human 开头、gpt 结尾
- gpt 的 `value` 是气泡用 `\n\n` 连接；单个气泡内部不出现 `\n\n`，单个 `\n` 不会触发切分
- 每条 1–8 个 gpt 轮；改写行轮数与原会话一致，新会话 6–8 轮

## CoT 的训练/推理对齐

- [`finetune/mix_dataset.py`](../finetune/mix_dataset.py) 把 `cot` 编码成 Qwen3.5 的 `<think>` 段：`<|im_start|>assistant\n<think>\n`（开头 mask）+ cot + `\n</think>\n\n` + 可见回复（监督）。
- CoT 是**内心独白**，不是回复策略：不要求“先…再…”，允许心动、嘴硬、吐槽、心疼、回忆、吃醋、犹豫、自嘲、碎念、联想、反问等形态。实际分布：问句 12.6%、感叹 1.6%、省略 2.7%、无句末标点 17.6%；以“先”开头仅 0.85%，含“先”5.1%、含“再”2.8%。
- 推理时客户端发 `chat_template_kwargs: {enable_thinking: true}`，只显示正文。
- 顶层 `cot` 是自定义字段，LLaMA-Factory 默认忽略。走 LLaMA-Factory 时先把 cot 注入最后一条 gpt 的 `<think>`，或直接用 `mix_dataset.py`。

## 重建与校验

```bash
# 最终集（缺 CoT 的候选会被明确丢弃并打印数量）
python3 database/tools/build_wechat.py --from accepted --drop-missing-cot

# 只做装配、不写文件
python3 database/tools/build_wechat.py --from accepted --drop-missing-cot --dry-run
```

构建前逐行校验：JSON、system 逐字一致、role 交替、末轮 gpt、气泡 1–4 且单条 2–60 字、整轮 2–200 字、无空串/`\n\n` 残留、无禁用词/动作旁白/其他猫娘名、human 3–30 字、CoT 8–40 字且全覆盖、场景合法、NekoQA ≤40%、long ≤5%。任何一项不过直接报错，不写半成品。

## 训练建议

**以根 README 的「基座」与「训练配置」为准**（8GB 单卡 / LoRA r=16 / bsz 1 / ctx 2048）。旧 `qwen_catgirl_ft/README.md` 里的 24G / rank 32 / bsz 4 参数不要直接抄。

LLaMA-Factory 数据声明：

```yaml
{"catgirl_ft": {"file_name": "train.jsonl", "formatting": "sharegpt",
               "columns": {"messages": "conversations"},
               "tags": {"role_tag": "from", "content_tag": "value", "user_tag": "human",
                        "assistant_tag": "gpt", "system_tag": "system"}}}
```

推理时使用同一份 `system_prompt.txt`（客户端 `catgirl/src/config/persona.ts` 直接引用该文件）。

## 来源归档

原始路径与本目录的对应关系见 [`archive/PROVENANCE.md`](archive/PROVENANCE.md)。旧目录 `database/catgirl_dataset/`、`database/qwen_catgirl_ft/` 与 `database/NekoQA-10K.json` 已删除；内容在 git 历史和 `archive/` 中都还在。
