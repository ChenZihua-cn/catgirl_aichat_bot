import { PERSONA_PROMPT } from '../config/persona';
import { RANGES } from '../config/defaults';
import { formatError } from '../services/llamaServer';
import type { Settings } from '../types';

type NumericKey = { [K in keyof Settings]: Settings[K] extends number ? K : never }[keyof Settings];
type BooleanKey = 'usePersona' | 'animations';

const LABELS: Record<NumericKey, string> = {
  temperature: 'temperature',
  topP: 'top_p',
  repeatPenalty: 'repeat_penalty',
  maxTokens: '最长回复 token',
  historyTurns: '携带上下文轮数',
  avatarOpacity: '立绘不透明度',
  fontSize: '字号',
  idleHideMinutes: '空闲自动收起（分钟）',
};

export interface SettingsPanelDeps {
  getSettings: () => Settings;
  onChange: (next: Settings) => void;
  refreshModels: () => Promise<string[]>;
  onClearChat: () => void;
  onQuit: () => void;
}

export class SettingsPanel {
  private readonly statusLine = document.createElement('p');
  private readonly modelSelect = document.createElement('select');
  private readonly autoOption = document.createElement('option');

  constructor(
    private readonly root: HTMLElement,
    private readonly deps: SettingsPanelDeps,
  ) {
    this.statusLine.className = 'note';
    this.autoOption.value = '';
    this.autoOption.textContent = '自动（服务端第一个）';
    this.root.replaceChildren(this.buildForm());
    void this.reloadModels();
  }

  private commit(patch: Partial<Settings>): void {
    this.deps.onChange({ ...this.deps.getSettings(), ...patch });
  }

  private say(text: string): void {
    this.statusLine.textContent = text;
  }

  private buildForm(): HTMLElement {
    const form = document.createElement('div');
    form.className = 'form';
    const settings = this.deps.getSettings();

    form.append(this.urlField(settings.serverUrl));
    form.append(this.modelField());
    form.append(this.toggleField('使用训练语料的猫娘人设', 'usePersona', settings.usePersona));

    for (const key of Object.keys(RANGES) as NumericKey[]) {
      form.append(this.rangeField(key));
    }

    form.append(this.toggleField('启用动画', 'animations', settings.animations));
    form.append(this.personaDetails());
    form.append(this.actionRow());
    form.append(this.statusLine);
    return form;
  }

  private urlField(value: string): HTMLElement {
    const field = fieldShell('llama-server 地址');
    const input = document.createElement('input');
    input.type = 'text';
    input.value = value;
    input.placeholder = 'http://127.0.0.1:8080';
    input.addEventListener('change', () => {
      const trimmed = input.value.trim().replace(/\/+$/, '');
      if (!/^https?:\/\//.test(trimmed)) {
        this.say('地址需要以 http:// 或 https:// 开头');
        return;
      }
      this.commit({ serverUrl: trimmed });
      void this.reloadModels();
    });
    field.append(input);
    return field;
  }

  private modelField(): HTMLElement {
    const field = fieldShell('模型别名');
    this.modelSelect.append(this.autoOption);
    this.modelSelect.value = this.deps.getSettings().model;
    this.modelSelect.addEventListener('change', () => this.commit({ model: this.modelSelect.value }));
    field.append(this.modelSelect);
    return field;
  }

  private async reloadModels(): Promise<void> {
    try {
      const models = await this.deps.refreshModels();
      this.modelSelect.replaceChildren(this.autoOption, ...models.map(optionElement));
      this.modelSelect.value = this.deps.getSettings().model;
      this.say(models.length ? `在线：${models.length} 个模型` : '在线，但没有可用模型');
    } catch (error) {
      this.say(formatError(error));
    }
  }

  private rangeField(key: NumericKey): HTMLElement {
    const range = RANGES[key];
    const field = fieldShell(LABELS[key]);
    const row = document.createElement('div');
    row.className = 'field-row';

    const input = document.createElement('input');
    input.type = 'range';
    input.min = String(range.min);
    input.max = String(range.max);
    input.step = String(range.step);
    input.value = String(this.deps.getSettings()[key]);

    const output = document.createElement('output');
    output.textContent = input.value;
    input.addEventListener('input', () => {
      output.textContent = input.value;
      this.commit({ [key]: Number(input.value) } as Partial<Settings>);
    });

    row.append(output);
    field.append(row, input);
    return field;
  }

  private toggleField(label: string, key: BooleanKey, value: boolean): HTMLElement {
    const field = fieldShell(label);
    const row = document.createElement('div');
    row.className = 'field-row';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = value;
    input.addEventListener('change', () => this.commit({ [key]: input.checked }));
    row.append(input);
    field.append(row);
    return field;
  }

  private personaDetails(): HTMLElement {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = '当前人设（与训练语料同一份）';
    const body = document.createElement('p');
    body.className = 'note';
    body.textContent = PERSONA_PROMPT;
    details.append(summary, body);
    return details;
  }

  private actionRow(): HTMLElement {
    const actions = document.createElement('div');
    actions.className = 'form-actions';
    actions.append(
      button('重新读取模型', () => void this.reloadModels()),
      button('清空对话', () => this.deps.onClearChat()),
      button('退出', () => this.deps.onQuit()),
    );
    return actions;
  }
}

function fieldShell(label: string): HTMLElement {
  const field = document.createElement('div');
  field.className = 'field';
  const text = document.createElement('label');
  text.textContent = label;
  field.append(text);
  return field;
}

function optionElement(id: string): HTMLOptionElement {
  const option = document.createElement('option');
  option.value = id;
  option.textContent = id;
  return option;
}

function button(text: string, onClick: () => void): HTMLButtonElement {
  const element = document.createElement('button');
  element.className = 'ghost';
  element.type = 'button';
  element.textContent = text;
  element.addEventListener('click', onClick);
  return element;
}
