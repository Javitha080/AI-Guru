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
import VoiceTab from "@/components/parent/VoiceTab";
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
import type { IncidentItem, OutboxSnapshot, StudentRow, TunnelSnapshot } from "@/lib/parent/types";

type Tab = "overview" | "analytics" | "voice" | "vault" | "settings";

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  analytics: "Analytics",
  voice: "Voice",
  vault: "Vault",
  settings: "Settings",
};

export default function ParentPortalPage() {
  const parentId = "default";

  // Gate state
  const [hasPinConfigured, setHasPinConfigured] = useState<boolean | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState(false);

  const isAuthenticated = () => Boolean(getParentAccessToken());
  const [authedTick, setAuthedTick] = useState(0); // forces re-render on auth changes
  const authed = isAuthenticated() && hasPinConfigured !== false;

  // Dashboard data
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [studentsError, setStudentsError] = useState<string | null>(null);
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(null);
  const [incidents, setIncidents] = useState<IncidentItem[]>([]);
  const [incidentsLoading, setIncidentsLoading] = useState(true);
  const [liveViewStudent, setLiveViewStudent] = useState<StudentRow | null>(null);

  // Tunnel
  const [tunnel, setTunnel] = useState<TunnelSnapshot>({ status: "inactive", url: null });
  const [tunnelBusy, setTunnelBusy] = useState(false);

  // Telegram outbox depth (offline badge)
  const [outbox, setOutbox] = useState<OutboxSnapshot | null>(null);

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

  // Keep the sliding tab indicator aligned across resize/font-load.
  // The GSAP tween above only runs on tab change; without this the capsule
  // drifts off the active tab after a viewport resize.
  useEffect(() => {
    const reposition = () => {
      const btn = tabRefs.current[activeTab];
      const ind = indicatorRef.current;
      if (!btn || !ind) return;
      gsap.set(ind, { x: btn.offsetLeft, width: btn.offsetWidth });
    };
    window.addEventListener("resize", reposition);
    // Fonts/layout settle after first paint — re-sync once.
    const t = setTimeout(reposition, 300);
    return () => {
      window.removeEventListener("resize", reposition);
      clearTimeout(t);
    };
  }, [activeTab]);

  const TAB_ORDER: Tab[] = ["overview", "analytics", "voice", "vault", "settings"];
  const handleTabKeyDown = (e: React.KeyboardEvent, tab: Tab) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const idx = TAB_ORDER.indexOf(tab);
    const next = e.key === "ArrowRight"
      ? TAB_ORDER[(idx + 1) % TAB_ORDER.length]
      : TAB_ORDER[(idx - 1 + TAB_ORDER.length) % TAB_ORDER.length];
    setActiveTab(next);
    // Move focus to the newly active tab for screen-reader users.
    requestAnimationFrame(() => tabRefs.current[next]?.focus());
  };
  // ------------------------------------------------------------- bootstrap
  // Three states: null = loading, true/false = reached backend, plus a
  // distinct offline error (backend unreachable) that must NOT be confused
  // with "no PIN configured" — previously any network failure opened the
  // setup wizard, misleading parents into re-creating their passcode.
  const [bootstrapRetry, setBootstrapRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { ok, data } = await pJson<{ has_pin?: boolean }>(
          `/api/v1/parent/auth/has-pin?parent_id=${parentId}`
        );
        if (!cancelled) {
          if (ok) {
            setHasPinConfigured(Boolean(data?.has_pin));
            setBootstrapError(null);
          } else {
            setBootstrapError("The AI Guru service is unreachable. Check that the app is running, then retry.");
          }
        }
      } catch {
        if (!cancelled) {
          setBootstrapError("The AI Guru service is unreachable. Check that the app is running, then retry.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [parentId, bootstrapRetry]);

  // Auto-lock when any pFetch exhausts token recovery.
  useEffect(() => {
    const onAuthLost = () => setAuthedTick((t) => t + 1);
    window.addEventListener(PARENT_AUTH_LOST_EVENT, onAuthLost);
    return () => window.removeEventListener(PARENT_AUTH_LOST_EVENT, onAuthLost);
  }, []);

  const refreshDashboard = useCallback(async () => {
    if (!isAuthenticated()) return;
    try {
      const { ok, status, data } = await pJson<StudentRow[]>(`/api/v1/parent/dashboard/${parentId}`);
      if (ok && Array.isArray(data)) {
        setStudents(data);
        setStudentsError(null);
        setSelectedStudentId((prev) =>
          prev && data.some((s) => s.student_id === prev)
            ? prev
            : data[0]?.student_id ?? null
        );
      } else if (!ok) {
        setStudentsError(`Could not load students (${status}). Retrying automatically.`);
      }
    } catch {
      // ParentAuthError (exhausted refresh) is surfaced globally via
      // PARENT_AUTH_LOST_EVENT; network blips keep the last good board.
      setStudentsError("Network error loading students. Retrying automatically.");
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
          provider: data.provider,
          url_is_public: data.url_is_public,
          message: data.message ?? null,
          local_port: data.local_port,
          portal_hint: data.portal_hint ?? null,
          restart_attempts: data.restart_attempts,
        });
      }
    } catch {
      /* keep last known honest status */
    }
  }, []);

  const refreshOutbox = useCallback(async () => {
    if (!isAuthenticated()) return;
    try {
      const { ok, data } = await pJson<OutboxSnapshot>(
        `/api/v1/parent/telegram/outbox?parent_id=${encodeURIComponent(parentId)}`
      );
      if (ok && data) setOutbox(data);
    } catch {
      /* badge is best-effort; keep last known counts */
    }
  }, [parentId]);

  // Authenticated data bootstrap + polling. Dashboard re-polls so a
  // student going live after the portal opened flips to "Studying"
  // without a manual reload; tunnel/outbox keep their own cadences.
  useEffect(() => {
    if (!authed) return;
    void refreshDashboard();
    void refreshTunnel();
    void refreshOutbox();
    const iv = setInterval(() => void refreshTunnel(), 15000);
    const iv2 = setInterval(() => void refreshOutbox(), 30000);
    const iv3 = setInterval(() => void refreshDashboard(), 12000);
    return () => {
      clearInterval(iv);
      clearInterval(iv2);
      clearInterval(iv3);
    };
  }, [authed, authedTick, refreshDashboard, refreshTunnel, refreshOutbox]);

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
    // Guard: starting/reconnecting already has a backend negotiation in
    // flight (serialized by the server start-lock) — re-clicking would only
    // queue duplicate work and flicker the status. Aligned with the setup
    // wizard: any "active" tunnel stops, even while still negotiating.
    if (tunnel.status === "starting" || tunnel.status === "reconnecting") return;
    setTunnelBusy(true);
    try {
      if (tunnel.status === "active") {
        await pFetch("/api/v1/parent/tunnel/stop", { method: "POST" });
        setTunnel({ status: "inactive", url: null, message: null });
      } else {
        // No provider is sent: the backend reuses the saved preference
        // (persisted on the last successful start), defaulting to cloudflare.
        const { ok, data } = await pJson<TunnelSnapshot & { message?: string | null }>(
          "/api/v1/parent/tunnel/start",
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }
        );
        if (ok && data) {
          setTunnel({
            status: data.status ?? "inactive",
            url: data.url ?? null,
            provider: (data as TunnelSnapshot).provider,
            url_is_public: data.url_is_public,
            message: data.message ?? null,
            local_port: data.local_port,
            portal_hint: (data as TunnelSnapshot).portal_hint ?? null,
            restart_attempts: (data as TunnelSnapshot).restart_attempts,
          });
        }
      }
    } catch {
      /* status poll will reconcile */
    } finally {
      setTunnelBusy(false);
      // Reconcile immediately so failed/starting states surface without
      // waiting for the 15s poll.
      void refreshTunnel();
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
  if (hasPinConfigured === null && !bootstrapError) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <RefreshCw size={22} className="animate-spin text-[var(--primary)]" />
      </div>
    );
  }

  if (bootstrapError && hasPinConfigured === null) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="w-full max-w-md bento-cell liquid-sheen !rounded-3xl p-8 text-center space-y-4">
          <h1 className="font-display text-xl font-bold">Service unreachable</h1>
          <p className="text-sm text-[var(--muted-foreground)]">{bootstrapError}</p>
          <button
            onClick={() => {
              setBootstrapError(null);
              setHasPinConfigured(null);
              setBootstrapRetry((n) => n + 1);
            }}
            className="w-full py-3 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white text-sm font-bold hover:brightness-110 active:scale-[0.98] transition-all"
          >
            Retry connection
          </button>
        </div>
      </div>
    );
  }

  if (!authed || showWizard) {
    if (showWizard || !hasPinConfigured) {
      return (
        <ParentWizard
          parentId={parentId}
          hasExistingPin={hasPinConfigured ?? false}
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
                    tabIndex={active ? 0 : -1}
                    onClick={() => setActiveTab(tab)}
                    onKeyDown={(e) => handleTabKeyDown(e, tab)}
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
            studentsError={studentsError}
            onRetryStudents={() => void refreshDashboard()}
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
            outbox={outbox}
          />
        )}

        {activeTab === "analytics" && (
          <AnalyticsTab studentId={selectedStudentId} />
        )}

        {activeTab === "voice" && (
          <VoiceTab
            studentId={selectedStudentId}
            studentName={students.find((s) => s.student_id === selectedStudentId)?.name}
          />
        )}

        {activeTab === "vault" && <VaultTab />}

        {activeTab === "settings" && (
          <SettingsTab
            parentId={parentId}
            onRulesChanged={() => {
              void refreshDashboard();
              void refreshOutbox();
            }}
          />
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
