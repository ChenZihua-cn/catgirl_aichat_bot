# 🐱 猫娘角色微调 · Qwen3.5-4B

![猫娘](ee.png)

本仓库现在做**微调**：用自建的猫娘日常对话语料，把 `Qwen/Qwen3.5-4B-Base` 改成一个傲娇猫娘女友风格的模型。`catgirl/` 下的桌面助手是微调产物的下游消费端。

## 目录结构

| 路径 | 说明 |
|---|---|
| `database/qwen_catgirl_ft/` | **当前训练集**，565 条 shareGPT JSONL + 校验脚本 + `SPEC.md` |
| `database/catgirl_dataset/` | 上一版语料（360 条），已被上面取代 |
| `database/NekoQA-10K.json` | 更早的外源数据集引用（[NekoQA-10K](https://huggingface.co/datasets/liumindmind/NekoQA-10K)） |
| `catgirl/` | Tauri + TypeScript 桌面客户端，接 llama-server（详见 `catgirl/README.md`） |
| `modelfiles/` | Ollama Modelfile（人设 / 好感度状态机），仍指向上一版 GGUF |
| `scripts/` | 零散脚本，`create-model.bat` 是空文件 |

## 1. 基座：Qwen/Qwen3.5-4B-Base

架构 `Qwen3_5ForConditionalGeneration`，`transformers` 格式，bf16 共 **4.66B 参数 / 9.32GB**。文本侧 hidden 2560、FFN 9216、32 层 = **24 × linear_attention（Gated DeltaNet）+ 8 × full_attention**、vocab 248320、`tie_word_embeddings=true`。

逐张量实测分组（直接读 safetensors 头，不是反解；合计 4659.9M / bf16 9.32GB）：

| 模块 | 参数量 | bf16 | 训练时的处理 |
|---|---|---|---|
| FFN ×32 | 2264.9M | 4.53GB | 4-bit |
| full_attn ×8 | 293.6M | 0.59GB | 4-bit（`attn_output_gate=true`，q_proj 是 2560→8192） |
| DeltaNet ×24 | 1011.4M | 2.02GB | **8-bit，不上 4-bit** |
| embed（tied，无独立 lm_head） | 635.7M | 1.27GB | bf16 常驻；4-bit 会直接压到词表输出分布 |
| visual（blocks 302.3 + merger 27.3 + pos 2.4 + patch 1.6） | **333.6M** | 0.67GB | **bf16 加载并冻结**，不量化、不挂 LoRA |
| mtp ×1 | 120.6M | 0.24GB | 加载时被忽略，不是本方案的选择项 |

> `-Base` **也是多模态模型**，视觉塔进不进训练只取决于加载哪个类；类选择、存盘丢视觉权重、`mtp.*` 自动忽略这些机制写进 **AGENTS.md**。本仓库的路线是保住看图能力，所以视觉塔 bf16 冻结常驻（§2 预算已含这 0.67GB）。

下载（9.34GB）：

```bash
export HF_ENDPOINT=https://hf-mirror.com      # 直连 huggingface.co 不通
export HF_HUB_DISABLE_XET=1                   # 镜像不代理 cas-server.xethub.hf.co，Xet 通道会 401
hf download Qwen/Qwen3.5-4B-Base --local-dir /home/labubu/30856/Model/Qwen3.5-4B-Base
```

权重放在仓库外的 `/home/labubu/30856/Model/`，不入库。

## 2. 训练配置

| 项 | 值 |
|---|---|
| adapter | LoRA r=16 fp32，挂在 attn + FFN，不动 DeltaNet |
| 优化器 | AdamW fp32，lr 1e-4，cosine，warmup 3% |
| 前向 | bf16 + gradient checkpointing，ctx 2048，bsz 1，accum 16 |

8GB 单卡显存预算（按上表实测参数量重算）：

| 项 | 显存 |
|---|---|
| 基座（4-bit 2558.5M + 8-bit 1011.4M + embed bf16） | 3.56GB |
| 视觉塔 + merger（bf16 冻结，§3 图文路线必需） | +0.67GB |
| LoRA 权重 + 梯度（21.2M × 2 × fp32） | 0.17GB |
| AdamW m + v | 0.17GB |
| bf16 激活（ctx 2048 / bsz 1 / grad ckpt） | ~1.2GB |
| 反量化工作区 + CUDA context | ~0.9GB |
| **峰值合计** | 图文路线 **~6.7GB**，纯文本路线（不载视觉塔）~6.0GB ／ 上限 8GB |

## 3. 数据

**人设语料** `database/qwen_catgirl_ft/train.jsonl`：565 条、16 个场景标签均衡、2–6 轮、gpt 回复 50–200 字、固定 system（340 字，各条逐字一致）。纯对话文本 218,663 token / 整文件 JSONL 258,148 token，单条最长 737 字——**ctx 2048 足够，不需要 packing**。格式与人设规范见同目录 `README.md`、`SPEC.md`，校验：

```bash
python database/qwen_catgirl_ft/tools/validate.py
```

**图文锚点**：为防纯文本 SFT 改掉视觉通路，仓库外挂三个数据集（`/home/labubu/30856/Model/datasets/`，共 4.2GB，分片字节数与镜像 API 一致）：

| 数据集 | 体量 | 备注 |
|---|---|---|
| `llava-instruct-mix-vsft` | 取 2/20 训练分片（1.09GB；全量 25,916 条）+ 全部 test 分片（0.57GB / 13,640 条） | test 分片作视觉漂移评测集 |
| `LLaVA-OneVision-Data/llava_wild_4v_12k_filtered` | 0.49GB / 7,562 条 | 单图 image struct + conversations |
| `LLaVA-OneVision-Data/ureader_cap` | 2.29GB / 4,813 条 | 0% 含中文（仓库标 `language:zh`） |

**混采管道** `finetune/mix_dataset.py` 把人设文本（`batches` / `qwen_ft` / `nekoqa` / `spec_data`）与图文行归一成一个 encoding：`input_ids / labels / attention_mask / mm_token_type_ids / pixel_values / image_grid_thw`，assistant-only loss，按轮次粒度截断，`--ratio` 控图文占比（默认 33%）。

```bash
/home/labubu/30856/Model/.venv/bin/python finetune/mix_dataset.py --text batches --text-cap 60 --image-cap 20
```

`persona_hook()` 目前是恒等函数，图文答案保持原文；改写方向等中文图文数据定了再动（选项见 AGENTS.md）。实测记录与项目进度也都在 AGENTS.md。
