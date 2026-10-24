# AGENTS.md — 本仓库作业规则

分工：**README.md 只放项目状态、实测数字和可复现命令；所有机制解释、"别信什么/为什么会静默失效"写在这里。** 发现新的坑，写这个文件，不要往 README 里加叙述。

## 网络与下载

- `huggingface.co` 直连不通。一律先 `export HF_ENDPOINT=https://hf-mirror.com`。
- **必须**同时 `export HF_HUB_DISABLE_XET=1`。镜像不代理 `cas-server.xethub.hf.co`，走 Xet 通道的大文件会 `401 Unauthorized`；小文件不受影响，所以症状是"配置明明成功、权重下不下来"，很容易误判。
- hf CLI 1.32 的 `hf download <repo> --include A B C` 会把第一个 pattern 当位置参数吞掉，只显示 "Fetching N files" 却少下一个。下完必须 `ls` 跟清单对数。
- 校验方式：拿镜像 tree API 的 per-file size 逐个比字节，parquet 再查首尾 `PAR1`。别只看命令退出码。

## Python 环境

- 训练只用 `/home/labubu/30856/Model/.venv`（uv 管理，python3.12）。它同时服务 `Model/` 下其它模型工作，改坏了影响面大。
- `transformers==5.17.0` 是硬依赖（只有它带 `qwen3_5`）。任何要把 transformers 或 torch 升降级的解析结果都先拒绝再报告，别让它顺手改。
- 已装并验证：peft 0.21.2 / trl 1.16.0 / accelerate 1.15.0 / bitsandbytes 0.50.2 / datasets 5.1.0 / pyarrow 26.0.0。Gated DeltaNet 不需要 flash-linear-attention，transformers 自带 torch 实现。
- 依赖装完要说明装在哪一层（venv / 系统 / uv 全局），不要只回一句"装好了"。

## 内存红线

- 系统只有约 8GB 空闲 RAM：**禁止**整体 `from_pretrained` 载入 4.66B bf16 权重（9.3GB）。要证明机制就用 2 层小 config 代理或只载视觉塔。
- 大 parquet 用 pyarrow 逐 row-group 读，别 `pq.read_table` 整文件。
- 显存结论一律以 `torch.cuda.max_memory_allocated()` 实测为准，不按参数表推算。

## DeltaNet 与显存

- `text_config.mamba_ssm_dtype = float32`。DeltaNet 的 chunk state 每层约 33MB（seq 2048、32 value heads × 128×128），24 层全存 ≈0.8GB，fp32 翻倍。gradient checkpointing 能把峰值压到 1–2 层，但反传到后段仍可能瞬时爆——建议把该状态显式降到 bf16，chunk 定 64。
- **梯度必须穿过 8-bit DeltaNet**：只要前面有 LoRA 需要梯度，这些层的计算图就不能用 `no_grad` 跳过，反量化工作区因此常驻。别指望"DeltaNet 不挂 LoRA 就不占显存"。
- 视觉 token 也吃 ctx：`MAX_PIXELS=512²` 一张图展开 192 token（≈ctx 2048 的 9%），像素张量本身 `768×1536` bf16 约 2.4MB/图。走图文混采时 `MAX_PIXELS` 是显存旋钮，不是画质旋钮。
- Gated DeltaNet 不需要 flash-linear-attention：transformers 自带 `torch_chunk_gated_delta_rule` / `torch_recurrent_gated_delta_rule`，纯 autograd 可反传，代价是激活更占。

## 模型加载（Qwen3.5）

