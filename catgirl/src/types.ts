export type Role = 'user' | 'assistant';

export interface ChatMessage {
  role: Role;
  content: string;
  ts: number;
}

/** 发给 /v1/chat/completions 的消息，比历史记录多一个 system 角色。 */
export interface RequestMessage {
  role: 'system' | Role;
  content: string;
}

export type PetMood = 'idle' | 'thinking' | 'talking' | 'offline';

export interface Settings {
  /** llama-server 基地址，默认端口 8080 */
  serverUrl: string;
  /** /v1/models 里的模型别名；留空则用服务端返回的第一个 */
  model: string;
  usePersona: boolean;
  temperature: number;
  topP: number;
  repeatPenalty: number;
  maxTokens: number;
  /** 携带的历史轮数（一问一答算一轮） */
  historyTurns: number;
  /** 立绘不透明度，40–100 */
  avatarOpacity: number;
  fontSize: number;
  animations: boolean;
  /** 空闲多少分钟后自动收起面板，0 = 不自动收起 */
  idleHideMinutes: number;
}

export interface Sampling {
  temperature: number;
  topP: number;
  repeatPenalty: number;
  maxTokens: number;
}
