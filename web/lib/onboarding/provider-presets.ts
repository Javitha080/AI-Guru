/**
 * Provider presets for the AI Guru first-run setup wizard.
 *
 * Mirrors PROVIDER_DEFAULTS in
 * deeptutor/services/llm/provider_activation.py — the backend resolves the
 * same defaults when the request omits base_url/model/binding, so these two
 * tables must stay in sync.
 */

export type WizardMode = "auto" | "cloud" | "ollama" | "offline";

export type CloudProviderId = "openai" | "deepseek" | "anthropic" | "dashscope" | "custom";

export interface CloudProviderPreset {
  id: CloudProviderId;
  label: string;
  hint: string;
  baseUrl: string;
  binding: string;
  defaultModel: string;
  models: string[];
}

export const CLOUD_PROVIDER_PRESETS: CloudProviderPreset[] = [
  {
    id: "openai",
    label: "OpenAI",
    hint: "GPT models via platform.openai.com",
    baseUrl: "https://api.openai.com/v1",
    binding: "openai",
    defaultModel: "gpt-4o-mini",
    models: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    hint: "Cost-effective V3 / R1 models",
    baseUrl: "https://api.deepseek.com/v1",
    binding: "openai",
    defaultModel: "deepseek-chat",
    models: ["deepseek-chat", "deepseek-reasoner"],
  },
  {
    id: "anthropic",
    label: "Anthropic",
    hint: "Claude models via console.anthropic.com",
    baseUrl: "",
    binding: "anthropic",
    defaultModel: "claude-sonnet-4-5",
    models: ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
  },
  {
    id: "dashscope",
    label: "DashScope (Qwen)",
    hint: "Alibaba Qwen models, OpenAI-compatible endpoint",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    binding: "openai",
    defaultModel: "qwen-plus",
    models: ["qwen-plus", "qwen-turbo", "qwen-max"],
  },
  {
    id: "custom",
    label: "Custom OpenAI-compatible",
    hint: "Any server exposing an OpenAI-style chat API (vLLM, LM Studio, …)",
    baseUrl: "",
    binding: "openai",
    defaultModel: "",
    models: [],
  },
];

export function getPreset(id: CloudProviderId): CloudProviderPreset {
  return CLOUD_PROVIDER_PRESETS.find((preset) => preset.id === id) ?? CLOUD_PROVIDER_PRESETS[0];
}

export function isWizardMode(value: unknown): value is WizardMode {
  return value === "auto" || value === "cloud" || value === "ollama" || value === "offline";
}
