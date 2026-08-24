"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Cloud,
  Cpu,
  Loader2,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
  Zap,
} from "lucide-react";

import {
  CLOUD_PROVIDER_PRESETS,
  getPreset,
  type CloudProviderId,
  type WizardMode,
} from "@/lib/onboarding/provider-presets";

interface AIWizardProps {
  isOpen: boolean;
  onClose: () => void;
  onComplete?: () => void;
}

interface HardwareProfile {
  tier: "LOW" | "MEDIUM" | "HIGH";
  gpu_type: string;
  gpu_name: string | null;
  vram_gb: number;
  system_ram_gb: number;
  cpu_cores_physical: number;
  recommended_models: string[];
  recommended_quantization: string;
  description: string;
}

interface ActivateResponse {
  success?: boolean;
  message?: string;
  mode?: string;
  provider?: string;
  model?: string | null;
  masked_key?: string;
}

const MODE_CARDS: Array<{
  id: WizardMode;
  icon: typeof Cloud;
  title: string;
  description: string;
  activeClasses: string;
  textClasses: string;
}> = [
  {
    id: "auto",
    icon: Sparkles,
    title: "Auto Dual-Mode (Best)",
    description:
      "Uses Cloud API when available, seamlessly falls back to Ollama or Offline rules when disconnected.",
    activeClasses: "border-[var(--primary)] bg-[var(--accent)] ring-2 ring-[var(--glow-primary)]",
    textClasses: "text-[var(--primary)]",
  },
  {
    id: "cloud",
    icon: Cloud,
    title: "External Cloud API",
    description:
      "Connect your OpenAI, DeepSeek, Claude, DashScope, or custom OpenAI-compatible endpoint.",
    activeClasses: "border-[var(--primary)] bg-[var(--primary)]/5 ring-2 ring-[var(--ring)]/20",
    textClasses: "text-[var(--primary)]",
  },
  {
    id: "ollama",
    icon: Server,
    title: "Local Ollama (Private)",
    description:
      "Runs local open-weights LLMs entirely on your hardware. Zero data leaves your computer.",
    activeClasses: "border-emerald-500 bg-emerald-500/5 ring-2 ring-emerald-500/20",
    textClasses: "text-emerald-600 dark:text-emerald-400",
  },
  {
    id: "offline",
    icon: ShieldCheck,
    title: "Offline Rule Engine",
    description:
      "Deterministic educational guidance with zero LLM requirements and zero network needs.",
    activeClasses: "border-amber-500 bg-amber-500/5 ring-2 ring-amber-500/20",
    textClasses: "text-amber-600 dark:text-amber-400",
  },
];

