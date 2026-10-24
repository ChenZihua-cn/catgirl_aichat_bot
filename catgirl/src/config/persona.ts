import personaRaw from '../../../database/qwen_catgirl_ft/system_prompt.txt?raw';

/**
 * 与微调语料共用同一份人设原文：训练时喂什么，推理时就发什么。
 * 改人设请改 database/qwen_catgirl_ft/system_prompt.txt，不要在这里复制粘贴。
 */
export const PERSONA_PROMPT = personaRaw.trim();
