"use client";

import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Cpu,
  Sparkles,
  Zap,
  Server,
  Cloud,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Download,
  KeyRound,
  Eye,
  EyeOff,
  Activity,
  Layers,
  ArrowRight,
} from "lucide-react";

interface HardwareProfile {
  tier: "LOW" | "MEDIUM" | "HIGH";
  gpu_type: string;
  gpu_name: string | null;
  gpu_count: number;
  vram_gb: number;
  system_ram_gb: number;
  cpu_cores_physical: number;
  cpu_cores_logical: number;
  cpu_name: string;
  recommended_models: string[];
  recommended_quantization: string;
  max_context_window: number;
  cv_recommended_fps: number;
  description: string;
}

interface ProviderStatus {
  mode: "auto" | "cloud" | "ollama" | "offline";
  active_provider: string;
  hardware_profile: HardwareProfile;
  cloud: {
    health: { status: string; available: boolean; latency_ms: number; error?: string };
    circuit_state: "CLOSED" | "OPEN" | "HALF_OPEN";
    masked_api_key: string;
  };
  ollama: {
    health: { status: string; available: boolean; latency_ms: number; models: string[]; error?: string };
    circuit_state: "CLOSED" | "OPEN" | "HALF_OPEN";
    base_url: string;
  };
  offline: {
    health: { status: string; available: boolean; latency_ms: number };
  };
}