- `-Base` **也是多模态 checkpoint**：`vision_config` 和 `model.visual.*` 与文本权重同在一份 safetensors 里，"选 Base 版"绕不开视觉塔。
- 绕不绕只取决于加载哪个类。`Qwen3_5ForConditionalGeneration` 读入 `model.visual.*`、只忽略 `mtp.*`（`modeling_qwen3_5.py:925`）；`Qwen3_5ForCausalLM` 把 `model.visual.*` 连同 `mtp.*` 一起丢（同文件 `:1670`）。
- **产物只保存你加载过的模块。** 用 `ForCausalLM` 训练再 `save_pretrained`，视觉权重就永久不在那个 checkpoint 里，得手动从原版合并才找得回来。要保住看图能力，从加载那一步就得用 `ForConditionalGeneration`。
- `mtp.*`（120.6M）不是可选项：两个类都把它列进 `_keys_to_ignore_on_load_unexpected`，HF 训练里既不前向也不进 loss。别把它算进显存预算，也别在"留不留"上花时间——只有导 GGUF 当投机解码草稿头时才有意义。
- 写量化排除项和 LoRA 目标时用真实前缀：`model.language_model.layers.*`、`model.visual.*`、`mtp.*`。不是 `model.layers.*`，按直觉写会静默匹配不到任何模块。
- 视觉塔是否常驻会改显存结论（bf16 冻结约 +0.67GB），README §2 的两条预算线就是区分这个的。

## Qwen3.5 数据侧

编码管道的踩坑清单（全部在本机 checkpoint 上量出来，别按直觉写）：

- processor 的文本参数名是 `text=`；写成 `texts=` **不报错、被静默忽略**，直到取 `input_ids` 才炸。
- `AutoProcessor` 这层没有 chat template（`processor.apply_chat_template` 抛 ValueError），模板只挂在 tokenizer 上；且 4B-Base 仓库不发布独立的 jinja 模板文件（镜像上 404），后训练版仓库才有。
- 视觉块是 `vision_start + N × image_pad + vision_end`，N = `grid_t*h*w/merge^2`（merge=2、patch=16）。`apply_chat_template` **不会**替你展开——模板里只放 1 个 pad，得自己按 N 复制。
- 图像处理器 `size` 里的键叫 `longest_edge`，代码实际当 `max_pixels` 用（512×512 限出 grid (1,32,24) = 192 pad），不是边长。
- 逐轮拼接和整串 tokenize 不是逐位相同：轮次在换行处发生 BPE 合并，前者每轮少 0–1 个 token。监督段必须逐 token 对齐，别靠子串搜索定位。
- 模板在最后一个 assistant 轮后补一个终止 stop token；逐轮拼接必须自己补，而且它要进监督——漏了模型学不到回复在哪结束。被截断的行**不能**补，那等于训练提前停机。
- 模板要求消息里至少有一个 user 轮，否则 jinja 抛 "No user query found in messages"。
- 图文行的答案必须是最后一轮，否则监督段为空。
- 数据集仓库的元数据不可信：`ureader_cap` 打着 `language:zh`，实测 0% 含中文。语言、条数、图片是否打包，都要自己抽样量。

`finetune/mix_dataset.py` 已按上面这些实现。README §3 只留数据事实与跑法命令，实测数字记在本文件末尾的「实测记录」。

### 视觉锚点的两个判断

- **纯文本 loss 看不出视觉退化**，所以必须留图文评测集；仓库里那两个 test 分片（13,640 条）就是干这个的。别拿"文本 loss 正常"当没退化的证据。
- 目前**没有任何含中文的图文训练样本**（`ureader_cap` 实测 0% CJK）。三条路，还没定：
  1. 直接用现有英文图文当锚点——零额外工作，只保能力不教中文看图说话。
  2. `FreedomIntelligence/ALLaVA-4V-Chinese`：标注是真中文且 Apache-2.0，**但仓库只有 JSON，图片要另外从原版 `ALLaVA-4V` 取，而原版是 cc-by-nc-4.0**——许可按最弱的一环算，别只看那个 Apache 标签。
  3. 用本地已有的 Qwen3.5-9B + `mmproj-Qwen3.5-9B-f16.gguf` 给这些图重打成中文猫娘口吻描述：顺带把英文 VQA 腔和人设冲突一起解决，代价是要先跑通 llama-server 的批量推理。

## 数字的出处

`database/qwen_catgirl_ft/README.md` 末尾的 LLaMA-Factory 参数是按**单卡 24G / lora_rank 32 / bsz 4**写的，和本仓库 8GB / r=16 / bsz 1 的方案不是一回事。抄之前先确认卡。以 README §1–§2 为准。

## 事实与措辞纪律