export function AIWizard({ isOpen, onClose, onComplete }: AIWizardProps) {
  const [step, setStep] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);
  const [hardware, setHardware] = useState<HardwareProfile | null>(null);

  const [selectedMode, setSelectedMode] = useState<WizardMode>("auto");
  const [providerId, setProviderId] = useState<CloudProviderId>("openai");
  const [apiKey, setApiKey] = useState<string>("");
  const [baseUrl, setBaseUrl] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [ollamaUrl, setOllamaUrl] = useState<string>("http://127.0.0.1:11434");
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [ollamaLoading, setOllamaLoading] = useState<boolean>(false);

  const [activating, setActivating] = useState<boolean>(false);
  const [verified, setVerified] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; message: string } | null>(null);
  const [confirmingClose, setConfirmingClose] = useState<boolean>(false);

  const preset = useMemo(() => getPreset(providerId), [providerId]);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    fetch("/api/v1/ai-provider/hardware-profile")
      .then((res) => res.json())
      .then((data) => setHardware(data))
      .catch((err) => console.error("Hardware probe failed:", err))
      .finally(() => setLoading(false));
  }, [isOpen]);

  if (!isOpen) return null;

  const applyPreset = (id: CloudProviderId) => {
    setProviderId(id);
    const next = getPreset(id);
    setBaseUrl(next.baseUrl);
    setModel(next.defaultModel);
    setVerified(false);
    setFeedback(null);
  };

  const switchMode = (mode: WizardMode) => {
    setSelectedMode(mode);
    setVerified(false);
    setFeedback(null);
  };

  const loadOllamaModels = async () => {
    setOllamaLoading(true);
    try {
      const res = await fetch(
        `/api/v1/ai-provider/ollama/models?host=${encodeURIComponent(ollamaUrl.trim() || "http://127.0.0.1:11434")}`,
      );
      const data = await res.json();
      setOllamaModels(Array.isArray(data?.installed_models) ? data.installed_models : []);
      if (!data?.ollama_online) {
        setFeedback({
          ok: false,
          message: String(data?.error ?? "Could not reach Ollama at that address."),
        });
      } else {
        setFeedback(null);
      }
    } catch {
      setFeedback({ ok: false, message: "Could not reach Ollama." });
    } finally {
      setOllamaLoading(false);
    }
  };

  const handleActivate = async () => {
    setActivating(true);
    setFeedback(null);
    try {
      const body: Record<string, unknown> = { mode: selectedMode };
      if (selectedMode === "cloud" || selectedMode === "auto") {
        body.provider = providerId;
        if (apiKey.trim()) body.api_key = apiKey.trim();
        if (baseUrl.trim()) body.base_url = baseUrl.trim();
        if (model.trim()) body.model = model.trim();
        body.binding = preset.binding;
      } else if (selectedMode === "ollama") {
        body.provider = "ollama";
        if (ollamaUrl.trim()) body.ollama_base_url = ollamaUrl.trim();
      }

      const res = await fetch("/api/v1/ai-provider/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data: ActivateResponse = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        setVerified(true);
        setFeedback({
          ok: true,
          message:
            data.message ||
            (selectedMode === "offline"
              ? "Offline Rule Engine activated."
              : "Connection verified and saved."),
        });
      } else {
        setVerified(false);
        setFeedback({
          ok: false,
          message: data.message || `Activation failed (HTTP ${res.status}).`,
        });
      }
    } catch (e) {
      setVerified(false);
      setFeedback({ ok: false, message: e instanceof Error ? e.message : "Activation failed." });
    } finally {
      setActivating(false);
    }
  };

  const requestClose = () => {
    if (verified || step >= 4) {
      handleClose();
      return;
    }
    setConfirmingClose(true);
  };

  const handleClose = () => {
    setConfirmingClose(false);
    onClose();
  };

  const handleFinish = () => {
    // Exactly one dismissal path: verified completions report onComplete,
    // everything else reports onClose.
    if (onComplete) {
      onComplete();
    } else {
      onClose();
    }
  };

  const canActivate =
    selectedMode === "offline" ||
    selectedMode === "ollama" ||
    (preset.id === "custom" ? Boolean(baseUrl.trim() && model.trim()) : Boolean(model.trim()));

  const inputClasses =
    "mt-1 w-full px-3.5 py-2 text-xs rounded-xl border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--glow-primary)]";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl rounded-3xl border border-[var(--border)] bg-[var(--card)] p-8 shadow-2xl space-y-6">
        {/* Close Button */}
        <button
          onClick={requestClose}
          aria-label="Close setup"
          className="absolute top-6 right-6 p-2 rounded-full text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)] transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Progress Tracker */}
        <div className="flex items-center gap-2">
          {[1, 2, 3, 4].map((s) => (
            <div
              key={s}
              className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
                s <= step ? "bg-[var(--primary)]" : "bg-[var(--border)]"
              }`}
            />
          ))}
        </div>

        {/* STEP 1: Hardware Detection */}
        {step === 1 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-[var(--accent)] text-[var(--primary)]">
                <Cpu className="w-3.5 h-3.5" /> Hardware Auto-Detection
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
                Welcome to AI Guru Setup
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                We&apos;ve scanned your system to determine local AI model compatibility and optimal
                performance settings.
              </p>
            </div>

            {loading ? (
              <div className="py-12 flex flex-col items-center justify-center space-y-3">
                <Loader2 className="w-8 h-8 text-[var(--primary)] animate-spin" />
                <p className="text-xs text-[var(--muted-foreground)]">Profiling GPU, VRAM, and RAM...</p>
              </div>
            ) : hardware ? (
              <div className="p-5 rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-[var(--foreground)]">Detected Hardware Tier:</span>
                  <span
                    className={`px-3 py-1 text-xs font-bold rounded-full ${
                      hardware.tier === "HIGH"
                        ? "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
                        : hardware.tier === "MEDIUM"
                          ? "bg-[var(--accent)] text-[var(--primary)] border border-[var(--glass-border-highlight)]"
                          : "bg-amber-500/10 text-amber-600 border border-amber-500/20"
                    }`}
                  >
                    {hardware.tier} PERFORMANCE
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-[var(--card)] border border-[var(--border)]">
                    <span className="text-[var(--muted-foreground)]">GPU / Device:</span>
                    <p className="font-semibold text-[var(--foreground)] truncate mt-1">
                      {hardware.gpu_name || hardware.gpu_type}
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-[var(--card)] border border-[var(--border)]">
                    <span className="text-[var(--muted-foreground)]">VRAM / RAM:</span>
                    <p className="font-semibold text-[var(--foreground)] mt-1">
                      {hardware.vram_gb}G VRAM / {hardware.system_ram_gb}G RAM
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-[var(--card)] border border-[var(--border)]">
                    <span className="text-[var(--muted-foreground)]">Recommended Models:</span>
                    <p className="font-semibold text-[var(--primary)] mt-1 truncate">
                      {hardware.recommended_models.slice(0, 2).join(", ")}
                    </p>
                  </div>
                </div>

                <p className="text-xs text-[var(--muted-foreground)] leading-relaxed italic">
                  {hardware.description}
                </p>
              </div>
            ) : null}

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setStep(2)}
                className="px-6 py-2.5 rounded-xl bg-[var(--primary)] text-white text-xs font-semibold hover:brightness-110 transition-colors flex items-center gap-2"
              >
                Choose Tutoring Mode <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* STEP 2: Choose Tutoring Mode (+ cloud provider) */}
        {step === 2 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <h2 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
                Select Your AI Provider Mode
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                AI Guru supports external cloud models, local private Ollama models, and offline tutoring rules.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {MODE_CARDS.map((card) => {
                const Icon = card.icon;
                const selected = selectedMode === card.id;
                return (
                  <div
                    key={card.id}
                    onClick={() => switchMode(card.id)}
                    role="radio"
                    aria-checked={selected}
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") switchMode(card.id);
                    }}
                    className={`cursor-pointer p-4 rounded-2xl border transition-all ${
                      selected ? card.activeClasses : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
                    }`}
                  >
                    <div className={`flex items-center gap-2 font-semibold text-sm ${card.textClasses}`}>
                      <Icon className="w-4 h-4" /> {card.title}
                    </div>
                    <p className="mt-2 text-xs text-[var(--muted-foreground)] leading-relaxed">
                      {card.description}
                    </p>
                  </div>
                );
              })}
            </div>

            {(selectedMode === "cloud" || selectedMode === "auto") && (
              <div className="space-y-2">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Cloud Provider</label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {CLOUD_PROVIDER_PRESETS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => applyPreset(item.id)}
                      title={item.hint}
                      className={`px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
                        providerId === item.id
                          ? "border-[var(--primary)] bg-[var(--accent)] text-[var(--primary)]"
                          : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--foreground)]/20"
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-[var(--muted-foreground)] italic">{preset.hint}</p>
              </div>
            )}

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(1)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition-colors flex items-center gap-1.5"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back
              </button>
              <button
                onClick={() => setStep(3)}
                className="px-6 py-2.5 rounded-xl bg-[var(--primary)] text-white text-xs font-semibold hover:brightness-110 transition-colors flex items-center gap-2"
              >
                Configure Provider <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* STEP 3: Configuration & Verification */}
        {step === 3 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <h2 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
                Configure &amp; Test
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                {selectedMode === "cloud" || selectedMode === "auto"
                  ? `Credentials for ${preset.label}. Everything is saved locally only after a successful connection test.`
                  : selectedMode === "ollama"
                    ? "Point AI Guru at your local Ollama daemon."
                    : "No credentials or network required."}
              </p>
            </div>

            <div className="space-y-4 p-5 rounded-2xl border border-[var(--border)] bg-[var(--background)]/60">
              {(selectedMode === "cloud" || selectedMode === "auto") && (
                <>
                  <div>
                    <label className="text-xs font-medium text-[var(--muted-foreground)]">
                      {preset.label} API Key
                    </label>
                    <input
                      type="password"
                      placeholder={
                        providerId === "anthropic"
                          ? "sk-ant-..."
                          : providerId === "dashscope"
                            ? "sk-..."
                            : "sk-..."
                      }
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                      className={inputClasses}
                    />
                    <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                      Stored in the local key vault on your machine only. Leave blank if a key is
                      already configured.
                    </p>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-[var(--muted-foreground)]">
                      Base URL{providerId === "custom" ? " (required)" : ""}
                    </label>
                    <input
                      type="text"
                      placeholder="https://api.example.com/v1"
                      value={baseUrl}
                      onChange={(event) => {
                        setBaseUrl(event.target.value);
                        setVerified(false);
                        setFeedback(null);
                      }}
                      className={inputClasses}
                    />
                  </div>

                  <div>
                    <label className="text-xs font-medium text-[var(--muted-foreground)]">Model</label>
                    <input
                      type="text"
                      list="wizard-model-suggestions"
                      placeholder="gpt-4o-mini"
                      value={model}
                      onChange={(event) => {
                        setModel(event.target.value);
                        setVerified(false);
                        setFeedback(null);
                      }}
                      className={inputClasses}
                    />
                    <datalist id="wizard-model-suggestions">
                      {preset.models.map((item) => (
                        <option key={item} value={item} />
                      ))}
                    </datalist>
                  </div>
                </>
              )}

              {selectedMode === "ollama" && (
                <>
                  <div>
                    <label className="text-xs font-medium text-[var(--muted-foreground)]">Ollama Base URL</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={ollamaUrl}
                        onChange={(event) => {
                          setOllamaUrl(event.target.value);
                          setVerified(false);
                          setFeedback(null);
                        }}
                        className={`${inputClasses} flex-1`}
                      />
                      <button
                        type="button"
                        onClick={loadOllamaModels}
                        disabled={ollamaLoading}
                        className="shrink-0 mt-1 px-3 py-2 rounded-xl text-xs font-semibold border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition-colors flex items-center gap-1.5 disabled:opacity-50"
                      >
                        {ollamaLoading ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3.5 h-3.5" />
                        )}
                        Models
                      </button>
                    </div>
                  </div>

                  {ollamaModels.length > 0 && (
                    <div className="text-xs text-[var(--muted-foreground)]">
                      Installed:{" "}
                      <span className="text-[var(--foreground)] font-medium">
                        {ollamaModels.slice(0, 6).join(", ")}
                        {ollamaModels.length > 6 ? ` +${ollamaModels.length - 6} more` : ""}
                      </span>
                    </div>
                  )}
                </>
              )}

              {selectedMode === "offline" && (
                <div className="text-xs text-amber-600 dark:text-amber-400">
                  The Offline Rule Engine requires no configuration. Activating it stores your choice
                  so AI Guru starts straight into deterministic tutoring guidance.
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3 pt-2">
                {!verified ? (
                  <button
                    onClick={handleActivate}
                    disabled={activating || !canActivate}
                    className="px-4 py-2 rounded-xl bg-[var(--foreground)] text-[var(--background)] text-xs font-semibold hover:opacity-90 transition-opacity flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <Activity className={`w-3.5 h-3.5 ${activating ? "animate-pulse" : ""}`} />
                    {activating ? "Testing…" : "Test & Save"}
                  </button>
                ) : (
                  <button
                    onClick={() => setStep(4)}
                    className="px-6 py-2.5 rounded-xl bg-[var(--primary)] text-white text-xs font-semibold hover:brightness-110 transition-colors flex items-center gap-2"
                  >
                    Complete Setup <ArrowRight className="w-4 h-4" />
                  </button>
                )}

                {feedback && feedback.ok && (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-medium min-w-0">
                    <CheckCircle2 className="w-4 h-4 shrink-0" />
                    <span className="truncate">{feedback.message}</span>
                  </span>
                )}
                {feedback && !feedback.ok && (
                  <span className="inline-flex items-center gap-1 text-xs text-red-600 font-medium min-w-0">
                    <XCircle className="w-4 h-4 shrink-0" />
                    <span className="truncate" title={feedback.message}>
                      {feedback.message}
                    </span>
                  </span>
                )}
              </div>
            </div>

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(2)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition-colors flex items-center gap-1.5"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back
              </button>
              {verified && (
                <span className="inline-flex items-center gap-1.5 text-xs text-emerald-600 font-semibold self-center">
                  <CheckCircle2 className="w-4 h-4" /> Saved &amp; verified
                </span>
              )}
            </div>
          </div>
        )}

        {/* STEP 4: Ready */}
        {step === 4 && (
          <div className="space-y-6 text-center py-6">
            <div className="mx-auto w-16 h-16 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
              <CheckCircle2 className="w-8 h-8" />
            </div>

            <div className="space-y-2">
              <h2 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
                AI Guru is Configured &amp; Ready!
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] max-w-md mx-auto leading-relaxed">
                Verified and saved: tutoring runs in <strong>{selectedMode.toUpperCase()}</strong> mode.
                You can adjust providers, models, and hardware profiles anytime in Settings.
              </p>
            </div>

            <div className="pt-4">
              <button
                onClick={handleFinish}
                className="px-8 py-3 rounded-2xl bg-[var(--primary)] text-white text-sm font-semibold hover:brightness-110 transition-colors shadow-lg shadow-violet-600/20 inline-flex items-center gap-2"
              >
                Start Learning Now <Zap className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Close confirmation — never silently mark setup as done */}
        {confirmingClose && (
          <div className="absolute inset-0 z-10 rounded-3xl bg-black/40 backdrop-blur-[2px] flex items-center justify-center p-6">
            <div className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 space-y-4 shadow-xl">
              <h3 className="text-base font-bold text-[var(--foreground)]">Quit setup?</h3>
              <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
                Nothing has been saved yet. Until you finish setup, AI Guru will fall back to its
                basic offline guidance, and this wizard will appear again next time you open the app.
              </p>
              <div className="flex justify-end gap-2 pt-1">
                <button
                  onClick={() => setConfirmingClose(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-[var(--primary)] hover:bg-[var(--accent)] transition-colors"
                >
                  Keep setting up
                </button>
                <button
                  onClick={handleClose}
                  className="px-4 py-2 rounded-xl bg-[var(--foreground)] text-[var(--background)] text-xs font-semibold hover:opacity-90 transition-opacity"
                >
                  Skip for now
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
