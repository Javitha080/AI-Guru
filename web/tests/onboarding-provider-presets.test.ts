import test from "node:test";
import assert from "node:assert/strict";

import {
  CLOUD_PROVIDER_PRESETS,
  getPreset,
  isWizardMode,
} from "../lib/onboarding/provider-presets";

test("every preset has a unique id and consistent shape", () => {
  const ids = CLOUD_PROVIDER_PRESETS.map((preset) => preset.id);
  assert.equal(new Set(ids).size, ids.length, "preset ids must be unique");
  for (const preset of CLOUD_PROVIDER_PRESETS) {
    assert.ok(preset.label.length > 0, `${preset.id} needs a label`);
    assert.ok(preset.hint.length > 0, `${preset.id} needs a hint`);
    assert.match(preset.baseUrl, /^($|https:\/\/)/, `${preset.id} base URL must be https or empty`);
    assert.ok(["openai", "anthropic"].includes(preset.binding), `${preset.id} binding must be known`);
  }
});

test("native providers carry their expected endpoints and models", () => {
  const byId = new Map(CLOUD_PROVIDER_PRESETS.map((preset) => [preset.id, preset]));

  assert.equal(byId.get("openai")?.baseUrl, "https://api.openai.com/v1");
  assert.equal(byId.get("openai")?.defaultModel, "gpt-4o-mini");

  assert.equal(byId.get("deepseek")?.baseUrl, "https://api.deepseek.com/v1");
  assert.equal(byId.get("deepseek")?.defaultModel, "deepseek-chat");

  // Anthropic uses its native binding without an OpenAI-style base URL.
  assert.equal(byId.get("anthropic")?.binding, "anthropic");
  assert.equal(byId.get("anthropic")?.baseUrl, "");

  assert.equal(
    byId.get("dashscope")?.baseUrl,
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
  );
  assert.equal(byId.get("dashscope")?.defaultModel, "qwen-plus");

  // Custom requires the user to supply everything meaningful.
  assert.equal(byId.get("custom")?.baseUrl, "");
  assert.equal(byId.get("custom")?.defaultModel, "");
});

test("getPreset falls back to the first preset for unknown ids", () => {
  const fallback = getPreset("does-not-exist" as never);
  assert.equal(fallback.id, CLOUD_PROVIDER_PRESETS[0].id);
  assert.equal(getPreset("deepseek").defaultModel, "deepseek-chat");
});

test("isWizardMode accepts exactly the four backend modes", () => {
  for (const mode of ["auto", "cloud", "ollama", "offline"] as const) {
    assert.equal(isWizardMode(mode), true, `${mode} should be valid`);
  }
  for (const bad of ["Auto", "", "local", null, undefined, 42]) {
    assert.equal(isWizardMode(bad), false, `${String(bad)} should be invalid`);
  }
});
