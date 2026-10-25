import { invoke } from '@tauri-apps/api/core';
import { LlamaServerError, listModels } from './services/llamaServer';
import { loadSettings, saveSettings } from './state/settings';
import type { Settings, SpriteMood } from './types';
import { bindAvatarPointer } from './ui/avatarDrag';
import { Chat } from './ui/chat';
import { mustGet } from './ui/dom';
import { SpriteWindow } from './ui/sprite';
import { SettingsPanel } from './ui/settingsPanel';

const HEALTH_POLL_MS = 20_000;
const TALKING_MOOD_MS = 2400;

type ActiveMood = Exclude<SpriteMood, 'offline'>;

async function boot(): Promise<void> {
  const el = {
    panel: mustGet<HTMLElement>('panel'),
    chatView: mustGet<HTMLElement>('chatView'),
    settingsView: mustGet<HTMLElement>('settingsView'),
    tabChat: mustGet<HTMLButtonElement>('tabChat'),
    tabSettings: mustGet<HTMLButtonElement>('tabSettings'),
    panelClose: mustGet<HTMLButtonElement>('panelClose'),
    avatar: mustGet<HTMLImageElement>('avatar'),
    dot: mustGet<HTMLElement>('dot'),
  };

  let settings = loadSettings();
  let models: string[] = [];
  let serverOnline: boolean | null = null;
  let activeMood: ActiveMood = 'idle';
  let isOpen = false;
  let idleTimer = 0;
  let talkingTimer = 0;

  const sprite = new SpriteWindow();
  sprite.applyStyle(settings);

  const updateMood = (): void => {
    const mood = activeMood === 'idle' && serverOnline === false ? 'offline' : activeMood;
    sprite.setMood(mood);
  };

  const setActiveMood = (mood: ActiveMood): void => {
    window.clearTimeout(talkingTimer);
    activeMood = mood;
    updateMood();
    if (mood !== 'talking') return;
    talkingTimer = window.setTimeout(() => setActiveMood('idle'), TALKING_MOOD_MS);
  };

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

  const showTab = async (tab: 'chat' | 'settings'): Promise<void> => {
    el.chatView.hidden = tab !== 'chat';
    el.settingsView.hidden = tab !== 'settings';
    el.tabChat.classList.toggle('is-active', tab === 'chat');
    el.tabSettings.classList.toggle('is-active', tab === 'settings');
    await sprite.syncPanelSize();
  };

  const setOpen = async (open: boolean, tab: 'chat' | 'settings' = 'chat'): Promise<void> => {
    isOpen = open;
    el.panel.hidden = !open;
    if (open) await showTab(tab);
    else await sprite.syncPanelSize();
  };

  const resetIdle = (): void => {
    window.clearTimeout(idleTimer);
    if (settings.idleHideMinutes <= 0) return;
    idleTimer = window.setTimeout(() => void setOpen(false), settings.idleHideMinutes * 60_000);
  };

  const chat = new Chat({
    sprite,
    getSettings: () => settings,
    resolveModel,
    setMood: setActiveMood,
    onActivity: resetIdle,
  });
  chat.mount();

  new SettingsPanel(el.settingsView, {
    getSettings: () => settings,
    onChange: (next: Settings) => {
      settings = next;
      saveSettings(settings);
      sprite.applyStyle(settings);
      models = [];
      resetIdle();
    },
    refreshModels,
    onClearChat: () => chat.clear(),
    onQuit: () => void invoke('quit_app'),
  });

  const toggleChat = async (): Promise<void> => {
    await setOpen(!isOpen);
    if (!isOpen) return;
    chat.focusInput();
    sprite.poke();
    resetIdle();
  };

  bindAvatarPointer(el.avatar, sprite, () => void toggleChat());
  el.panelClose.addEventListener('click', () => void setOpen(false));
  el.tabChat.addEventListener('click', () => {
    void showTab('chat').then(() => chat.scrollToLatest());
  });
  el.tabSettings.addEventListener('click', () => void showTab('settings'));
  el.avatar.addEventListener('contextmenu', (event) => event.preventDefault());

  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey && event.key.toLowerCase() === 'm') {
      event.preventDefault();
      void toggleChat();
    }
  });

  await sprite.init('idle');
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
    updateMood();
  };

  await probe();
  window.setInterval(() => void probe(), HEALTH_POLL_MS);
  resetIdle();
}

void boot();
