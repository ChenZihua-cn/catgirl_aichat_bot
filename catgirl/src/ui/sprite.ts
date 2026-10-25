import { invoke } from '@tauri-apps/api/core';
import { LogicalSize, PhysicalPosition } from '@tauri-apps/api/dpi';
import { getCurrentWindow, primaryMonitor } from '@tauri-apps/api/window';
import type { Settings, SpriteMood } from '../types';

export const SPRITE_SIZE = { width: 200, height: 200 };
export const PANEL_SIZE = { width: 364, height: 520 };

const ANCHOR_KEY = 'catgirl.anchor.v1';
const RESTORE_EVENT = 'catgirl://restore';
const HIDE_EVENT = 'catgirl://hide';
const EDGE_MARGIN = 20;
const PANEL_MIN_HEIGHT = 240;
const SCREEN_TOP_MARGIN = 48;
const FIT_STEP_PX = 44;
const FIT_COALESCE_MS = 120;
const FIXED_SURFACE_HEIGHT = 720;
const MOOD_SOURCES: Record<SpriteMood, string> = {
  idle: '/assets/moods/idle.png',
  thinking: '/assets/moods/thinking.png',
  talking: '/assets/moods/talking.png',
  offline: '/assets/moods/offline.png',
};

const IS_TAURI = '__TAURI_INTERNALS__' in window;

const win = (() => {
  let cached: ReturnType<typeof getCurrentWindow> | null = null;
  return () => (cached ??= getCurrentWindow());
})();

interface Anchor {
  x: number;
  y: number;
}

interface DragOrigin {
  cursor: Anchor;
  position: Anchor;
  width: number;
  height: number;
  scale: number;
}

