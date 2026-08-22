"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Sparkles,
  Cpu,
  Server,
  Cloud,
  ShieldCheck,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  Zap,
  Activity,
  X,
} from "lucide-react";

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

export function AIWizard({ isOpen, onClose, onComplete }: AIWizardProps) {
  const { t } = useTranslation();
  const [step, setStep] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);
  const [hardware, setHardware] = useState<HardwareProfile | null>(null);
  const [selectedMode, setSelectedMode] = useState<"auto" | "cloud" | "ollama" | "offline">("auto");
  const [apiKey, setApiKey] = useState<string>("");
  const [ollamaUrl, setOllamaUrl] = useState<string>("http://127.0.0.1:11434");
  const [testSuccess, setTestSuccess] = useState<boolean | null>(null);
  const [testing, setTesting] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetch("/api/v1/ai-provider/hardware-profile")
        .then((res) => res.json())
        .then((data) => {
          setHardware(data);
        })
        .catch((err) => console.error("Hardware probe failed:", err))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleTestAndSave = async () => {
    setTesting(true);
    setTestSuccess(null);
    try {
      // 1. Save Mode
      await fetch("/api/v1/ai-provider/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: selectedMode }),
      });

      // 2. Test Connection
      if (selectedMode === "cloud" || selectedMode === "auto") {
        const res = await fetch("/api/v1/ai-provider/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_type: "cloud",
            api_key: apiKey || undefined,
          }),
        });
        const data = await res.json();
        setTestSuccess(data.success);
      } else if (selectedMode === "ollama") {
        const res = await fetch("/api/v1/ai-provider/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_type: "ollama",
            base_url: ollamaUrl,
          }),
        });
        const data = await res.json();
        setTestSuccess(data.success);
      } else {
        setTestSuccess(true);
      }
    } catch (e) {
      setTestSuccess(false);
    } finally {
      setTesting(false);
    }
  };

  const handleFinish = () => {
    if (onComplete) onComplete();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl rounded-3xl border border-[var(--border)] bg-[var(--card)] p-8 shadow-2xl space-y-6">
        {/* Close Button */}
        <button
          onClick={onClose}
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
                s <= step ? "bg-violet-600" : "bg-[var(--border)]"
              }`}
            />
          ))}
        </div>

        {/* STEP 1: Hardware Detection */}
        {step === 1 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-violet-500/10 text-violet-600 dark:text-violet-400">
                <Cpu className="w-3.5 h-3.5" /> Hardware Auto-Detection
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
                Welcome to AI Guru Setup
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                We've scanned your system to determine local AI model compatibility and optimal performance settings.
              </p>
            </div>

            {loading ? (
              <div className="py-12 flex flex-col items-center justify-center space-y-3">
                <Activity className="w-8 h-8 text-violet-600 animate-spin" />
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
                          ? "bg-blue-500/10 text-blue-600 border border-blue-500/20"
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
                    <p className="font-semibold text-violet-600 dark:text-violet-400 mt-1 truncate">
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
                className="px-6 py-2.5 rounded-xl bg-violet-600 text-white text-xs font-semibold hover:bg-violet-700 transition-colors flex items-center gap-2"
              >
                Choose Tutoring Mode <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* STEP 2: Choose Tutoring Mode */}
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
              <div
                onClick={() => setSelectedMode("auto")}
                className={`cursor-pointer p-4 rounded-2xl border transition-all ${
                  selectedMode === "auto"
                    ? "border-violet-500 bg-violet-500/5 ring-2 ring-violet-500/20"
                    : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
                }`}
              >
                <div className="flex items-center gap-2 text-violet-600 font-semibold text-sm">
                  <Sparkles className="w-4 h-4" /> Auto Dual-Mode (Best)
                </div>
                <p className="mt-2 text-xs text-[var(--muted-foreground)] leading-relaxed">
                  Uses Cloud API when available, seamlessly falls back to Ollama or Offline rules when disconnected.
                </p>
              </div>

              <div
                onClick={() => setSelectedMode("cloud")}
                className={`cursor-pointer p-4 rounded-2xl border transition-all ${
                  selectedMode === "cloud"
                    ? "border-blue-500 bg-blue-500/5 ring-2 ring-blue-500/20"
                    : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
                }`}
              >
                <div className="flex items-center gap-2 text-blue-600 font-semibold text-sm">
                  <Cloud className="w-4 h-4" /> External Cloud API
                </div>
                <p className="mt-2 text-xs text-[var(--muted-foreground)] leading-relaxed">
                  Connect your OpenAI, DeepSeek, Claude, or DashScope API key for maximum speed and intelligence.
                </p>
              </div>

              <div
                onClick={() => setSelectedMode("ollama")}
                className={`cursor-pointer p-4 rounded-2xl border transition-all ${
                  selectedMode === "ollama"
                    ? "border-emerald-500 bg-emerald-500/5 ring-2 ring-emerald-500/20"
                    : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
                }`}
              >
                <div className="flex items-center gap-2 text-emerald-600 font-semibold text-sm">
                  <Server className="w-4 h-4" /> Local Ollama (Private)
                </div>
                <p className="mt-2 text-xs text-[var(--muted-foreground)] leading-relaxed">
                  Runs local open-weights LLMs entirely on your hardware. Zero data leaves your computer.
                </p>
              </div>

              <div
                onClick={() => setSelectedMode("offline")}
                className={`cursor-pointer p-4 rounded-2xl border transition-all ${
                  selectedMode === "offline"
                    ? "border-amber-500 bg-amber-500/5 ring-2 ring-amber-500/20"
                    : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
                }`}
              >
                <div className="flex items-center gap-2 text-amber-600 font-semibold text-sm">
                  <ShieldCheck className="w-4 h-4" /> Offline Rule Engine
                </div>
                <p className="mt-2 text-xs text-[var(--muted-foreground)] leading-relaxed">
                  Deterministic educational guidance with zero LLM requirements and zero network needs.
                </p>
              </div>
            </div>

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(1)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition-colors flex items-center gap-1.5"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back
              </button>
              <button
                onClick={() => setStep(3)}
                className="px-6 py-2.5 rounded-xl bg-violet-600 text-white text-xs font-semibold hover:bg-violet-700 transition-colors flex items-center gap-2"
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
                Configure & Test
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                Provide credentials or server endpoints for your chosen mode ({selectedMode}).
              </p>
            </div>

            <div className="space-y-4 p-5 rounded-2xl border border-[var(--border)] bg-[var(--background)]/60">
              {(selectedMode === "cloud" || selectedMode === "auto") && (
                <div>
                  <label className="text-xs font-medium text-[var(--muted-foreground)]">
                    Cloud API Key (Optional if already configured)
                  </label>
                  <input
                    type="password"
                    placeholder="sk-..."
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="mt-1 w-full px-3.5 py-2 text-xs rounded-xl border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                  />
                </div>
              )}

              {selectedMode === "ollama" && (
                <div>
                  <label className="text-xs font-medium text-[var(--muted-foreground)]">
                    Ollama Base URL
                  </label>
                  <input
                    type="text"
                    value={ollamaUrl}
                    onChange={(e) => setOllamaUrl(e.target.value)}
                    className="mt-1 w-full px-3.5 py-2 text-xs rounded-xl border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  />
                </div>
              )}

              {selectedMode === "offline" && (
                <div className="text-xs text-amber-600 dark:text-amber-400">
                  Offline Rule Engine requires no credentials or configuration. It is ready out of the box!
                </div>
              )}

              <div className="flex items-center gap-3 pt-2">
                <button
                  onClick={handleTestAndSave}
                  disabled={testing}
                  className="px-4 py-2 rounded-xl bg-[var(--foreground)] text-[var(--background)] text-xs font-semibold hover:opacity-90 transition-opacity flex items-center gap-1.5 disabled:opacity-50"
                >
                  <Activity className={`w-3.5 h-3.5 ${testing ? "animate-spin" : ""}`} />
                  Test Connection
                </button>

                {testSuccess === true && (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-medium">
                    <CheckCircle2 className="w-4 h-4" /> Ready to go!
                  </span>
                )}
                {testSuccess === false && (
                  <span className="inline-flex items-center gap-1 text-xs text-red-600 font-medium">
                    Verification failed. Check parameters and retry.
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
              <button
                onClick={() => setStep(4)}
                className="px-6 py-2.5 rounded-xl bg-violet-600 text-white text-xs font-semibold hover:bg-violet-700 transition-colors flex items-center gap-2"
              >
                Complete Setup <ArrowRight className="w-4 h-4" />
              </button>
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
                AI Guru is Configured & Ready!
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] max-w-md mx-auto leading-relaxed">
                Your AI tutoring pipeline is active in <strong>{selectedMode.toUpperCase()}</strong> mode. You can adjust model settings and hardware profiles anytime in Settings.
              </p>
            </div>

            <div className="pt-4">
              <button
                onClick={handleFinish}
                className="px-8 py-3 rounded-2xl bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors shadow-lg shadow-violet-600/20 inline-flex items-center gap-2"
              >
                Start Learning Now <Zap className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
