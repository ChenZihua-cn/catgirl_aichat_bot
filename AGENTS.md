# AGENTS.md — 本仓库作业规则

分工：**根 README.md 面向使用者，介绍项目、运行方式、操作和必要的数据/训练事实；所有机制解释、"别信什么/为什么会静默失效"写在这里。** 发现新的坑，写这个文件，不要在 README 里堆实现叙述。

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
- 视觉塔是否常驻会改显存结论（bf16 冻结约 +0.67GB），根 README「训练配置」的两条预算线就是区分这个的。

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

`finetune/mix_dataset.py` 已按上面这些实现。根 README「模型与微调」只留数据事实与跑法命令，实测数字记在本文件末尾的「实测记录」。

### 视觉锚点的两个判断

- **纯文本 loss 看不出视觉退化**，所以必须留图文评测集；仓库里那两个 test 分片（13,640 条）就是干这个的。别拿"文本 loss 正常"当没退化的证据。
- 目前**没有任何含中文的图文训练样本**（`ureader_cap` 实测 0% CJK）。三条路，还没定：
  1. 直接用现有英文图文当锚点——零额外工作，只保能力不教中文看图说话。
  2. `FreedomIntelligence/ALLaVA-4V-Chinese`：标注是真中文且 Apache-2.0，**但仓库只有 JSON，图片要另外从原版 `ALLaVA-4V` 取，而原版是 cc-by-nc-4.0**——许可按最弱的一环算，别只看那个 Apache 标签。
  3. 用本地已有的 Qwen3.5-9B + `mmproj-Qwen3.5-9B-f16.gguf` 给这些图重打成中文猫娘口吻描述：顺带把英文 VQA 腔和人设冲突一起解决，代价是要先跑通 llama-server 的批量推理。

## 数字的出处

`database/README.md` 已把训练建议指回根 README；旧的 **单卡 24G / lora_rank 32 / bsz 4** LLaMA-Factory 参数只留在 git 历史里。抄之前先确认卡，以根 README 的「基座」与「训练配置」为准。

## 事实与措辞纪律

- **不要用产物缺失反推"没跑过"**。`tauri dev` 走 `beforeDevCommand: npm run dev` + `devUrl`，根本不产出 `dist/`；`target/` 也可能被 clean 掉。用户说跑过就是跑过，要确认就自己启动看窗口，而不是拿目录状态驳回。
- **裸 `cargo build` 出的二进制不嵌前端资源**：Tauri v2 只在 `custom-protocol` feature（`tauri build` 路径）下才把 `dist/` 嵌进产物，平时直接跑 `target/debug/catgirl` 是去连 devUrl 的——vite 没开时页面空白。又因为窗口已改 `visible: false`、由前端定位后再 show，症状不是"白窗"而是**窗口永远不出现**（X11 里只有一个 10x10 的 UnMapped 壳）。实机自查要么 `npm run tauri dev`，要么 `npm run build` + 带 custom-protocol 重编。
- 环境/依赖类断言先重新探测再说（`pgrep` 之外还要注意 `pkill -f` 会匹配到自己的命令行，导致自杀式退出 143）。
- 一次性探针脚本（`_probe*.py`）用完就删，结论进 README；不要把没实现的占位函数留在仓库里。

## 仓库现状与 git

- `catgirl/` 是 Tauri + TypeScript 桌面客户端，用户正在重构，工作区里有大量既存改动。不要 `stash` / `checkout` / `reset` / `clean`，未获明确要求不 commit。
- **措辞纪律**：这个产品不是"桌宠"，是桌面虚拟女友（见 `REACTOR.md` §0）。注释、文档、UI 文案、标识符里都不要重新引入 `桌宠` 或 `pet` 字样。现名：窗口 label `catgirl`、app id `app.catgirl.desktop`、立绘侧标识符统一 `sprite`（`src/ui/sprite.ts` / `SpriteWindow` / `SpriteMood` / `SPRITE_SIZE` / `#sprite`）。改 `identifier` 会连带换 Tauri 用户数据目录（localStorage：设置/历史/锚点位置），2026-10-24 已把 `~/.local/share/app.catgirl.pet` 原样复制到 `app.catgirl.desktop`，旧目录留着没删。
- 权重和数据集都在仓库外的 `/home/labubu/30856/Model/`，不入库。