- **不要用产物缺失反推"没跑过"**。`tauri dev` 走 `beforeDevCommand: npm run dev` + `devUrl`，根本不产出 `dist/`；`target/` 也可能被 clean 掉。用户说跑过就是跑过，要确认就自己启动看窗口，而不是拿目录状态驳回。
- 环境/依赖类断言先重新探测再说（`pgrep` 之外还要注意 `pkill -f` 会匹配到自己的命令行，导致自杀式退出 143）。
- 一次性探针脚本（`_probe*.py`）用完就删，结论进 README；不要把没实现的占位函数留在仓库里。

## 仓库现状与 git

- `catgirl/` 是 Tauri + TypeScript 桌面客户端，用户正在重构，工作区里有大量既存改动。不要 `stash` / `checkout` / `reset` / `clean`，未获明确要求不 commit。
- **措辞纪律**：这个产品不是"桌宠"，是桌面虚拟女友（见 `REACTOR.md` §0）。注释、文档、UI 文案、标识符里都不要重新引入 `桌宠` 或 `pet` 字样。现名：窗口 label `catgirl`、app id `app.catgirl.desktop`、立绘侧标识符统一 `sprite`（`src/ui/sprite.ts` / `SpriteWindow` / `SpriteMood` / `SPRITE_SIZE` / `#sprite`）。改 `identifier` 会连带换 Tauri 用户数据目录（localStorage：设置/历史/锚点位置），2026-10-24 已把 `~/.local/share/app.catgirl.pet` 原样复制到 `app.catgirl.desktop`，旧目录留着没删。
- 权重和数据集都在仓库外的 `/home/labubu/30856/Model/`，不入库。

## 实测记录

2026-10-24：

- 混采管道 ctx 2048：90/90 行编码成功、0 行截断、`terminal_stop_supervised=90/90`、监督 token 33,093；图文样本行 300 token 含 192 个视觉 pad。
- ctx 300 压力：60 行里 8 行可用、3 行按轮次边界截断（`terminal_stop_supervised=5/8`），其余行报所需长度（493 / 826 / 808）后抛错。
- 基座权重：738/738 张量、4.66B、两个分片字节数与镜像 tree API 一致；数据集 4.2GB 也逐文件对齐，无 `.incomplete`。
- **桌面客户端**：`cargo build` 46.92s 通过，`target/debug/catgirl` 实机起窗（X11 `:0`），托盘走 libayatana-appindicator，启动打 deprecated 警告。
- **去"桌宠"改名清账**：`npx tsc --noEmit` 通过；`cargo check` 37.21s、`cargo build` 44.70s 通过，`target/debug/catgirl` 路径不变；`gen/schemas/capabilities.json` 已随 `cargo check` 重新生成为 `catgirl`；浏览器预览（`npm run dev` + 结构校验）`#sprite` 存在、`data-mood=offline`、`.sprite-body` 存在、根节点 `display:flex/align-items:flex-end`、残留 `.pet`/`#pet` 节点 0；全库 `桌宠` 与 `pet` 字样残留 0 处（排除 `node_modules`、`src-tauri/gen`）。**注意：in-app browser 无可见 surface（viewport 0x0），这次只做了 DOM/CSSOM 级校验，透明窗口与托盘仍未被肉眼看过。**

## 项目进度

- ✅ 语料 565 条 + 校验脚本
- ✅ 基座选型、参数分组、8GB 显存预算定稿
- ✅ `catgirl/` 前端重写为 Tauri + TypeScript，对话走 llama-server
- ✅ 桌面客户端可构建可启动
- ✅ 基座权重下载并校验
- ✅ 图文锚点数据 + 混采/格式转换管道入仓
- ⬜ 中文图文数据路线未定，`persona_hook()` 因此仍是恒等函数
- ⬜ 透明窗口 / 托盘 / 拖拽尚未被人肉眼判定过（进程起过，没看过渲染结果）
- ⬜ 训练入口脚本未写（无 train.py / yaml）
- ⬜ LoRA → 合并 → GGUF → llama-server 导出链路未验证：llama.cpp 侧要支持 `qwen3_5`（Gated DeltaNet + MTP）；`modelfiles/Modelfile` 的 `FROM` 仍指向上一版 DeepSeek GGUF，且桌面端已不走 Ollama
