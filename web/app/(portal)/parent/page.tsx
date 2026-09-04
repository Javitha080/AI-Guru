"use client";

/**
 * AI Guru — Parent Portal (standalone route group).
 *
 * Auth model: server-enforced 'Ask Pass' gate. Tokens live in sessionStorage;
 * pFetch auto-refreshes (single-flight) and broadcasts `aiguru:parent-auth-lost`
 * when the session cannot be recovered — this page listens and re-locks.
 *
 * Ember Glass chrome: floating frosted command header + GSAP-sliding
 * tab capsule. All auth/data logic unchanged.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Lock, RefreshCw, Settings, ShieldCheck } from "lucide-react";
import gsap from "gsap";
import AnalyticsTab from "@/components/parent/AnalyticsTab";
import OverviewTab from "@/components/parent/OverviewTab";
import ParentWizard from "@/components/parent/ParentWizard";
import PinLock from "@/components/parent/PinLock";
import SettingsTab from "@/components/parent/SettingsTab";
import VaultTab from "@/components/parent/VaultTab";
import LiveVideoView from "@/components/parent/LiveVideoView";
import { motionOK, useGSAP } from "@/lib/motion/useGsapReveal";
import {
  clearParentTokens,
  getParentAccessToken,
  getParentRefreshToken,
  PARENT_AUTH_LOST_EVENT,
  pFetch,
  pJson,
} from "@/lib/parent/parent-api";
import type { IncidentItem, StudentRow, TunnelSnapshot } from "@/lib/parent/types";

type Tab = "overview" | "analytics" | "vault" | "settings";

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  analytics: "Analytics",
  vault: "Vault",
  settings: "Settings",
};

export default function ParentPortalPage() {
  const parentId = "default";

  // Gate state
  const [hasPinConfigured, setHasPinConfigured] = useState<boolean | null>(null);
  const [showWizard, setShowWizard] = useState(false);

  const isAuthenticated = () => Boolean(getParentAccessToken());
  const [authedTick, setAuthedTick] = useState(0); // forces re-render on auth changes
  const authed = isAuthenticated() && hasPinConfigured !== false;

  // Dashboard data
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(null);
  const [incidents, setIncidents] = useState<IncidentItem[]>([]);
  const [incidentsLoading, setIncidentsLoading] = useState(true);
  const [liveViewStudent, setLiveViewStudent] = useState<StudentRow | null>(null);

  // Tunnel
  const [tunnel, setTunnel] = useState<TunnelSnapshot>({ status: "inactive", url: null });
  const [tunnelBusy, setTunnelBusy] = useState(false);

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  // Dedicated in-flight guard for the send-link action (previously reused a
  // misnamed shared ref and reported neither success nor failure).
  const sendLinkBusyRef = useRef(false);
  const [sendLinkStatus, setSendLinkStatus] = useState<{ ok: boolean; text: string } | null>(null);

  // Sliding tab capsule (GSAP)
  const tabRefs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({});
  const indicatorRef = useRef<HTMLSpanElement | null>(null);
  const firstTabPaint = useRef(true);

  useGSAP(
    () => {
      const btn = tabRefs.current[activeTab];
      const ind = indicatorRef.current;
      if (!btn || !ind) return;
      const x = btn.offsetLeft;
      const w = btn.offsetWidth;
      if (!motionOK() || firstTabPaint.current) {
        gsap.set(ind, { x, width: w });
        firstTabPaint.current = false;
        return;
      }
      gsap.to(ind, { x, width: w, duration: 0.38, ease: "power3.out" });
    },
    { dependencies: [activeTab] }
  );

  // ------------------------------------------------------------- bootstrap
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { ok, data } = await pJson<{ has_pin?: boolean }>(
          `/api/v1/parent/auth/has-pin?parent_id=${parentId}`
        );
        if (!cancelled && ok) setHasPinConfigured(Boolean(data?.has_pin));
      } catch {
        if (!cancelled) {
          setHasPinConfigured(false);
          setShowWizard(true); // backend unreachable → setup entry point still visible
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [parentId]);

  // Auto-lock when any pFetch exhausts token recovery.
  useEffect(() => {
    const onAuthLost = () => setAuthedTick((t) => t + 1);
    window.addEventListener(PARENT_AUTH_LOST_EVENT, onAuthLost);
    return () => window.removeEventListener(PARENT_AUTH_LOST_EVENT, onAuthLost);
  }, []);

  const refreshDashboard = useCallback(async () => {
    if (!isAuthenticated()) return;
    try {
      const { ok, data } = await pJson<StudentRow[]>(`/api/v1/parent/dashboard/${parentId}`);
      if (ok && Array.isArray(data)) {
        setStudents(data);
        setSelectedStudentId((prev) =>
          prev && data.some((s) => s.student_id === prev)
            ? prev
            : data[0]?.student_id ?? null
        );
      }
    } catch {
      // ParentAuthError (exhausted refresh) is surfaced globally via
      // PARENT_AUTH_LOST_EVENT; network blips keep the last good board.
    }
  }, [parentId]);

  const refreshIncidents = useCallback(async (studentId: string | null) => {
    if (!studentId || !isAuthenticated()) return;
    setIncidentsLoading(true);
    try {
      const { ok, data } = await pJson<{ recent_incidents?: IncidentItem[] }>(
        `/api/v1/parent/sessions/${encodeURIComponent(studentId)}`
      );
      if (ok && data) {
        setIncidents(Array.isArray(data.recent_incidents) ? data.recent_incidents : []);
      } else {
        setIncidents([]);
      }
    } catch {
      setIncidents([]);
    } finally {
      setIncidentsLoading(false);
    }
  }, []);

  const refreshTunnel = useCallback(async () => {
    if (!isAuthenticated()) return;
    try {
      const { ok, data } = await pJson<TunnelSnapshot>("/api/v1/parent/tunnel/status");
      if (ok && data) {
        setTunnel({
          status: data.status ?? "inactive",
          url: data.url ?? null,
          url_is_public: data.url_is_public,
          message: data.message ?? null,
          local_port: data.local_port,
        });
      }
    } catch {
      /* keep last known honest status */
    }
  }, []);

  // Authenticated data bootstrap + tunnel polling.
  useEffect(() => {
    if (!authed) return;
    void refreshDashboard();
    void refreshTunnel();
    const iv = setInterval(() => void refreshTunnel(), 15000);
    return () => clearInterval(iv);
  }, [authed, authedTick, refreshDashboard, refreshTunnel]);

  useEffect(() => {
    if (!authed) return;
    void refreshIncidents(selectedStudentId);
  }, [authed, selectedStudentId, refreshIncidents]);

  // ---------------------------------------------------------------- actions
  const handleUnlocked = () => {
    setAuthedTick((t) => t + 1);
  };

  const handleLock = async () => {
    const refresh = getParentRefreshToken();
    try {
      await pFetch("/api/v1/parent/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
    } catch {
      /* best-effort */
    }
    clearParentTokens();
    setActiveTab("overview");
    setStudents([]);
    setSelectedStudentId(null);
    setAuthedTick((t) => t + 1);
  };

  const handleWizardDone = () => {
    setShowWizard(false);
    setAuthedTick((t) => t + 1);
  };

  const handleToggleTunnel = async () => {
    setTunnelBusy(true);
    try {
      if (tunnel.status === "active" && tunnel.url_is_public) {
        await pFetch("/api/v1/parent/tunnel/stop", { method: "POST" });
        setTunnel({ status: "inactive", url: null, message: null });
      } else {
        const { ok, data } = await pJson<TunnelSnapshot & { message?: string | null }>(
          "/api/v1/parent/tunnel/start",
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }
        );
        if (ok && data) {
          setTunnel({
            status: data.status ?? "inactive",
            url: data.url ?? null,
            url_is_public: data.url_is_public,
            message: data.message ?? null,
            local_port: data.local_port,
          });
        }
      }
    } catch {
      /* status poll will reconcile */
    } finally {
      setTunnelBusy(false);
    }
  };

  const handleSendLink = async () => {
    if (sendLinkBusyRef.current) return;
    sendLinkBusyRef.current = true;
    setSendLinkStatus(null);
    try {
      const name = students.find((s) => s.student_id === selectedStudentId)?.name ?? "Student";
      const { ok, data } = await pJson<{ detail?: string; mode?: string }>(
        `/api/v1/parent/telegram/send-link?parent_id=${parentId}&student_name=${encodeURIComponent(name)}`,
        { method: "POST" }
      );
      setSendLinkStatus(
        ok
          ? { ok: true, text: `Portal link sent via Telegram${data?.mode === "lan" ? " (home Wi-Fi only — tunnel not active)" : ""}.` }
          : { ok: false, text: String(data?.detail || "Could not send the link — check Telegram setup.") }
      );
    } catch {
      setSendLinkStatus({ ok: false, text: "Network error sending the link." });
    } finally {
      sendLinkBusyRef.current = false;
    }
  };

  // ----------------------------------------------------------------- render
  if (hasPinConfigured === null) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <RefreshCw size={22} className="animate-spin text-[var(--primary)]" />
      </div>
    );
  }

  if (!authed || showWizard) {
    if (showWizard || !hasPinConfigured) {
      return (
        <ParentWizard
          parentId={parentId}
          hasExistingPin={hasPinConfigured}
          onCancel={hasPinConfigured ? () => setShowWizard(false) : undefined}
          onEnterPortal={() => {
            setShowWizard(false);
            setHasPinConfigured(true);
            handleWizardDone();
          }}
        />
      );
    }
    return (
      <PinLock
        parentId={parentId}
        onUnlocked={handleUnlocked}
        onOpenWizard={() => setShowWizard(true)}
      />
    );
  }

  return (
    <div className="min-h-screen">
      {/* Floating glass command header */}
      <header className="sticky top-0 z-40 px-4 pt-4">
        <div className="surface-glass-base liquid-sheen rounded-2xl max-w-7xl mx-auto overflow-hidden">
          <div className="relative z-[2] max-w-7xl mx-auto px-5 py-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[var(--primary)]/30 to-[var(--amber)]/15 border border-[var(--ember-line)]/40 flex items-center justify-center text-[var(--primary)] shadow-[0_0_20px_var(--glow-primary)]">
                <ShieldCheck size={19} />
              </div>
              <div>
                <h1 className="font-display text-lg font-bold leading-tight">AI Guru Parent Portal</h1>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Real-time monitoring · Telegram alerts · encrypted local reporting
                </p>
              </div>
              <span className="ml-2 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/40 hidden sm:flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)] ember-dot" />
                Authenticated
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowWizard(true)}
                className="glass-btn-secondary !rounded-xl inline-flex items-center gap-1.5 !py-2 !px-3.5 text-sm"
              >
                <Settings size={15} />
                <span>Setup</span>
              </button>
              <button
                onClick={() => void handleLock()}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/35 rounded-xl text-sm font-semibold transition-colors glow-ring"
              >
                <Lock size={15} />
                <span>Lock</span>
              </button>
            </div>
          </div>

          {/* Sliding capsule tabs */}
          <nav className="relative z-[2] max-w-7xl mx-auto px-5 pb-2.5">
            <div role="tablist" aria-label="Portal sections" className="relative flex gap-1">
              <span
                ref={indicatorRef}
                aria-hidden
                className="absolute top-1 bottom-1 left-0 rounded-full bg-[var(--ember-0)] border border-[var(--ember-line)]/45 shadow-[0_0_18px_var(--glow-primary)] pointer-events-none"
                style={{ width: 0 }}
              />
              {(Object.keys(TAB_LABELS) as Tab[]).map((tab) => {
                const active = activeTab === tab;
                return (
                  <button
                    key={tab}
                    ref={(el) => {
                      tabRefs.current[tab] = el;
                    }}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveTab(tab)}
                    className={`relative z-10 px-4 py-2 rounded-full text-sm font-bold transition-colors duration-200 ${
                      active
                        ? "text-[var(--primary)]"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {TAB_LABELS[tab]}
                  </button>
                );
              })}
            </div>
          </nav>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-5 py-6">
        {activeTab === "overview" && (
          <OverviewTab
            students={students}
            incidents={incidents}
            incidentsLoading={incidentsLoading}
            selectedStudentId={selectedStudentId}
            onSelectStudent={(id) => setSelectedStudentId(id)}
            onOpenReports={(id) => {
              setSelectedStudentId(id);
              setActiveTab("analytics");
            }}
            onLiveView={(s) => setLiveViewStudent(s)}
            onSendTunnelLink={() => void handleSendLink()}
            sendLinkStatus={sendLinkStatus}
            tunnel={tunnel}
            tunnelBusy={tunnelBusy}
            onToggleTunnel={() => void handleToggleTunnel()}
          />
        )}

        {activeTab === "analytics" && (
          <AnalyticsTab studentId={selectedStudentId} />
        )}

        {activeTab === "vault" && <VaultTab />}

        {activeTab === "settings" && (
          <SettingsTab parentId={parentId} onRulesChanged={() => void refreshDashboard()} />
        )}
      </main>

      {liveViewStudent && (
        <LiveVideoView
          studentName={liveViewStudent.name}
          sessionId={null}
          studentId={liveViewStudent.student_id}
          onClose={() => setLiveViewStudent(null)}
        />
      )}
    </div>
  );
}