## 桌面客户端自查（X11 `:0`，无 xdotool，但 XTest 可用）

本机没有 `xdotool` / `xte`，python3 也没装 Xlib 绑定，但系统里有 `libXtst`：用 ctypes 调 `XTestFakeMotionEvent` / `XTestFakeButtonEvent` / `XTestFakeKeyEvent` 就能注入鼠标和键盘。键盘注入前必须确认猫娘是 `_NET_ACTIVE_WINDOW`（例如先触发二次实例恢复），点击输入框后还要等焦点事件落到 WebView 再发键；否则按键会落进前一个窗口。现在发送消息可以全脚本化。

- 找窗口 + 看尺寸：`xwininfo -root -tree | grep -i catgirl` 拿 id，再 `xwininfo -id 0x…`（几何）与 `xprop -id 0x… WM_NORMAL_HINTS`（min/max 提示）。**断言"setSize 生效了吗"必须看这两个，别信代码逻辑。**
- 看渲染：`DISPLAY=:0.0 import -window root -crop WxH+X+Y +repage /tmp/x.png` 然后 Read 那张图。**只裁窗口自己的区域**——桌面上开着微信和 QQ，整屏截图会把别人的内容捞进来。
- 量拖动要读 `xwininfo -id` 的 **Absolute upper-left 坐标差**，不要拿 `outerPosition()` 的返回值自证；`scaleFactor=1` 时实测 1:1 无漂移。
- 滚轮事件只有指针落在窗口的**输入形状**内才收得到：收起态要先把指针移到右下 200×200 里再 `XTestFakeButtonEvent(4/5)`，否则滚的是桌面。断言看 `#log.scrollTop`（用 WebKit inspector 或临时日志），别只看截图。
- 托盘图标不是 X11 窗口（StatusNotifier / AppIndicator），XTest 点不到，托盘菜单三项只能人工点；恢复路径可以用"hide + 启动第二个实例"间接验证（走的是同一个 `restore_window`）。
- 改 `src-tauri/tauri.conf.json` 会触发 `tauri dev` 重建并重启窗口，X11 window id 会变，脚本里别记死。

### 窗口级坑

- **Linux 用固定 surface，不做窗口伸缩**：init 时一次性 `setSize(364×720)`，之后开合面板只改 DOM（`#panel.hidden`）和一张 GDK input shape。收起时输入区是**右下角 200×200**（= `SPRITE_SIZE`），展开时是整窗。两者不同步的症状分别是"面板看得见、点不到"和"收起后透明区域还在吃桌面点击"。
- **input shape 用 `gtk_window.allocation()`，不是请求尺寸**：`set_panel_input` 按当前 allocation 算矩形；开合时前端用 `lastPanelInput` 跳过重复 IPC，恢复显示前清空该缓存，保证 hide/show 后重新应用一次。传空 region 不是"隐藏"，是整窗不吃事件，别拿它当收起。
- **固定表面能力由后端声明**：前端不再用 `navigator.platform` 猜平台；init 调 Rust 的 `uses_fixed_surface`，由编译目标决定走固定 surface 还是响应式路径。
- **非 Linux 走响应式路径**：收起 200×200；展开 364×520 起，按内容高度以 44px 台阶伸缩（240 下限、屏高−48 封顶）。改尺寸的顺序是先 `setPosition` 再 `setSize`，反了右下锚点会漂。要让 `setSize` 落地必须保持 `resizable: true`：`resizable: false` 会让 GTK 发布 min=max 的 `WM_NORMAL_HINTS`，前端所有 `setSize` 被 WM 静默拒掉；无边框靠 `decorations: false`，不是靠关掉 resizable。
- **拖拽是前端指针状态机，不是原生拖动**：`avatarDrag.ts` 用 `pointerdown/move/up` + 6px 阈值 + `event.screenX/screenY`，位移乘 `scaleFactor` 后 `setPosition(PhysicalPosition)`；拖动期间用一条 `geometry` Promise 串行化并丢弃旧 revision，否则连续 `setPosition` 会乱序抖动。**已经不用 `data-tauri-drag-region` / 原生 `start-dragging`**，对应 capability 已删除，别照旧配置推断实现。
- **点击与拖动互斥**：超过阈值拖完要在 `click` 里吞掉事件，否则松手会顺带开/收面板。
- **托盘"显示"之后 WM 会重置几何**：窗口被放回**可用区**正中，尺寸也可能打回配置值。Rust 端只发 `catgirl://restore` / `catgirl://hide`，前端在隐藏状态完成布局后再 show；不要再靠 `onResized` / `onMoved` 和居中坐标猜测系统操作。
- **透明现在不靠 WebKit 环境变量**：当前 `npm run tauri dev` / 构建产物都不设 `WEBKIT_*`，窗口是 32 位 ARGB、`transparent: true`。旧的"必须同时设 `WEBKIT_DISABLE_DMABUF_RENDERER` + `WEBKIT_DISABLE_COMPOSITING_MODE`"是上一版布局的结论，已不成立；再遇到不透明方块先查窗口深度与合成器，别条件反射加环境变量。
- **配置里的置顶不等于始终在最上层**：本机出现过 `_NET_WM_STATE_ABOVE` 仍在、窗口却被普通窗口盖住。当前只在 `WindowEvent::Focused(true)` 里重设 `set_always_on_top(true)`，`Focused(false)` 不处理；二次实例恢复已实测能重新置顶。要动这条先量清楚是否真被盖住，别在失焦分支里加对称逻辑。
- 旧代码曾把 WM 居中落点当成用户拖动存进 `catgirl.anchor.v1`。拖一次立绘即可覆盖，不必清存档。