export function AISettings() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [hardware, setHardware] = useState<HardwareProfile | null>(null);
  const [selectedMode, setSelectedMode] = useState<"auto" | "cloud" | "ollama" | "offline">("auto");
  const [isUpdatingMode, setIsUpdatingMode] = useState(false);

  // Cloud test state
  const [cloudApiKey, setCloudApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [testingCloud, setTestingCloud] = useState(false);
  const [cloudTestResult, setCloudTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // Ollama state
  const [ollamaHost, setOllamaHost] = useState("http://127.0.0.1:11434");
  const [testingOllama, setTestingOllama] = useState(false);
  const [ollamaTestResult, setOllamaTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/v1/ai-provider/status");
      if (res.ok) {
        const data: ProviderStatus = await res.json();
        setStatus(data);
        setSelectedMode(data.mode);
        if (data.hardware_profile) {
          setHardware(data.hardware_profile);
        }
      }
    } catch (err) {
      console.error("Failed to fetch AI provider status:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHardware = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/ai-provider/hardware-profile");
      if (res.ok) {
        const data: HardwareProfile = await res.json();
        setHardware(data);
      }
    } catch (err) {
      console.error("Failed to fetch hardware profile:", err);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchHardware();
  }, [fetchStatus, fetchHardware]);

  const handleModeChange = async (mode: "auto" | "cloud" | "ollama" | "offline") => {
    try {
      setIsUpdatingMode(true);
      const res = await fetch("/api/v1/ai-provider/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (res.ok) {
        setSelectedMode(mode);
        await fetchStatus();
      }
    } catch (err) {
      console.error("Failed to update tutoring mode:", err);
    } finally {
      setIsUpdatingMode(false);
    }
  };

  const testCloudConnection = async () => {
    try {
      setTestingCloud(true);
      setCloudTestResult(null);
      const res = await fetch("/api/v1/ai-provider/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_type: "cloud",
          api_key: cloudApiKey || undefined,
        }),
      });
      const data = await res.json();
      setCloudTestResult({
        success: data.success,
        message: data.message || (data.success ? "Connection successful" : "Failed"),
      });
    } catch (err: any) {
      setCloudTestResult({ success: false, message: err.message || "Request failed" });
    } finally {
      setTestingCloud(false);
    }
  };

  const testOllamaConnection = async () => {
    try {
      setTestingOllama(true);
      setOllamaTestResult(null);
      const res = await fetch("/api/v1/ai-provider/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_type: "ollama",
          base_url: ollamaHost,
        }),
      });
      const data = await res.json();
      setOllamaTestResult({
        success: data.success,
        message: data.message || (data.success ? "Ollama is online" : "Offline"),
      });
      if (data.success) {
        await fetchStatus();
      }
    } catch (err: any) {
      setOllamaTestResult({ success: false, message: err.message || "Connection refused" });
    } finally {
      setTestingOllama(false);
    }
  };

  const handlePullModel = async (modelName: string) => {
    try {
      setDownloadingModel(modelName);
      setDownloadStatus(`Initiating download for ${modelName}...`);
      const res = await fetch("/api/v1/ai-provider/ollama/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelName }),
      });
      if (res.ok) {
        setDownloadStatus(`Download requested for ${modelName}. Downloading in background...`);
        setTimeout(() => {
          fetchStatus();
          setDownloadingModel(null);
          setDownloadStatus(null);
        }, 4000);
      } else {
        const err = await res.json();
        setDownloadStatus(`Download failed: ${err.detail || "Error"}`);
        setDownloadingModel(null);
      }
    } catch (err: any) {
      setDownloadStatus(`Download error: ${err.message}`);
      setDownloadingModel(null);
    }
  };

  const getTierBadge = (tier?: string) => {
    switch (tier) {
      case "HIGH":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <Sparkles className="w-3.5 h-3.5" /> High Performance Tier
          </span>
        );
      case "MEDIUM":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[var(--primary)]/10 text-[var(--primary)] border border-[var(--primary)]/20">
            <Zap className="w-3.5 h-3.5" /> Balanced Tier
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
            <Cpu className="w-3.5 h-3.5" /> Standard / CPU Tier
          </span>
        );
    }
  };

  return (
    <div className="space-y-8 max-w-5xl">
      {/* 1. Hardware Capability Profiler Banner */}
      <div className="rounded-2xl border border-[var(--border)] bg-gradient-to-br from-[var(--card)] to-[var(--card)]/50 p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-[var(--accent)] text-[var(--primary)]">
              <Cpu className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-[var(--foreground)]">System Hardware Capability</h2>
              <p className="text-xs text-[var(--muted-foreground)]">
                Local-first hardware detection determines optimal model sizes and resource allocations.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {getTierBadge(hardware?.tier)}
            <button
              onClick={() => {
                fetchHardware();
                fetchStatus();
              }}
              className="p-2 text-xs font-medium rounded-lg border border-[var(--border)] hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition-colors flex items-center gap-1.5"
              title="Rescan hardware"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Rescan
            </button>
          </div>
        </div>

        {hardware && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5">
            <div className="p-3.5 rounded-xl bg-[var(--background)]/60 border border-[var(--border)]">
              <span className="text-[11px] font-medium text-[var(--muted-foreground)] uppercase tracking-wider">
                Accelerator (GPU)
              </span>
              <p className="mt-1 text-sm font-semibold text-[var(--foreground)] truncate">
                {hardware.gpu_name || hardware.gpu_type}
              </p>
              <span className="text-xs text-[var(--muted-foreground)]">{hardware.vram_gb} GB VRAM</span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--background)]/60 border border-[var(--border)]">
              <span className="text-[11px] font-medium text-[var(--muted-foreground)] uppercase tracking-wider">
                System Memory (RAM)
              </span>
              <p className="mt-1 text-sm font-semibold text-[var(--foreground)]">
                {hardware.system_ram_gb} GB RAM
              </p>
              <span className="text-xs text-[var(--muted-foreground)]">
                {hardware.system_ram_gb >= 16 ? "Fast dual-channel" : "Standard memory"}
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--background)]/60 border border-[var(--border)]">
              <span className="text-[11px] font-medium text-[var(--muted-foreground)] uppercase tracking-wider">
                Processor (CPU)
              </span>
              <p className="mt-1 text-sm font-semibold text-[var(--foreground)] truncate">
                {hardware.cpu_cores_physical} Cores ({hardware.cpu_cores_logical} Threads)
              </p>
              <span className="text-xs text-[var(--muted-foreground)] truncate">{hardware.cpu_name}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--background)]/60 border border-[var(--border)]">
              <span className="text-[11px] font-medium text-[var(--muted-foreground)] uppercase tracking-wider">
                Recommended Local LLMs
              </span>
              <p className="mt-1 text-sm font-semibold text-[var(--foreground)] truncate">
                {hardware.recommended_models.slice(0, 2).join(", ")}
              </p>
              <span className="text-xs text-[var(--primary)] font-medium">
                Quant: {hardware.recommended_quantization} · Max {hardware.max_context_window / 1024}k Ctx
              </span>
            </div>
          </div>
        )}
      </div>

      {/* 2. Tutoring Execution Mode Switcher */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-[var(--foreground)]">AI Tutoring & Fallback Mode</h2>
          <p className="text-xs text-[var(--muted-foreground)]">
            Select how AI Guru routes tutoring queries. The auto-fallback chain ensures uninterrupted studying even when offline.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          {/* Mode Card: Auto */}
          <div
            onClick={() => handleModeChange("auto")}
            className={`cursor-pointer relative p-4 rounded-2xl border transition-all duration-150 ${
              selectedMode === "auto"
                ? "border-[var(--primary)] bg-[var(--accent)] shadow-md shadow-[var(--glow-primary)] ring-2 ring-[var(--glow-primary)]"
                : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="p-2 rounded-xl bg-[var(--accent)] text-[var(--primary)]">
                <Sparkles className="w-5 h-5" />
              </span>
              {selectedMode === "auto" && (
                <span className="px-2 py-0.5 text-[10px] font-semibold uppercase bg-[var(--primary)] text-white rounded-full">
                  Active
                </span>
              )}
            </div>
            <h3 className="mt-3 text-sm font-semibold text-[var(--foreground)]">Auto Mode (Recommended)</h3>
            <p className="mt-1 text-xs text-[var(--muted-foreground)] leading-relaxed">
              Cloud API $\to$ Local Ollama $\to$ Offline Rules. Automatic recovery upon network drops.
            </p>
          </div>

          {/* Mode Card: Cloud */}
          <div
            onClick={() => handleModeChange("cloud")}
            className={`cursor-pointer relative p-4 rounded-2xl border transition-all duration-150 ${
              selectedMode === "cloud"
                ? "border-[var(--primary)] bg-[var(--primary)]/5 shadow-md shadow-[var(--glow-primary)] ring-2 ring-[var(--ring)]/20"
                : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="p-2 rounded-xl bg-[var(--primary)]/10 text-[var(--primary)]">
                <Cloud className="w-5 h-5" />
              </span>
              {selectedMode === "cloud" && (
                <span className="px-2 py-0.5 text-[10px] font-semibold uppercase bg-[var(--primary)] text-white rounded-full">
                  Active
                </span>
              )}
            </div>
            <h3 className="mt-3 text-sm font-semibold text-[var(--foreground)]">External Cloud API</h3>
            <p className="mt-1 text-xs text-[var(--muted-foreground)] leading-relaxed">
              OpenAI, DeepSeek, Claude, DashScope. Highest reasoning quality with internet.
            </p>
          </div>

          {/* Mode Card: Ollama */}
          <div
            onClick={() => handleModeChange("ollama")}
            className={`cursor-pointer relative p-4 rounded-2xl border transition-all duration-150 ${
              selectedMode === "ollama"
                ? "border-emerald-500 bg-emerald-500/5 shadow-md shadow-emerald-500/5 ring-2 ring-emerald-500/20"
                : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="p-2 rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <Server className="w-5 h-5" />
              </span>
              {selectedMode === "ollama" && (
                <span className="px-2 py-0.5 text-[10px] font-semibold uppercase bg-emerald-500 text-white rounded-full">
                  Active
                </span>
              )}
            </div>
            <h3 className="mt-3 text-sm font-semibold text-[var(--foreground)]">Local Ollama</h3>
            <p className="mt-1 text-xs text-[var(--muted-foreground)] leading-relaxed">
              100% private local LLM inference on your machine. Zero cloud communication.
            </p>
          </div>

          {/* Mode Card: Offline */}
          <div
            onClick={() => handleModeChange("offline")}
            className={`cursor-pointer relative p-4 rounded-2xl border transition-all duration-150 ${
              selectedMode === "offline"
                ? "border-amber-500 bg-amber-500/5 shadow-md shadow-amber-500/5 ring-2 ring-amber-500/20"
                : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/20"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="p-2 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
                <ShieldCheck className="w-5 h-5" />
              </span>
              {selectedMode === "offline" && (
                <span className="px-2 py-0.5 text-[10px] font-semibold uppercase bg-amber-500 text-white rounded-full">
                  Active
                </span>
              )}
            </div>
            <h3 className="mt-3 text-sm font-semibold text-[var(--foreground)]">Offline Rule Engine</h3>
            <p className="mt-1 text-xs text-[var(--muted-foreground)] leading-relaxed">
              Deterministic educational pedagogical engine. Operates with zero AI model overhead.
            </p>
          </div>
        </div>
      </div>

      {/* 3. Provider Configuration Panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Panel A: Cloud API Setup */}
        <div className="p-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Cloud className="w-5 h-5 text-[var(--primary)]" />
              <h3 className="text-sm font-semibold text-[var(--foreground)]">Cloud API Configuration</h3>
            </div>
            {status?.cloud?.circuit_state === "CLOSED" ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium bg-emerald-500/10 px-2 py-0.5 rounded-full">
                <CheckCircle2 className="w-3 h-3" /> Online
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[11px] text-amber-600 font-medium bg-amber-500/10 px-2 py-0.5 rounded-full">
                <AlertTriangle className="w-3 h-3" /> Circuit: {status?.cloud?.circuit_state || "Unknown"}
              </span>
            )}
          </div>

          <div className="space-y-3 pt-2">
            <div>
              <label className="text-xs font-medium text-[var(--muted-foreground)]">API Key (Secure Local Vault)</label>
              <div className="mt-1 relative flex items-center">
                <input
                  type={showKey ? "text" : "password"}
                  placeholder={status?.cloud?.masked_api_key || "Enter your API key..."}
                  value={cloudApiKey}
                  onChange={(e) => setCloudApiKey(e.target.value)}
                  className="w-full px-3 py-2 pr-10 text-xs rounded-xl border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]/20"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-3 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
                🔒 Keys are stored strictly on your local disk and never bundled into frontend static assets.
              </p>
            </div>

            <div className="flex items-center gap-2 pt-2">
              <button
                onClick={testCloudConnection}
                disabled={testingCloud}
                className="px-3.5 py-1.5 text-xs font-medium rounded-xl bg-[var(--primary)] text-white hover:brightness-110 transition-colors flex items-center gap-1.5 disabled:opacity-50"
              >
                <Activity className={`w-3.5 h-3.5 ${testingCloud ? "animate-spin" : ""}`} />
                Test Cloud API
              </button>
            </div>

            {cloudTestResult && (
              <div
                className={`p-3 rounded-xl text-xs ${
                  cloudTestResult.success
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20"
                    : "bg-red-500/10 text-red-700 dark:text-red-300 border border-red-500/20"
                }`}
              >
                {cloudTestResult.message}
              </div>
            )}
          </div>
        </div>

        {/* Panel B: Local Ollama Setup */}
        <div className="p-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Server className="w-5 h-5 text-emerald-500" />
              <h3 className="text-sm font-semibold text-[var(--foreground)]">Local Ollama Runtime</h3>
            </div>
            {status?.ollama?.health?.available ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium bg-emerald-500/10 px-2 py-0.5 rounded-full">
                <CheckCircle2 className="w-3 h-3" /> Ready ({status.ollama.health.models.length} models)
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[11px] text-zinc-500 font-medium bg-zinc-500/10 px-2 py-0.5 rounded-full">
                Offline
              </span>
            )}
          </div>

          <div className="space-y-3 pt-2">
            <div>
              <label className="text-xs font-medium text-[var(--muted-foreground)]">Ollama Daemon Endpoint</label>
              <input
                type="text"
                value={ollamaHost}
                onChange={(e) => setOllamaHost(e.target.value)}
                className="mt-1 w-full px-3 py-2 text-xs rounded-xl border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
              />
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={testOllamaConnection}
                disabled={testingOllama}
                className="px-3.5 py-1.5 text-xs font-medium rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 transition-colors flex items-center gap-1.5 disabled:opacity-50"
              >
                <Activity className={`w-3.5 h-3.5 ${testingOllama ? "animate-spin" : ""}`} />
                Check Ollama
              </button>
            </div>

            {ollamaTestResult && (
              <div
                className={`p-3 rounded-xl text-xs ${
                  ollamaTestResult.success
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20"
                    : "bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20"
                }`}
              >
                {ollamaTestResult.message}
              </div>
            )}

            {/* Recommended Model One-Click Downloads */}
            {hardware && (
              <div className="pt-2">
                <span className="text-xs font-medium text-[var(--muted-foreground)]">Recommended Models to Download:</span>
                <div className="mt-2 flex flex-wrap gap-2">
                  {hardware.recommended_models.map((m) => {
                    const isInstalled = status?.ollama?.health?.models?.includes(m);
                    return (
                      <button
                        key={m}
                        onClick={() => handlePullModel(m)}
                        disabled={downloadingModel === m || isInstalled}
                        className={`px-3 py-1 text-xs font-medium rounded-lg border transition-all flex items-center gap-1.5 ${
                          isInstalled
                            ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20 cursor-default"
                            : "bg-[var(--background)] hover:bg-[var(--accent)] text-[var(--foreground)] border-[var(--border)]"
                        }`}
                      >
                        {isInstalled ? (
                          <>
                            <CheckCircle2 className="w-3 h-3" /> {m} (Installed)
                          </>
                        ) : downloadingModel === m ? (
                          <>
                            <RefreshCw className="w-3 h-3 animate-spin" /> Pulling...
                          </>
                        ) : (
                          <>
                            <Download className="w-3 h-3" /> Pull {m}
                          </>
                        )}
                      </button>
                    );
                  })}
                </div>
                {downloadStatus && (
                  <p className="mt-2 text-xs text-[var(--primary)] font-medium">
                    {downloadStatus}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
