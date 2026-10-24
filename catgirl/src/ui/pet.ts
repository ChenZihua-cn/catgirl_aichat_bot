import { LogicalSize, PhysicalPosition } from '@tauri-apps/api/dpi';
import { getCurrentWindow, primaryMonitor } from '@tauri-apps/api/window';
import type { PetMood, Settings } from '../types';

export const PET_SIZE = { width: 168, height: 152 };
export const PANEL_SIZE = { width: 340, height: 520 };

const ANCHOR_KEY = 'catgirl.anchor.v1';
const EDGE_MARGIN = 20;
/** setSize 会连带触发 moved 事件，这段时间内不要把它当成用户拖动。 */
const RESIZE_GUARD_MS = 250;

/** 用 `npm run dev` 在普通浏览器里预览时，窗口 API 不可用，只跑样式与对话。 */
const IS_TAURI = '__TAURI_INTERNALS__' in window;

const sleep = (ms: number): Promise<void> => new Promise((resolve) => window.setTimeout(resolve, ms));

const win = (() => {  let cached: ReturnType<typeof getCurrentWindow> | null = null;
  // 顶层直接调用会在普通浏览器里抛错，所以只在 Tauri 环境内取句柄
  return () => (cached ??= getCurrentWindow());
})();

interface Anchor {
  x: number;
  y: number;
}

function readAnchor(): Anchor | null {
  const raw = localStorage.getItem(ANCHOR_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<Anchor>;
    if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') {
      return { x: parsed.x, y: parsed.y };
    }
  } catch {
    // 位置存档坏了就当没存过
  }
  return null;
}

export class PetWindow {
  private anchor: Anchor = { x: 0, y: 0 };
  private lastResize = 0;
  private persistTimer = 0;

  async init(mood: PetMood): Promise<void> {
    this.anchor = readAnchor() ?? (await this.defaultAnchor());
    await this.resize(PET_SIZE.width, PET_SIZE.height);
    this.setMood(mood);

    if (!IS_TAURI) return;
    await win().onMoved(() => {
      if (Date.now() - this.lastResize < RESIZE_GUARD_MS) return;
      void this.rememberAnchor();
    });
  }

  /** 面板展开时窗口变高变宽，立绘始终钉在右下角，所以向左上扩张。 */
  async setPanelOpen(open: boolean): Promise<void> {
    const size = open ? PANEL_SIZE : PET_SIZE;
    await this.resize(size.width, size.height);
  }

  async setClickThrough(enabled: boolean): Promise<void> {
    document.body.dataset.through = enabled ? 'on' : 'off';
    if (IS_TAURI) await win().setIgnoreCursorEvents(enabled);
  }

  async hide(): Promise<void> {
    await this.setPanelOpen(false);
    if (IS_TAURI) await win().hide();
  }

  async showAndFocus(): Promise<void> {
    if (!IS_TAURI) return;
    await win().show();
    await win().setFocus();
  }

  setMood(mood: PetMood): void {
    const pet = document.getElementById('pet');
    if (pet) pet.dataset.mood = mood;
  }

  poke(): void {
    const avatar = document.getElementById('avatar');
    if (!avatar) return;
    avatar.classList.remove('poke');
    // 重启动画需要一个回流间隙
    void avatar.offsetWidth;
    avatar.classList.add('poke');
    window.setTimeout(() => avatar.classList.remove('poke'), 600);
  }

  applyStyle(settings: Settings): void {
    const root = document.documentElement;
    root.style.setProperty('--font-size', `${settings.fontSize}px`);
    root.style.setProperty('--avatar-opacity', String(settings.avatarOpacity / 100));
    document.body.dataset.animations = settings.animations ? 'on' : 'off';
  }

  private async resize(width: number, height: number): Promise<void> {
    if (!IS_TAURI) return;
    this.lastResize = Date.now();
    await win().setSize(new LogicalSize(width, height));
    await this.snapToAnchor();
  }

  /** GTK 的尺寸变更是异步落地的，等外框尺寸稳定后再按锚点贴回去。 */
  private async snapToAnchor(): Promise<void> {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      const size = await win().outerSize();
      await win().setPosition(new PhysicalPosition(this.anchor.x - size.width, this.anchor.y - size.height));
      await sleep(30);
      const settled = await win().outerSize();
      if (settled.width === size.width && settled.height === size.height) return;
    }
  }

  private async defaultAnchor(): Promise<Anchor> {
    const scale = IS_TAURI ? await win().scaleFactor() : window.devicePixelRatio;
    const monitor = IS_TAURI ? await primaryMonitor() : null;
    if (!monitor) {
      return {
        x: window.screen.width * scale - EDGE_MARGIN,
        y: window.screen.height * scale - EDGE_MARGIN,
      };
    }
    return {
      x: monitor.position.x + monitor.size.width - EDGE_MARGIN,
      y: monitor.position.y + monitor.size.height - EDGE_MARGIN,
    };
  }

  private async rememberAnchor(): Promise<void> {
    const position = await win().outerPosition();
    const size = await win().outerSize();
    this.anchor = { x: position.x + size.width, y: position.y + size.height };

    window.clearTimeout(this.persistTimer);
    this.persistTimer = window.setTimeout(() => {
      localStorage.setItem(ANCHOR_KEY, JSON.stringify(this.anchor));
    }, 200);
  }
}