## 对话与立绘状态

- **SSE 只是协议层流式，UI 不做增量渲染**：`streamChat` 把 `delta.content` 拼完，`chat.ts` 才 `say()` 一条完整气泡；期间立绘 `thinking`，出正文后 `talking`（2.4s 回 `idle`）。想要打字机效果，改的是 `chat.ts` 的 await 点，不是样式。
- 请求带 `reasoning_effort: 'none'`。正文为空但 `reasoningChars > 0` 时，先怀疑服务端没认这个参数（模型/后端可能忽略它），而不是调 `max_tokens`。
- 日志是普通 `overflow-y: auto` 容器（`overscroll-behavior: contain`），滚轮原生可用；打开面板、切回对话、新消息、清空后都 `scrollTop = scrollHeight`。别再按"日志不滚、只在顶部裁"去改布局。
- 四张 mood PNG（idle / thinking / talking / offline）在 init 前 `image.decode()` 预加载，避免切换闪白；`offline` 仅在 `activeMood === 'idle' && serverOnline === false` 时覆盖 idle。
- 右键菜单已移除（只剩 `contextmenu` 的默认行为拦截）；点击穿透没有入口，`setClickThrough` 只在恢复显示时被调用来复位。

## 实测记录

2026-10-24：

- 混采管道 ctx 2048：90/90 行编码成功、0 行截断、`terminal_stop_supervised=90/90`、监督 token 33,093；图文样本行 300 token 含 192 个视觉 pad。
- ctx 300 压力：60 行里 8 行可用、3 行按轮次边界截断（`terminal_stop_supervised=5/8`），其余行报所需长度（493 / 826 / 808）后抛错。
- 基座权重：738/738 张量、4.66B、两个分片字节数与镜像 tree API 一致；数据集 4.2GB 也逐文件对齐，无 `.incomplete`。
- **桌面客户端**：`cargo build` 46.92s 通过，`target/debug/catgirl` 实机起窗（X11 `:0`），托盘走 libayatana-appindicator，启动打 deprecated 警告。
- **去"桌宠"改名清账**：`npx tsc --noEmit` 通过；`cargo check` 37.21s、`cargo build` 44.70s 通过，`target/debug/catgirl` 路径不变；`gen/schemas/capabilities.json` 已随 `cargo check` 重新生成为 `catgirl`；浏览器预览（`npm run dev` + 结构校验）`#sprite` 存在、`data-mood=offline`、`.sprite-body` 存在、根节点 `display:flex/align-items:flex-end`、残留 `.pet`/`#pet` 节点 0；全库 `桌宠` 与 `pet` 字样残留 0 处（排除 `node_modules`、`src-tauri/gen`）。**注意：in-app browser 无可见 surface（viewport 0x0），这次只做了 DOM/CSSOM 级校验，透明窗口与托盘仍未被肉眼看过。**

2026-10-25：

