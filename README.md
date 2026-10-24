# 🐱 猫娘角色微调 · Qwen3.5-4B

![猫娘](ee.png)

本仓库现在做**微调**：用自建的猫娘日常对话语料，把 `Qwen/Qwen3.5-4B-Base` 改成一个傲娇猫娘女友风格的模型。`catgirl/` 下的桌面助手是微调产物的下游消费端。

## 目录结构

| 路径 | 说明 |
|---|---|
| `database/qwen_catgirl_ft/` | **当前训练集**，565 条 shareGPT JSONL + 校验脚本 + `SPEC.md` |
| `database/catgirl_dataset/` | 上一版语料（360 条），已被上面取代 |
| `database/NekoQA-10K.json` | 更早的外源数据集引用（[NekoQA-10K](https://huggingface.co/datasets/liumindmind/NekoQA-10K)） |
| `catgirl/` | Tauri + TypeScript 桌宠前端，接 llama-server（详见 `catgirl/README.md`） |
| `modelfiles/` | Ollama Modelfile（人设 / 好感度状态机），仍指向上一版 GGUF |
| `scripts/` | 零散脚本，`create-model.bat` 是空文件 |

## 1. 基座：Qwen/Qwen3.5-4B-Base

架构 `Qwen3_5ForConditionalGeneration`，`transformers` 格式，bf16 共 **4.66B 参数 / 9.32GB**。文本侧 hidden 2560、FFN 9216、32 层 = **24 × linear_attention（Gated DeltaNet）+ 8 × full_attention**、vocab 248320、`tie_word_embeddings=true`。

按 `config.json` + `total_size` 反解的真实分组（误差 15M）：

| 模块 | 参数量 | 训练时的处理 |
|---|---|---|
| FFN ×32 | 2265M | 4-bit |
| full_attn ×8 | 294M | 4-bit（`attn_output_gate=true`，q_proj 是 2560→8192） |
| DeltaNet ×24 | 1011M | **8-bit，不上 4-bit** |
| embed（tied，无独立 lm_head） | 636M | bf16 常驻 |
| visual ×24 | 319M | **不加载** |
| mtp ×1 | 121M | 不加载（仅投机解码用） |

> `-Base` **也是多模态模型**（带 `vision_config`，视觉权重和文本权重在同一份 safetensors 里）。绕开视觉塔靠不实例化 `model.visual.*`，不是靠选 Base 版。

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

8GB 单卡显存预算（按上表真实参数量重算）：

| 项 | 显存 |
|---|---|
| 基座（4-bit 2559M + 8-bit 1011M + embed bf16） | 3.56GB |
| LoRA 权重 + 梯度（21.2M × 2 × fp32） | 0.17GB |
| AdamW m + v | 0.17GB |
| bf16 激活（ctx 2048 / bsz 1 / grad ckpt） | ~1.2GB |
| 反量化工作区 + CUDA context | ~0.9GB |
| **峰值合计** | **~6.0GB / 8GB** |

两个已知的坑：

- `text_config.mamba_ssm_dtype = float32`。DeltaNet 的 chunk state 每层约 33MB（seq 2048、32 value heads × 128×128），24 层全存 ≈0.8GB，fp32 翻倍。grad ckpt 能压到 1–2 层峰值，但反传到后段仍可能瞬时爆——建议把该状态显式降到 bf16，chunk 定 64。
- **梯度必须穿过 8-bit DeltaNet**：只要前面有 LoRA 需要梯度，这些层的计算图就不能用 `no_grad` 跳过，反量化工作区因此常驻。
- 实测以 `torch.cuda.max_memory_allocated()` 为准，不要按表推算。

## 3. 语料

`database/qwen_catgirl_ft/train.jsonl`：565 条、16 个场景标签均衡、2–6 轮、gpt 回复 50–200 字、固定 system（340 字，各条逐字一致）。纯对话文本 218,663 token / 整文件 JSONL 258,148 token，单条最长 737 字——**ctx 2048 足够，不需要 packing**。

格式、人设规范、校验细则见 `database/qwen_catgirl_ft/README.md` 和 `SPEC.md`；跑校验：

```bash
python database/qwen_catgirl_ft/tools/validate.py
```

> `database/qwen_catgirl_ft/README.md` 末尾的 LLaMA-Factory 参数是按**单卡 24G、lora_rank 32、bsz 4**写的，与本仓库 8GB / r=16 / bsz 1 的方案不一致，以本文件为准。

## 4. 当前进度

- ✅ 语料 565 条 + 校验脚本
- ✅ 基座选型、参数分组、8GB 显存预算定稿
- ✅ `catgirl/` 桌宠前端重写为 Tauri + TypeScript，对话走 llama-server
- ⬜ 桌宠没实机跑过：`cargo check` 已通过（tauri 2.12.5），但 `tauri dev` 未启动，透明窗口/托盘/拖拽仍缺肉眼验证
- ⬜ 基座权重下载（需 `HF_HUB_DISABLE_XET=1`）
- ⬜ 训练脚本尚未入仓（仓库内还没有 train 入口 / yaml）
- ⬜ LoRA → GGUF → llama-server 导出链路未验证：llama.cpp 侧需支持 `qwen3_5`（Gated DeltaNet + MTP）；`modelfiles/Modelfile` 的 `FROM` 目前仍是上一版 DeepSeek GGUF，且桌宠已不再走 Ollama
