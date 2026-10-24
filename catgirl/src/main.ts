import { LlamaServerError, listModels } from './services/llamaServer';
import { loadSettings, saveSettings } from './state/settings';
import type { Settings } from './types';
import { Chat } from './ui/chat';
import { ContextMenu } from './ui/contextMenu';
import { PetWindow } from './ui/pet';
import { SettingsPanel } from './ui/settingsPanel';

const HEALTH_POLL_MS = 20_000;

function must<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`缺少 #${id} 节点`);
  return element as T;
}

async function boot(): Promise<void> {
  const el = {
    panel: must<HTMLElement>('panel'),
    chatView: must<HTMLElement>('chatView'),
    settingsView: must<HTMLElement>('settingsView'),
    tabChat: must<HTMLButtonElement>('tabChat'),
    tabSettings: must<HTMLButtonElement>('tabSettings'),
    panelClose: must<HTMLButtonElement>('panelClose'),
    avatar: must<HTMLImageElement>('avatar'),
    dot: must<HTMLElement>('dot'),
    menu: must<HTMLUListElement>('menu'),
  };

  let settings = loadSettings();
  let models: string[] = [];
  let serverOnline: boolean | null = null;
  let isOpen = false;
  let idleTimer = 0;

  const pet = new PetWindow();
  pet.applyStyle(settings);

  const refreshModels = async (): Promise<string[]> => {
    models = await listModels(settings.serverUrl);
    return models;
  };

  const resolveModel = async (): Promise<string> => {
    if (settings.model) return settings.model;
    if (models.length === 0) await refreshModels();
    const first = models[0];
    if (!first) throw new LlamaServerError('服务端没有加载任何模型');
    return first;
  };

  const showTab = (tab: 'chat' | 'settings'): void => {
    el.chatView.hidden = tab !== 'chat';
    el.settingsView.hidden = tab !== 'settings';
    el.tabChat.classList.toggle('is-active', tab === 'chat');
    el.tabSettings.classList.toggle('is-active', tab === 'settings');
  };

  const setOpen = async (open: boolean, tab: 'chat' | 'settings' = 'chat'): Promise<void> => {
    isOpen = open;
    el.panel.hidden = !open;
    await pet.setPanelOpen(open);
    if (open) showTab(tab);
  };

  const resetIdle = (): void => {
    window.clearTimeout(idleTimer);
    if (settings.idleHideMinutes <= 0) return;
    idleTimer = window.setTimeout(() => void setOpen(false), settings.idleHideMinutes * 60_000);
  };

  const chat = new Chat({
    pet,
    getSettings: () => settings,
    resolveModel,
    onActivity: resetIdle,
  });
  chat.mount();

  new SettingsPanel(el.settingsView, {
    getSettings: () => settings,
    onChange: (next: Settings) => {
      settings = next;
      saveSettings(settings);
      pet.applyStyle(settings);
      models = [];
      resetIdle();
    },
    refreshModels,
    onClearChat: () => chat.clear(),
    onQuit: () => void pet.hide(),
  });

  const menu = new ContextMenu(el.menu);

  const toggleChat = async (): Promise<void> => {
    await setOpen(!isOpen);
    if (!isOpen) return;
    chat.focusInput();
    pet.poke();
    resetIdle();
  };

  el.avatar.addEventListener('click', () => void toggleChat());
  el.panelClose.addEventListener('click', () => void setOpen(false));
  el.tabChat.addEventListener('click', () => showTab('chat'));
  el.tabSettings.addEventListener('click', () => showTab('settings'));

  el.avatar.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    menu.show(event.clientX, event.clientY, [
      { label: isOpen ? '收起对话' : '打开对话', onSelect: () => void toggleChat() },
      { label: '设置', onSelect: () => void setOpen(true, 'settings') },
      {
        label: '点击穿透（只能从托盘恢复）',
        onSelect: () => void pet.setClickThrough(true),
      },
      { label: '收进托盘', onSelect: () => void pet.hide() },
    ]);
  });

  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey && event.key.toLowerCase() === 'm') {
      event.preventDefault();
      void toggleChat();
    }
  });

  await pet.init('idle');
  chat.greet();

  const probe = async (): Promise<void> => {
    let online = false;
    try {
      await refreshModels();
      online = true;
    } catch {
      models = [];
    }
    if (online === serverOnline) return;
    serverOnline = online;
    el.dot.dataset.state = online ? 'online' : 'offline';
    pet.setMood(online ? 'idle' : 'offline');
  };

  await probe();
  window.setInterval(() => void probe(), HEALTH_POLL_MS);
  resetIdle();
}

void boot();