- 桌面客户端 `npm run build`、`cargo check` 通过；实机窗口为 32 位 ARGB，Linux 固定 surface 364×720，收起后 GDK 输入形状为右下 200×200，展开为整窗。用户截图确认失焦时圆形透明区域正常，全程没设 `WEBKIT_*`。
- **XTest/libXtst 注入实机验收**：拖动位移与鼠标位移逐像素一致；开合面板连续 10 轮、标签切换连续 5 轮稳定，没有尺寸或输入形状残留；滚轮上下都能滚 `#log`。
- **流式终态**：用延迟 SSE 的假服务端把 delta 拆成多段，WebKit 里仍是流结束后才出现一条完整气泡，过程中只有 thinking 指示。
- **hide → 二次启动恢复**：窗口先 `catgirl://hide`，再启动第二个实例，几何与面板布局保留并被带回前台。
- 右键菜单已删；四张 mood 图已预加载接线。
- **未自动化**：托盘图标本身的左/右键和托盘菜单三项（AppIndicator 不是 X11 窗口，XTest 点不到），仍需人工验收。不要把"二次实例恢复已实测"写成"托盘菜单已实测"。

2026-10-29：

- **三源合并**：`database/` 成为唯一训练目录。原始 10,991 条 → 3,228 条（A 244/360、B 565/565、NekoQA 2,419/10,066）；5,375 条 gpt 回复、19 个场景、50–200 字；Qwen3.5-4B-Base 分词器计整文件 2,161,887 token（含 CoT）、纯对话 1,867,574 token。
- **NekoQA 不是日常聊天**：它是「猫娘问答」库（百科/写诗/职业建议/无厘头假设），清洗只能去格式垃圾。丢弃分布：长度 6,501、instruction 长度 505、角色错位 280、元提问 254、名字泄漏 52、禁用词 35、空行 14、残留占位 4、用户猫腔 2。入集仍占 74.9%，全库 62.5% 回复带猫娘口吻词；训练前按 `source` 降采样。
- **B 集 565 = 28 个批次 560 + `b_samples_5` 的 5 条**。后者不在批次里，只读批次会静默少 5 条。
- **严格 50–200 字**使 A 的 `微信短聊`（10 字体）20 条全灭、`接梗日常` 只剩 1 条；A 共 116 行因任一条回复 <50 字被丢。
- NekoQA 的 `用户:初始问题:` 前缀、`主人/宝宝` 称呼、`莉莉/小雪/小橘/咪咪` 自称、`本少爷/本小姐` 用户角色、`*星号动作*`、句尾 `的说` 都已清洗；`build.py` 自检不过直接失败，不写半成品。
- **CoT**：3,228 条全部补了隐藏内心独白（30–60 字，平均 39.6），由子代理按 `cot/PROMPT.md` 分块生成，`cot/cot.jsonl` 用 id 映射，顶层字段 `cot` 只对应最后一条 gpt。纯对话+CoT 1,975,004 token（整文件 2,161,887）。
- **CoT 对齐**：`<think>`/`</think>` 是单 token（248068/248069）；`mix_dataset.py` 构造的 id 序列已与 `apply_chat_template(..., enable_thinking=True)` 逐 token 比对通过。开头 `<think>\n` mask，独白+`</think>`+正文监督。客户端发 `chat_template_kwargs.enable_thinking=true` 并剥掉思考标签。
- **CoT 只加在最后一轮**：Qwen 模板只给「最后一条 user 之后」的 assistant 包 think，更早的 gpt 轮是历史，不加；否则模板与手动编码会分叉。
- 顶层 `cot` 是自定义字段，LLaMA-Factory 不认识；走 LLaMA-Factory 必须先注入最后一条 gpt 的 `<think>` 内容，或直接用 `mix_dataset.py`。

## 微信短聊语料（2026-10-30）

