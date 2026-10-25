import type { SpriteWindow } from './sprite';

const DRAG_THRESHOLD_PX = 6;

interface Point {
  x: number;
  y: number;
}

export function bindAvatarPointer(
  avatar: HTMLImageElement,
  sprite: SpriteWindow,
  onActivate: () => void,
): void {
  let start: Point | null = null;
  let latest: Point | null = null;
  let dragging = false;
  let dragReady = false;
  let suppressClick = false;

  const beginDrag = async (point: Point): Promise<void> => {
    await sprite.beginDrag(point.x, point.y);
    if (start !== point || !dragging || !latest) return;
    dragReady = true;
    sprite.dragTo(latest.x, latest.y);
  };

  const resetDrag = (): boolean => {
    const wasDragging = dragging;
    start = null;
    latest = null;
    dragging = false;
    dragReady = false;
    return wasDragging;
  };

  const finishDrag = (): void => {
    const wasDragging = resetDrag();
    suppressClick = wasDragging;
    if (wasDragging) void sprite.endDrag();
  };

  avatar.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    start = { x: event.screenX, y: event.screenY };
    latest = start;
    dragging = false;
    dragReady = false;
    suppressClick = false;
    avatar.setPointerCapture(event.pointerId);
  });

  avatar.addEventListener('pointermove', (event) => {
    if (!start) return;
    latest = { x: event.screenX, y: event.screenY };
    if (!dragging) {
      if (Math.hypot(latest.x - start.x, latest.y - start.y) < DRAG_THRESHOLD_PX) return;
      dragging = true;
      void beginDrag(start);
      return;
    }
    if (dragReady) sprite.dragTo(latest.x, latest.y);
  });

  window.addEventListener('pointerup', finishDrag);
  window.addEventListener('pointercancel', () => {
    const wasDragging = resetDrag();
    suppressClick = false;
    if (wasDragging) void sprite.endDrag();
  });

  avatar.addEventListener('click', (event) => {
    if (suppressClick) {
      event.preventDefault();
      return;
    }
    onActivate();
  });
}
