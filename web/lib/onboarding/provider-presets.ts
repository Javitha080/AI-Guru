/**
 * Provider presets for the AI Guru first-run setup wizard.
 *
 * Mirrors PROVIDER_DEFAULTS in
 * deeptutor/services/llm/provider_activation.py — the backend resolves the
 * same defaults when the request omits base_url/model/binding, so these two
 * tables must stay in sync.
 */

export type WizardMode = "auto" | "cloud" | "ollama" | "offline";

export type CloudProviderId =
  | "openai"
  | "deepseek"
  | "anthropic"
  | "dashscope"
  | "gemini"
  | "groq"
  | "openrouter"
  | "custom";

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
    id: "gemini",
    label: "Gemini",
    hint: "Google Gemini with a free AI Studio key; thinking shown in chat",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    binding: "gemini",
    defaultModel: "gemini-2.5-flash",
    models: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"],
  },
  {
    id: "groq",
    label: "Groq",
    hint: "Fast free-tier inference (Llama, Qwen, GPT-OSS)",
    baseUrl: "https://api.groq.com/openai/v1",
    binding: "groq",
    defaultModel: "llama-3.3-70b-versatile",
    models: [
      "llama-3.3-70b-versatile",
      "openai/gpt-oss-20b",
      "qwen/qwen3-32b",
      "deepseek-r1-distill-llama-70b",
    ],
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    hint: "One key for many models, including free :free variants",
    baseUrl: "https://openrouter.ai/api/v1",
    binding: "openrouter",
    defaultModel: "meta-llama/llama-3.3-70b-instruct:free",
    models: [
      "meta-llama/llama-3.3-70b-instruct:free",
      "deepseek/deepseek-r1:free",
      "qwen/qwen3-32b:free",
      "google/gemma-3-27b-it:free",
    ],
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