- 现行 `train.jsonl` 不是旧的 3,228 条长回复语料，而是 **1,652 条微信短聊**：A/B 改写 801 + NekoQA 551 + 新会话 300；旧 3,228 条只作为 `distill/source/legacy_train.jsonl` 的冻结候选池。
- 气泡分隔用 `\n\n`：Qwen3.5 分词器里是单 token（id 271），不改词表、不需要服务端开关。`system_prompt.txt` 有 6 个单换行、**没有空行**，不会污染分隔；单个气泡内部不出现 `\n\n`。
- 新会话 seed 是 `distill/seeds/all_scenes.jsonl`（p001–p300，`scenes.jsonl` + `scale_scenes.jsonl` 合并）；`tools/build_wechat.py` 的默认 `SEEDS` 已指向它。
- 构建命令：`python3 database/tools/build_wechat.py --from accepted --drop-missing-cot --drop-ids distill/review/drop_final_major.ids`。`--drop-missing-cot` 显式丢弃没有 CoT 的候选并打印数量；`--drop-ids` 丢弃最终审查确认不可单点修的 blocker/major 行。本次先丢 1,861 条缺 CoT 的 NekoQA，再丢 15 条审查行；最终 NekoQA 占 33.35%，低于 40%。CoT 重写后，那 15 条淘汰行也不再保留 CoT，重建会打印 1,876 条缺失、0 条 drop-ids，最终行数不变。
- 改写池接受 **3,228 条**（A/B 809 + NekoQA 2,419），覆盖全部旧语料；最终集只使用有 CoT 的候选。新会话 300 条，全部 1 次可验证 callback。
- 最终统计：5,577 个 assistant 轮 / 9,756 个气泡；单 41.96% / 双 41.30% / 三 16.60% / 四 0.14%；emoji 18.5%、问句 26.5%、猫娘 23.26%、本喵 6.2%；`long` 66 行（4.0%）；CoT 1,652 条（重写前 10–25 字、平均 20.6；重写后 8–24 字、平均 10.9，旧版备份 `distill/cot.jsonl.v1.bak`）。构建自检覆盖 system 逐字一致、role 交替、气泡长度/空串/`\n\n` 残留、禁用词、动作旁白、human 3–30、CoT 全覆盖、NekoQA ≤40%、long ≤5%。
- 全量审查走 `distill/review/REVIEW_PROTOCOL.md`：一个子代理顺序读 `train.jsonl` 到 EOF，写 `final_review.jsonl` + `.md`；0 blocker 才交付。该协议原名 `FINAL_REVIEW.md`，与审查产出 `final_review.md` 只差大小写，而本仓库 `.git/config` 里 `core.ignorecase=true`，两个名字进不了同一个索引（`git add` 直接 fatal），已改名；新文件别再用只差大小写的名字。
- 2026-10-30 子代理队列多次出现 `get_model_policy timeout` / 长时间排队；最终 186 条 NekoQA 的 CoT 没能在队列恢复前补齐，因此用 `--drop-missing-cot` 排除，而不是伪造 CoT。

### CoT 重写（2026-10-30）

- **旧 CoT 的单调不是写手失误，是规则造成的**：`wechat-cot-v1` 明确要求“先…再…最后…”的动作规划。实测 1,667 条里 95.4% 含“先”、97.3% 含“再”、66% 直接以“先”开头，问句/感叹/省略号均为 0，99.9% 含逗号、95% 以句号收尾。
- 已改为 `wechat-cot-v2`：写内心独白而非回复策略，允许心动、嘴硬、吐槽、心疼、担心、回忆、吃醋、得意、犹豫、自嘲、感官画面、碎念、联想、认命、反问；开头、句式、标点必须分散；长度从 10–25 放宽到 **8–40**（`tools/build_wechat.py:validate_cot` 同步改）。
- 新集 1,652 条全部唯一：以“先”开头 0.85%、含“先”5.1%、含“再”2.8%；问句 12.6%、感叹 1.6%、省略 2.7%、无句末标点 17.6%；8–24 字、平均 10.9；`他`/`你` 分别出现在 15.9%/16.6% 的条目里。REPORT.json 的 `cot` 字段记录 min/avg/max。
- 旧 CoT 备份在 `distill/cot.jsonl.v1.bak`；`--drop-ids` 的 15 条淘汰行不再保留 CoT，重建命令会打印 1,876 条缺失、0 条 drop-ids，最终 1,652 行不变。

### DeepSeek-R1-7B QLoRA 代理实验（2026-10-30）

