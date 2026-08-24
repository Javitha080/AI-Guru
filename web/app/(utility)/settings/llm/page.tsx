"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles, Sliders } from "lucide-react";

import { AISettings } from "@/components/settings/AISettings";
import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function LlmSettingsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<"guru" | "advanced">("guru");

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title={t("AI Tutoring & LLM Engine")}
        description={t(
          "Configure dual-mode AI tutoring (External Cloud API or Local Ollama), hardware profiling tiers, and advanced model profiles.",
        )}
      />

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-[var(--border)] pb-2">
        <button
          onClick={() => setActiveTab("guru")}
          className={`px-4 py-2 text-xs font-semibold rounded-xl transition-all flex items-center gap-2 ${
            activeTab === "guru"
              ? "bg-[var(--primary)] text-white shadow-sm"
              : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" /> AI Guru Dual-Mode & Hardware
        </button>
        <button
          onClick={() => setActiveTab("advanced")}
          className={`px-4 py-2 text-xs font-semibold rounded-xl transition-all flex items-center gap-2 ${
            activeTab === "advanced"
              ? "bg-[var(--primary)] text-white shadow-sm"
              : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          }`}
        >
          <Sliders className="w-3.5 h-3.5" /> Catalog & Advanced Profiles
        </button>
      </div>

      {activeTab === "guru" ? (
        <AISettings />
      ) : (
        <ServiceConfigEditor service="llm" />
      )}
    </div>
  );
}
