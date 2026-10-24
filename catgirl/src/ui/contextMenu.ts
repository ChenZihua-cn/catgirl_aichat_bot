export interface MenuItem {
  label: string;
  onSelect: () => void;
}

export class ContextMenu {
  constructor(private readonly root: HTMLUListElement) {
    document.addEventListener('pointerdown', (event) => {
      if (!root.contains(event.target as Node)) this.hide();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') this.hide();
    });
  }

  show(x: number, y: number, items: MenuItem[]): void {
    this.root.replaceChildren(
      ...items.map((item) => {
        const li = document.createElement('li');
        li.textContent = item.label;
        li.addEventListener('click', () => {
          this.hide();
          item.onSelect();
        });
        return li;
      }),
    );
    this.root.hidden = false;
    // 先显示才能量出自身尺寸，再夹回窗口内
    const rect = this.root.getBoundingClientRect();
    this.root.style.left = `${Math.max(0, Math.min(x, window.innerWidth - rect.width))}px`;
    this.root.style.top = `${Math.max(0, Math.min(y, window.innerHeight - rect.height))}px`;
  }

  hide(): void {
    this.root.hidden = true;
  }
}