- `Model/deepseek-r1_latest` 那个 4.9GB GGUF 是 **qwen3 架构的 8B 蒸馏**，不是官方 `deepseek-r1:7b`（Qwen2.5-7B distill）；要训 LoRA 必须下 HF 权重，GGUF/Ollama 只能推理。
- 官方 `deepseek-ai/DeepSeek-R1-Distill-Qwen-7B` 两个分片 8,606,596,466 / 6,624,675,384 字节，已放在 `Model/DeepSeek-R1-Distill-Qwen-7B`。4-bit 加载占 **5.71GB**，896 token 的 smoke 峰值 **7.50GB**，8GB 4060 Laptop 能跑。
- **别直接调 `prepare_model_for_kbit_training`**：它会把 embedding/lm_head 从 bf16 转 fp32，额外要 2GB，8GB 卡第一步就 OOM。改为手动冻结参数、只把 RMSNorm 转 fp32，并 `enable_input_require_grads()`。
- 800 条 / 1 epoch / 768 token / lr 2e-4：98 步、1,499s（约 15s/步）、峰值 **7.63GB**、train_loss 4.03；全量 1,652 约 50 分钟/epoch。适配器 155MB，在 `Model/LoRAs/deepseek-r1-7b-cot-qlora`。
- **896 token 全量 2 epoch 不稳**：跑到 step 193/404（约 50 分钟）时在 `paged_adamw_8bit` 的 `sync_gpu()` 崩 `CUDA illegal memory access`，当时显存 7.89GB/8.19GB，GPU 随后卡死（`nvidia-smi` D 状态），只能重启。768 token 的 800 条 1 epoch 已稳定跑完，恢复时优先 768；checkpoint-150 已保存，可 `--resume-adapter` 续跑。
- **全量 2 epoch（续跑）**：从 checkpoint-150 用 768 token 续 1.25 epoch，248 步、3,801s、峰值 7.63GB、末段 train_loss 2.82；累计约 2 epoch / 398 步。适配器 155MB，在 `Model/LoRAs/deepseek-r1-7b-cot-qlora-full2e-resume`。
- **效果对比（同一批 5 条留出，t=0.7）**：全量 adapter 比 800 条连贯（“今天真是累”→“累就早点睡 行吗”；“那我请半天假”→“谁要你请半天 / 跑就跑 本喵陪 / 别又睡到两点”），但仍会跑题或复读（“你笑什么”→“谁笑 你鱼贩子还没走”）；base 在 256 token 内还在 reasoning，没出正文。结论：7B QLoRA 可用于验证管线和数据风格，但还不是可上客户端的最终模型；要可用优先换 Qwen3.5-4B / 更 chat 的基座，或继续 3–5 epoch。
- 效果：LoRA 明显学会短气泡和猫娘口癖；800 条 1 epoch 的内容相关性仍弱，常复读训练片段。采样 `temperature=0.7` 比贪心自然；base 在 256 token 内还在 reasoning，没出正文。
- 脚本：`finetune/train_qlora.py`（手工拼 `<｜User｜>/<｜Assistant｜>` 序列，CoT 放 `<think>…</think>`，只监督 assistant 段）、`finetune/sample_qlora.py`（base/adapter 对比，支持 `--sample`）。未接入客户端，全量训练待定。

## 项目进度

- ✅ 微信短聊语料 1,652 条：A/B + NekoQA 改写 + 300 新会话 + 气泡格式 + CoT 全覆盖 + 全量审查通过（`database/`）
- ✅ CoT 重写为多样内心独白（1,652 条，8–24 字，问句 12.6%、无句末标点 17.6%，以“先”开头 0.85%）
- ✅ 旧三源 3,228 条冻结在 `distill/source/legacy_train.jsonl`，作为改写候选池
- ✅ 基座选型、参数分组、8GB 显存预算定稿
- ✅ `catgirl/` 前端重写为 Tauri + TypeScript，对话走 llama-server
- ✅ 桌面客户端可构建可启动
- ✅ 基座权重下载并校验
- ✅ 图文锚点数据 + 混采/格式转换管道入仓
- ⬜ 中文图文数据路线未定，`persona_hook()` 因此仍是恒等函数
- ⬜ 托盘图标本体的鼠标交互（AppIndicator，XTest 点不到）仍待人工验收；隐藏/显示事件路径与二次实例恢复已实测
- ⬜ 训练入口脚本未写（无 train.py / yaml）
- ⬜ LoRA → 合并 → GGUF → llama-server 导出链路未验证：llama.cpp 侧要支持 `qwen3_5`（Gated DeltaNet + MTP）；`modelfiles/Modelfile` 的 `FROM` 仍指向上一版 DeepSeek GGUF，且桌面端已不走 Ollama
