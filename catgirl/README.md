# 猫娘 · Tauri + TypeScript

透明、置顶、能拖的桌面小人，接本机 `llama-server` 的 OpenAI 兼容接口。人设直接引用微调语料里的同一份 system prompt，训练和推理不会说两套话。

## 运行前提

客户端只认 llama-server，不再管 Ollama。先起服务：

```bash
/home/labubu/30856/Model/llama-cpp/build/bin/llama-server \
  -m /home/labubu/30856/Model/Qwen3.5-9B/Qwen3.5-9B-Q4_K_M.gguf \
  -a catgirl --port 8080
```

- `-a` 决定 `/v1/models` 里返回的别名；设置里可以指定别名，留空就取服务端返回的第一个。
- llama-server 的 `--cors-origins` 默认是 `*`，网页/桌面端跨源访问不用额外加参数。
- 服务没起也能打开窗口：状态点变红、立绘去色，发消息给一句中文提示，不会白屏。

## 开发

```bash
cd catgirl
npm install

npm run dev        # 纯浏览器预览：样式/对话/设置都能跑，窗口 API 自动跳过
npm run typecheck  # tsc --noEmit
npm run build      # tsc + vite build → dist/

npx tauri dev      # 真正的桌面窗口（透明、置顶、托盘）
npx tauri build
```

Linux 上编译 Rust 壳需要系统 C 库（cargo 管不到这层，得 apt 装）：`libdbus-1-dev`、`libgtk-3-dev`、`libwebkit2gtk-4.1-dev`、`libsoup-3.0-dev`、`libjavascriptcoregtk-4.1-dev`、`libayatana-appindicator3-dev`。图标已生成在 `src-tauri/icons/`，换形象后重跑：

```bash
npx tauri icon public/assets/catgirl_character.png
```

## 交互

| 操作 | 结果 |
|---|---|
| 左键点立绘 | 展开/收起对话面板 |
| 拖立绘 | 移动窗口（`data-tauri-drag-region`，位置存 `localStorage`） |
| 右键立绘 | 菜单：对话 / 设置 / 点击穿透 / 收进托盘 |
| `Ctrl+M` | 展开或收起（窗口有焦点时才收得到，系统级全局热键没接） |
| `Enter` / `Shift+Enter` / `Esc` | 发送 / 换行 / 打断当前回复或关菜单 |

**点击穿透打开后，webview 收不到任何鼠标事件，只能从托盘菜单恢复。** 托盘另有「显示 / 隐藏猫娘」和「退出」。

## 目录

```
catgirl/
├── index.html              页面骨架（无 CDN 依赖）
├── src/
│   ├── main.ts             装配：状态、事件、健康轮询
│   ├── styles.css          玻璃质感样式，替代原 Tailwind Play CDN
│   ├── types.ts            共享类型
│   ├── config/persona.ts   ?raw 引入 database/qwen_catgirl_ft/system_prompt.txt
│   ├── config/defaults.ts  默认设置、取值区间、开场白、存档校验
│   ├── services/llamaServer.ts  /v1/models + /v1/chat/completions SSE + 错误文案
│   ├── state/settings.ts   设置读写（localStorage）
│   ├── state/history.ts    对话存档与上下文窗口裁剪
│   └── ui/                 窗口几何 / 气泡对话 / 设置面板 / 右键菜单
├── public/assets/          立绘 PNG
└── src-tauri/              Rust 壳、tauri.conf.json、capabilities、icons
```

存档键：`catgirl.settings.v1`、`catgirl.history.v1`（最多 200 条）、`catgirl.anchor.v1`（立绘右下角锚点，物理像素）。

## 相对旧版前端砍掉的东西

- 好感度数值、情绪状态机、事件加成表、`【debug】` 输出 —— 这些写死在旧 `modelfiles/Modelfile` 里，和微调语料的傲娇口吻互相打架，删。
- 发色/瞳色/服装定制、模型训练面板与损失曲线：只有 UI 空壳，无实现。
- `hardwareAccel` / `memoryLimit` / `defaultModel: llama2`：Ollama 专属，随旧版 `launcher.py` 一起失效。
- `settings.html`、`model-config.html` 两个独立页面：合并成同一个设置标签页。
- Tailwind Play CDN、anime.js、Splitting.js、Google Fonts 四个外链：动画改用 CSS，字体走系统栈，离线可用。
- 对话导出成 JSON 文件：webview 里的下载路径不可靠，改成需要时从 `localStorage` 取。

## 与微调链路的接口

- 人设只有一份：`database/qwen_catgirl_ft/system_prompt.txt`，构建期通过 `?raw` 打进包，语料和客户端不可能说两套话。改人设改那个文件。
- 采样默认值取自语料 README 的推理建议：`temperature 0.8`、`top_p 0.9`、`repeat_penalty 1.05`、`max_tokens 256`（语料单条回复 50–200 字）。
- 上下文默认带 6 轮，语料单条 2–6 轮、system 340 字，仍在 2048 ctx 内。
- LoRA 合并导出成 GGUF 后，把上面 `llama-server -m` 换成你的文件即可，客户端不用改代码。

## 当前验证状态

已在真机 X11（2048×1280，单屏）上 `npx tauri dev` 跑起来看过：

- 窗口属性实测：`Depth: 32` + TrueColor 可视（ARGB 透明生效）、`_NET_WM_STATE` 带 `ABOVE / SKIP_TASKBAR / SKIP_PAGER`、收起态 200×200 贴右下角留 20px 边距、展开态 340×520 完整在屏内。
- 面板展开、标签切换、气泡与输入框布局、立绘渲染都截图确认过。
- WebKit 里 `fetch` 打 `/v1/models` 通（跨源，无 CORS 报错），健康轮询正常。
- `tsc --noEmit`、`vite build`、`cargo check`（tauri 2.12.5，0 warning）全通过。
- 真机跑这一轮抓出三个纯逻辑测试看不到的 bug，已修：`[hidden]` 被作者样式的 `display:flex` 盖掉导致面板和打字指示器常显；GTK 把窗口最小尺寸夹到 200×200 而定位按请求尺寸算，立绘被挤出屏幕；`setSize` 后立刻读 `outerSize()` 拿到的是旧尺寸，展开面板时定位差了一整个窗口。

仍未验证：

- **流式回复没在 WebKit 里点过**。这台机器没有 xdotool/xte，合成按键拿不到 GTK 键盘焦点，所以打字机效果只在 Chromium（Vite dev）里验证过；WebKitGTK 2.54 支持 `ReadableStream`，但没实测。
- 点击穿透、托盘菜单、多屏/高 DPI 下的锚点。
- 立绘只有 `catgirl_character.png` 在用，`catgirl_effection.png` 暂时没接线。