interface WorkArea {
  x: number;
  y: number;
  width: number;
  height: number;
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
    return null;
  }
  return null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function cssPixels(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

async function preloadMoods(): Promise<void> {
  await Promise.all(
    Object.values(MOOD_SOURCES).map(async (source) => {
      const image = new Image();
      image.src = source;
      await image.decode();
    }),
  );
}

export class SpriteWindow {
  private anchor: Anchor = { x: 0, y: 0 };
  private dragOrigin: DragOrigin | null = null;
  private dragRevision = 0;
  private workArea: WorkArea | null = null;
  private fixedSurface = false;
  private lastPanelInput: boolean | null = null;
  private maxHeight = PANEL_SIZE.height;
  private fitting = false;
  private fitTimer = 0;
  private pokeTimer = 0;
  private geometry: Promise<void> = Promise.resolve();
  private geometryRevision = 0;
  private lastSize: { width: number; height: number } | null = null;
  private lastPosition: Anchor | null = null;
  private readonly moodsReady = preloadMoods();

  async init(mood: SpriteMood): Promise<void> {
    await this.moodsReady;
    this.fixedSurface = IS_TAURI ? await invoke<boolean>('uses_fixed_surface') : false;
    const screen = await this.readScreen();
    this.anchor = readAnchor() ?? screen.anchor;
    this.workArea = screen.area;
    this.maxHeight = screen.maxHeight;
    this.setMood(mood);
    if (this.fixedSurface) {
      await this.resize(PANEL_SIZE.width, Math.min(this.maxHeight, FIXED_SURFACE_HEIGHT));
    } else {
      await this.resize(SPRITE_SIZE.width, SPRITE_SIZE.height);
    }

    if (!IS_TAURI) return;
    await win().show();
    if (this.fixedSurface) await this.setPanelInput(false);
    await win().listen(RESTORE_EVENT, () => void this.showAndFocus());
    await win().listen(HIDE_EVENT, () => void this.hide());
  }

  async syncPanelSize(): Promise<void> {
    const panel = document.getElementById('panel');
    const open = panel !== null && !panel.hidden;
    if (this.fixedSurface) {
      await this.setPanelInput(open);
      return;
    }
    await this.syncResponsiveSize(open);
  }

  private async syncResponsiveSize(open: boolean): Promise<void> {
    const chatView = document.getElementById('chatView');
    this.fitting = open && chatView !== null && !chatView.hidden;
    if (!open) {
      this.cancelRefit();
      await this.resize(SPRITE_SIZE.width, SPRITE_SIZE.height);
      return;
    }
    if (!this.fitting) {
      window.clearTimeout(this.fitTimer);
      this.fitTimer = 0;
      await this.resize(PANEL_SIZE.width, PANEL_SIZE.height);
      return;
    }
    await this.applyFitHeight();
  }

  refit(): void {
    if (!this.fitting || this.fitTimer) return;
    this.fitTimer = window.setTimeout(() => {
      this.fitTimer = 0;
      if (this.fitting) void this.applyFitHeight();
    }, FIT_COALESCE_MS);
  }

  async beginDrag(screenX: number, screenY: number): Promise<void> {
    if (!IS_TAURI) return;
    const revision = ++this.dragRevision;
    this.dragOrigin = null;
    const [position, size, scale] = await Promise.all([
      win().outerPosition(),
      win().outerSize(),
      win().scaleFactor(),
    ]);
    if (revision !== this.dragRevision) return;
    this.dragOrigin = {
      cursor: { x: screenX, y: screenY },
      position: { x: position.x, y: position.y },
      width: size.width,
      height: size.height,
      scale,
    };
  }

  dragTo(screenX: number, screenY: number): void {
    const origin = this.dragOrigin;
    if (!origin) return;
    const position = this.constrainPosition(
      {
        x: Math.round(origin.position.x + (screenX - origin.cursor.x) * origin.scale),
        y: Math.round(origin.position.y + (screenY - origin.cursor.y) * origin.scale),
      },
      origin.width,
      origin.height,
      1,
    );
    this.anchor = { x: position.x + origin.width, y: position.y + origin.height };
    this.lastPosition = position;
    void this.queueGeometry(async () => {
      await win().setPosition(new PhysicalPosition(position.x, position.y));
    });
  }

  async endDrag(): Promise<void> {
    if (!IS_TAURI) return;
    ++this.dragRevision;
    await this.geometry;
    this.dragOrigin = null;
    localStorage.setItem(ANCHOR_KEY, JSON.stringify(this.anchor));
  }

  private async setPanelInput(open: boolean): Promise<void> {
    if (this.lastPanelInput === open) return;
    await invoke('set_panel_input', { open, spriteSize: SPRITE_SIZE.width });
    this.lastPanelInput = open;
  }

  async setClickThrough(enabled: boolean): Promise<void> {
    document.body.dataset.through = enabled ? 'on' : 'off';
    if (IS_TAURI) await win().setIgnoreCursorEvents(enabled);
  }

  async hide(): Promise<void> {
    this.cancelRefit();
    if (IS_TAURI) await win().hide();
  }

  async showAndFocus(): Promise<void> {
    if (!IS_TAURI) return;
    this.cancelRefit();
    this.lastSize = null;
    this.lastPosition = null;
    this.lastPanelInput = null;
    await this.setClickThrough(false);
    await this.syncPanelSize();
    await win().show();
    await win().setFocus();
  }

  setMood(mood: SpriteMood): void {
    const root = document.getElementById('sprite');
    const avatar = document.getElementById('avatar');
    if (root?.dataset.mood === mood) return;
    if (root) root.dataset.mood = mood;
    if (avatar instanceof HTMLImageElement) avatar.src = MOOD_SOURCES[mood];
  }

  poke(): void {
    const body = document.querySelector<HTMLElement>('.sprite-body');
    if (!body) return;
    window.clearTimeout(this.pokeTimer);
    body.classList.remove('poke');
    void body.offsetWidth;
    body.classList.add('poke');
    this.pokeTimer = window.setTimeout(() => body.classList.remove('poke'), 600);
  }

  applyStyle(settings: Settings): void {
    const root = document.documentElement;
    root.style.setProperty('--font-size', `${settings.fontSize}px`);
    root.style.setProperty('--avatar-opacity', String(settings.avatarOpacity / 100));
    document.body.dataset.animations = settings.animations ? 'on' : 'off';
  }

  private cancelRefit(): void {
    window.clearTimeout(this.fitTimer);
    this.fitTimer = 0;
    this.fitting = false;
  }

  private async applyFitHeight(): Promise<void> {
    if (!this.fitting) return;
    const stepped = Math.ceil(this.desiredHeight() / FIT_STEP_PX) * FIT_STEP_PX;
    const target = Math.round(clamp(stepped, PANEL_MIN_HEIGHT, this.maxHeight));
    await this.resize(PANEL_SIZE.width, target);
  }

  private desiredHeight(): number {
    const panel = document.getElementById('panel');
    const log = document.getElementById('log');
    const body = document.querySelector<HTMLElement>('.sprite-body');
    if (!panel || !log || !body) return PANEL_SIZE.height;
    const shell = panel.offsetHeight - log.offsetHeight + body.offsetHeight;
    return Math.ceil(shell + this.spriteChromeHeight() + this.logContentHeight(log));
  }

  private spriteChromeHeight(): number {
    const sprite = document.getElementById('sprite');
    if (!sprite) return 0;
    const style = window.getComputedStyle(sprite);
    return cssPixels(style.paddingTop) + cssPixels(style.paddingBottom) + cssPixels(style.rowGap);
  }

  private logContentHeight(log: HTMLElement): number {
    const style = window.getComputedStyle(log);
    const gap = cssPixels(style.rowGap);
    const padding = cssPixels(style.paddingTop) + cssPixels(style.paddingBottom);
    const children = Array.from(log.children) as HTMLElement[];
    const bubbles = children.reduce((sum, element) => sum + element.offsetHeight, 0);
    const gaps = children.length > 1 ? gap * (children.length - 1) : 0;
    return bubbles + gaps + padding;
  }

  private constrainPosition(
    position: Anchor,
    width: number,
    height: number,
    scale: number,
  ): Anchor {
    if (!this.workArea) return position;
    const area = this.workArea;
    return {
      x: Math.round(clamp(position.x, area.x, Math.max(area.x, area.x + area.width - width * scale))),
      y: Math.round(clamp(position.y, area.y, Math.max(area.y, area.y + area.height - height * scale))),
    };
  }

  private queueGeometry(task: (isCurrent: () => boolean) => Promise<void>): Promise<void> {
    const revision = ++this.geometryRevision;
    const operation = this.geometry.then(async () => {
      const isCurrent = (): boolean => revision === this.geometryRevision;
      if (!isCurrent()) return;
      await task(isCurrent);
    });
    this.geometry = operation.catch(() => undefined);
    return operation;
  }

  private resize(width: number, height: number): Promise<void> {
    if (!IS_TAURI) return Promise.resolve();
    return this.queueGeometry(async (isCurrent) => {
      const scale = await win().scaleFactor();
      const position = this.constrainPosition(
        {
          x: Math.round(this.anchor.x - width * scale),
          y: Math.round(this.anchor.y - height * scale),
        },
        width,
        height,
        scale,
      );
      const sizeChanged =
        !this.lastSize || this.lastSize.width !== width || this.lastSize.height !== height;
      const positionChanged =
        !this.lastPosition || this.lastPosition.x !== position.x || this.lastPosition.y !== position.y;
      if (!sizeChanged && !positionChanged) return;

      await win().setPosition(new PhysicalPosition(position.x, position.y));
      if (!isCurrent()) return;
      if (sizeChanged) await win().setSize(new LogicalSize(width, height));
      this.lastSize = { width, height };
      this.lastPosition = position;
    });
  }

  private async readScreen(): Promise<{ anchor: Anchor; maxHeight: number; area: WorkArea }> {
    const scale = IS_TAURI ? await win().scaleFactor() : window.devicePixelRatio;
    const monitor = IS_TAURI ? await primaryMonitor() : null;
    const area = monitor
      ? {
          x: monitor.workArea.position.x,
          y: monitor.workArea.position.y,
          width: monitor.workArea.size.width,
          height: monitor.workArea.size.height,
        }
      : { x: 0, y: 0, width: window.screen.width * scale, height: window.screen.height * scale };
    return {
      anchor: {
        x: Math.round(area.x + area.width - EDGE_MARGIN),
        y: Math.round(area.y + area.height - EDGE_MARGIN),
      },
      maxHeight: Math.round(area.height / scale - SCREEN_TOP_MARGIN),
      area,
    };
  }
}
