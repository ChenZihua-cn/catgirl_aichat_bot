import { PERSONA_PROMPT } from '../config/persona';
import { WELCOME_LINES } from '../config/defaults';
import { contextWindow, loadHistory, saveHistory } from '../state/history';
import { formatError, streamChat, type StreamResult } from '../services/llamaServer';
import type { ChatMessage, RequestMessage, Settings, SpriteMood } from '../types';
import { mustGet } from './dom';
import type { SpriteWindow } from './sprite';

export interface ChatDeps {
  sprite: SpriteWindow;
  getSettings: () => Settings;
  resolveModel: () => Promise<string>;
  setMood: (mood: Exclude<SpriteMood, 'offline'>) => void;
  onActivity: () => void;
}

const MAX_INPUT_HEIGHT = 84;

export class Chat {
  private history: ChatMessage[] = loadHistory();
  private busy = false;
  private inflight: AbortController | null = null;

  private readonly log = mustGet<HTMLDivElement>('log');
  private readonly input = mustGet<HTMLTextAreaElement>('input');
  private readonly sendButton = mustGet<HTMLButtonElement>('send');
  private readonly hint = mustGet<HTMLDivElement>('hint');
  private readonly typing = mustGet<HTMLDivElement>('typing');

  constructor(private readonly deps: ChatDeps) {}

  mount(): void {
    this.renderAll();

    this.sendButton.addEventListener('click', () => {
      if (this.busy) this.cancel();
      else void this.send();
    });

    this.input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void this.send();
      }
      if (event.key === 'Escape') this.cancel();
    });

    this.input.addEventListener('input', () => this.autoGrow());
  }

  focusInput(): void {
    this.input.focus();
    this.scrollToLatest();
  }

  scrollToLatest(): void {
    this.log.scrollTop = this.log.scrollHeight;
  }

  /** 无历史时补一句开场白，不走推理。 */
  greet(): void {
    if (this.history.length > 0) return;
    const line = WELCOME_LINES[Math.floor(Math.random() * WELCOME_LINES.length)];
    if (line) this.say({ role: 'assistant', content: line, ts: Date.now() });
  }

  cancel(): void {
    this.inflight?.abort();
  }

  clear(): void {
    this.cancel();
    this.history = [];
    saveHistory(this.history);
    this.log.replaceChildren();
    this.scrollToLatest();
    this.refitPanel();
  }

  private async send(): Promise<void> {
    const text = this.input.value.trim();
    if (!text || this.busy) return;

    const settings = this.deps.getSettings();
    this.input.value = '';
    this.autoGrow();
    this.setHint(null);
    this.say({ role: 'user', content: text, ts: Date.now() });
    this.deps.onActivity();

    const messages = this.requestMessages(settings);
    const controller = new AbortController();
    this.inflight = controller;
    this.busy = true;
    this.setBusyUi(true);
    this.deps.setMood('thinking');

    try {
      const result = await this.requestReply(settings, messages, controller.signal);
      this.showReply(result);
    } catch (error) {
      this.showFailure(error);
    } finally {
      this.inflight = null;
      this.busy = false;
      this.setBusyUi(false);
    }
  }

  private requestMessages(settings: Settings): RequestMessage[] {
    const context = contextWindow(this.history, settings.historyTurns);
    return settings.usePersona
      ? [{ role: 'system', content: PERSONA_PROMPT }, ...context]
      : context;
  }

  private async requestReply(
    settings: Settings,
    messages: RequestMessage[],
    signal: AbortSignal,
  ): Promise<StreamResult> {
    const model = await this.deps.resolveModel();
    return streamChat({
      baseUrl: settings.serverUrl,
      model,
      messages,
      sampling: {
        temperature: settings.temperature,
        topP: settings.topP,
        repeatPenalty: settings.repeatPenalty,
        maxTokens: settings.maxTokens,
      },
      signal,
    });
  }

  private showReply(result: StreamResult): void {
    const content = result.content.trim();
    if (!content) {
      this.setHint(emptyReplyHint(result));
      this.deps.setMood('idle');
      return;
    }
    this.say({ role: 'assistant', content, ts: Date.now() });
    this.deps.setMood('talking');
  }

  private showFailure(error: unknown): void {
    const message = error instanceof DOMException && error.name === 'AbortError'
      ? '已打断。'
      : formatError(error);
    this.setHint(message);
    this.deps.setMood('idle');
  }

  /** 只写历史与存档，不碰 DOM。 */
  private record(message: ChatMessage): void {
    this.history = [...this.history.slice(-199), message];
    saveHistory(this.history);
  }

  /** 记一条并立刻画出来。 */
  private say(message: ChatMessage): void {
    this.record(message);
    this.renderMessage(message);
    this.scrollToLatest();
    this.refitPanel();
  }

  private renderAll(): void {
    this.log.replaceChildren(...this.history.map((m) => createBubble(m)));
    this.scrollToLatest();
    this.refitPanel();
  }

  private renderMessage(message: ChatMessage): void {
    this.log.append(createBubble(message));
  }

  private setBusyUi(busy: boolean): void {
    this.sendButton.textContent = busy ? '停止' : '发送';
    this.typing.hidden = !busy;
  }

  private setHint(text: string | null): void {
    this.hint.textContent = text ?? '';
    this.hint.hidden = text === null;
    this.refitPanel();
  }

  private autoGrow(): void {
    this.input.style.height = 'auto';
    this.input.style.height = `${Math.min(this.input.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }

  private refitPanel(): void {
    this.deps.sprite.refit();
  }
}

function emptyReplyHint(result: StreamResult): string {
  if (result.reasoningChars > 0) {
    return '模型把本轮 token 全用在思考上了，请调高“最长回复 token”。';
  }
  if (result.finishReason === 'length') {
    return '回复达到 token 上限但没产出正文，请调高“最长回复 token”。';
  }
  return '她没接上话，检查 llama-server 的模型别名和上下文长度。';
}

function createBubble(message: ChatMessage): HTMLElement {
  const element = document.createElement('div');
  element.className = `msg msg--${message.role}`;
  element.textContent = message.content;
  return element;
}
