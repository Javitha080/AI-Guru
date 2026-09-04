"use client";

/**
 * AI Guru — Parent Setup Wizard.
 *
 * Fixes over the legacy inline wizard:
 * - Detects an EXISTING PIN and switches to the current-PIN + new-PIN change
 *   flow (the old code always posted set-pin without current_pin → 403).
 * - Digits-only PIN inputs; weak codes are rejected server-side with the
 *   reason surfaced inline.
 * - Telegram credentials are SAVED when leaving step 2 (and skipped when
 *   blank so a good config is never overwritten with empty values).
 * - Tunnel start sends NO port — the backend targets the configured frontend
 *   port so {tunnel}/parent serves this portal remotely.
 * - Supervision rules persist on Finish before entering the portal.
 *
 * Ember Glass chrome: glowing stepper rail, bento step cards, terracotta CTAs.
 */

import React, { useState } from "react";
import {
  ArrowLeft, Bot, CheckCircle2, ChevronRight, Globe, KeyRound,
  Loader2, Lock, Send, ShieldCheck, Sparkles, User,
} from "lucide-react";
import { pFetch, pJson, storeParentTokens } from "@/lib/parent/parent-api";
import {
  STRICTNESS_LABEL,
  toBackendStrictness,
  UI_STRICTNESS,
  type UiStrictness as Strictness,
} from "@/lib/parent/strictness";

interface ParentWizardProps {
  parentId: string;
  hasExistingPin: boolean;
  onCancel?: () => void;
  /** Called once setup finished AND the portal holds valid tokens. */
  onEnterPortal: () => void;
}

const STEPS = [
  { step: 1, label: "Passcode PIN", icon: KeyRound },
  { step: 2, label: "Telegram Bot", icon: Bot },
  { step: 3, label: "Tunnel Access", icon: Globe },
  { step: 4, label: "Supervision Rules", icon: ShieldCheck },
] as const;

interface VerifyResponse {
  access_token?: string;
  refresh_token?: string;
}

export default function ParentWizard({ parentId, hasExistingPin, onCancel, onEnterPortal }: ParentWizardProps) {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);

  // Step 1 — PIN
  const [currentPin, setCurrentPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);

  // Step 2 — Telegram
  const [tgToken, setTgToken] = useState("");
  const [tgChatId, setTgChatId] = useState("");
  const [tgStatus, setTgStatus] = useState<{ ok: boolean; text: string } | null>(null);

  // Step 3 — Tunnel
  const [provider, setProvider] = useState<"cloudflare" | "ngrok">("cloudflare");
  const [ngrokToken, setNgrokToken] = useState("");
  const [tunnelStatus, setTunnelStatus] = useState<string | null>(null);
  const [tunnelUrl, setTunnelUrl] = useState<string | null>(null);
  const [tunnelMsg, setTunnelMsg] = useState<string | null>(null);

  // Step 4 — Rules
  const [studentName, setStudentName] = useState("Student");
  const [dailyGoalMinutes, setDailyGoalMinutes] = useState(60);
  const [strictness, setStrictness] = useState<Strictness>("normal");

  const digitsOnly = (v: string) => v.replace(/\D/g, "");

  const authenticateWith = async (pin: string): Promise<boolean> => {
    try {
      const { ok, data } = await pJson<VerifyResponse>("/api/v1/parent/auth/verify-pin", {
        method: "POST",
        body: JSON.stringify({ pin, parent_id: parentId }),
      });
      if (ok && data?.access_token) {
        storeParentTokens(data.access_token, data.refresh_token);
        return true;
      }
    } catch {
      /* fallthrough */
    }
    return false;
  };

  const handleSavePin = async () => {
    setPinError(null);
    if (newPin.length < 4 || newPin.length > 8) {
      setPinError("PIN must be 4–8 digits.");
      return;
    }
    if (newPin !== confirmPin) {
      setPinError("PIN confirmation does not match.");
      return;
    }
    if (hasExistingPin && !currentPin) {
      setPinError("Enter your CURRENT passcode to authorize the change.");
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = { pin: newPin, parent_id: parentId };
      if (hasExistingPin) body.current_pin = currentPin;
      const res = await pFetch("/api/v1/parent/auth/set-pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}) as Record<string, unknown>);
      if (!res.ok) {
        const detail = String((data as Record<string, unknown>).detail ?? "Failed to save PIN.");
        setPinError(detail === "current_pin_required"
          ? "Current passcode was incorrect or missing."
          : detail);
        return;
      }
      // Immediately obtain tokens so later wizard steps can persist config.
      if (await authenticateWith(newPin)) {
        setStep(2);
      } else {
        setPinError("Passcode saved, but sign-in failed. Use it on the lock screen.");
      }
    } catch {
      setPinError("Network error while saving the passcode.");
    } finally {
      setBusy(false);
    }
  };

  const saveTelegram = async (): Promise<boolean> => {
    if (!tgToken.trim() || !tgChatId.trim()) return false; // skip empty — never overwrite good config
    try {
      const res = await pFetch("/api/v1/parent/telegram/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_token: tgToken.trim(),
          chat_id: tgChatId.trim(),
          enabled: true,
          parent_id: parentId,
        }),
      });
      return res.ok;
    } catch {
      return false;
    }
  };

  const handleTestTelegram = async () => {
    if (!tgToken.trim() || !tgChatId.trim()) {
      setTgStatus({ ok: false, text: "Fill in BOTH the Bot Token and Chat ID first." });
      return;
    }
    setBusy(true);
    setTgStatus({ ok: true, text: "Saving credentials…" });
    let saved = false;
    try {
      saved = await saveTelegram();
    } catch {
      saved = false;
    }
    if (!saved) {
      setTgStatus({ ok: false, text: "Could not save credentials." });
      setBusy(false);
      return;
    }
    try {
      const res = await pFetch(`/api/v1/parent/telegram/test?parent_id=${parentId}`, { method: "POST" });
      if (res.ok) {
        setTgStatus({ ok: true, text: "✅ Test message delivered to your Telegram!" });
      } else {
        const err = await res.json().catch(() => ({}) as { detail?: string });
        setTgStatus({ ok: false, text: `❌ ${err.detail || "Delivery failed — verify Token and Chat ID."}` });
      }
    } catch {
      setTgStatus({ ok: false, text: "❌ Network error sending test message." });
    } finally {
      setBusy(false);
    }
  };

  const handleContinueTelegram = async () => {
    setBusy(true);
    try {
      await saveTelegram();
    } catch {
      /* session recovery is handled globally; continue to tunnel step */
    }
    setBusy(false);
    setStep(3);
  };

  const handleToggleTunnel = async () => {
    setBusy(true);
    setTunnelMsg(null);
    try {
      if (tunnelStatus === "active") {
        await pFetch("/api/v1/parent/tunnel/stop", { method: "POST" });
        setTunnelStatus("inactive");
        setTunnelUrl(null);
      } else {
        // The start request is synchronous: the first run downloads the
        // cloudflared engine (~18 MB) before the URL is negotiated, so set
        // an honest expectation while the button shows "Working…".
        setTunnelMsg(
          provider === "cloudflare"
            ? "Requesting tunnel… the first run downloads the engine once (~18 MB)."
            : "Requesting tunnel…"
        );
        const { ok, data } = await pJson<{ status?: string; url?: string | null; message?: string | null; url_is_public?: boolean }>(
          "/api/v1/parent/tunnel/start",
          { method: "POST", body: JSON.stringify({ provider, ngrok_token: ngrokToken.trim() || undefined }) }
        );
        if (ok && data) {
          setTunnelStatus(data.status ?? "unknown");
          setTunnelUrl(data.url ?? null);
          setTunnelMsg(
            data.url_is_public ? null : data.message || null
          );
        }
      }
    } catch {
      setTunnelStatus("error");
      setTunnelMsg("Could not reach the tunnel gateway — check your connection.");
    } finally {
      setBusy(false);
    }
  };

  const handleFinish = async () => {
    setBusy(true);
    try {
      await pFetch("/api/v1/parent/supervision-rules", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_name: studentName.trim() || "Student",
          daily_goal_minutes: Math.min(600, Math.max(10, Number(dailyGoalMinutes) || 60)),
          alert_strictness: toBackendStrictness(strictness),
          parent_id: parentId,
        }),
      });
    } catch {
      /* non-fatal — rules can be saved later from Settings */
    } finally {
      setBusy(false);
    }
    onEnterPortal();
  };

  const inputCls = "glass-input w-full text-xs font-mono";
  const pinInputCls =
    "glass-input w-full px-4 py-3 text-center text-2xl font-mono tracking-widest focus:!shadow-[0_0_0_3px_var(--glow-primary),inset_0_2px_4px_rgba(0,0,0,0.04)]";
  const navBtn =
    "px-4 py-3 surface-glass-base !rounded-2xl glow-ring text-xs font-bold transition-colors inline-flex items-center justify-center disabled:opacity-40";
  const primaryBtn =
    "bg-gradient-to-r from-[var(--primary)] to-[#E8895F] hover:brightness-110 active:scale-[0.99] text-white font-bold shadow-[0_8px_28px_var(--glow-primary)] transition-all flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:shadow-none";

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bento-cell liquid-sheen !rounded-3xl p-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--glass-border)] pb-5 relative z-[2]">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[var(--primary)]/30 to-[var(--amber)]/15 border border-[var(--ember-line)]/40 flex items-center justify-center text-[var(--primary)] shadow-[0_0_24px_var(--glow-primary)]">
              <Sparkles size={23} />
            </div>
            <div>
              <h2 className="font-display text-xl font-bold">AI Guru — Parent Setup Wizard</h2>
              <p className="text-xs text-[var(--muted-foreground)]">
                {hasExistingPin ? "Update your passcode, alerts, tunnel, and supervision rules" : "Configure Passcode PIN, Telegram alerts, and Outbound Tunnel"}
              </p>
            </div>
          </div>
          {hasExistingPin && (
            <button
              onClick={onCancel}
              className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] text-xs px-3 py-1.5 rounded-xl surface-glass-base transition-colors"
            >
              Cancel
            </button>
          )}
        </div>

        {/* Stepper */}
        <div className="relative z-[2] flex items-center justify-between px-2">
          {STEPS.map((item) => {
            const Icon = item.icon;
            const isDone = step > item.step;
            const isCurrent = step === item.step;
            return (
              <div key={item.step} className="flex items-center gap-2">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 ${
                    isDone
                      ? "bg-[var(--primary)]/25 text-[var(--primary)] border border-[var(--ember-line)]/50"
                      : isCurrent
                        ? "bg-gradient-to-br from-[var(--primary)] to-[#E8895F] text-white shadow-[0_0_18px_var(--glow-primary)] scale-110"
                        : "surface-glass-base text-[var(--muted-foreground)]"
                  }`}
                >
                  {isDone ? <CheckCircle2 size={14} /> : item.step === step ? <Icon size={14} /> : item.step}
                </div>
                <span className={`text-xs font-semibold hidden sm:inline ${isCurrent ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}>
                  {item.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* STEP 1: PASSCODE */}
        {step === 1 && (
          <div className="space-y-5 animate-pop-in">
            <div className="p-4 rounded-2xl surface-glass-base space-y-1">
              <h4 className="text-sm font-bold flex items-center gap-2">
                <Lock size={16} className="text-[var(--amber)]" />
                <span>{hasExistingPin ? "Change Parent Security Passcode" : "Create Parent Security Passcode"}</span>
              </h4>
              <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
                This PIN protects the Parent Portal so students cannot change rules, turn off monitoring, or view encrypted incident recordings. Use 4–8 unique digits (not sequential or repeated).
              </p>
            </div>

            {hasExistingPin && (
              <div>
                <label className="block text-xs font-semibold mb-1.5">Current Passcode</label>
                <input
                  type="password"
                  inputMode="numeric"
                  maxLength={8}
                  autoFocus
                  placeholder="Current PIN"
                  value={currentPin}
                  onChange={(e) => setCurrentPin(digitsOnly(e.target.value))}
                  className={pinInputCls}
                />
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1.5">New 4–8 Digit PIN</label>
                <input
                  type="password"
                  inputMode="numeric"
                  maxLength={8}
                  autoFocus={!hasExistingPin}
                  placeholder="e.g. 7391"
                  value={newPin}
                  onChange={(e) => setNewPin(digitsOnly(e.target.value))}
                  className={pinInputCls}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1.5">Confirm PIN</label>
                <input
                  type="password"
                  inputMode="numeric"
                  maxLength={8}
                  placeholder="Repeat PIN"
                  value={confirmPin}
                  onChange={(e) => setConfirmPin(digitsOnly(e.target.value))}
                  onKeyDown={(e) => e.key === "Enter" && void handleSavePin()}
                  className={pinInputCls}
                />
              </div>
            </div>

            {pinError && (
              <p className="text-xs font-semibold text-red-300 bg-red-500/[0.08] border border-red-500/30 rounded-lg px-3 py-2 animate-pop-in">
                {pinError}
              </p>
            )}

            <button
              onClick={() => void handleSavePin()}
              disabled={busy || !newPin || newPin.length < 4}
              className={`w-full py-3.5 rounded-2xl text-sm ${primaryBtn}`}
            >
              {busy ? <Loader2 size={17} className="animate-spin" /> : null}
              <span>{busy ? "Saving…" : "Save Passcode & Continue"}</span>
              {!busy && <ChevronRight size={17} />}
            </button>
          </div>
        )}

        {/* STEP 2: TELEGRAM */}
        {step === 2 && (
          <div className="space-y-5 animate-pop-in">
            <div className="p-4 rounded-2xl surface-glass-base space-y-2">
              <h4 className="text-sm font-bold flex items-center gap-2">
                <Send size={16} className="text-[var(--primary)]" />
                <span>How to connect your Telegram in 2 minutes:</span>
              </h4>
              <ol className="text-xs space-y-1.5 list-decimal pl-4 text-[var(--muted-foreground)]">
                <li>Open Telegram on your phone and search for <strong className="text-[var(--primary)]">@BotFather</strong>.</li>
                <li>Send <code className="text-[var(--amber)] bg-[var(--muted)] px-1 py-0.5 rounded font-mono">/newbot</code> and copy the <strong>HTTP API Token</strong>.</li>
                <li>Search for <strong className="text-[var(--primary)]">@userinfobot</strong> and click Start to get your <strong>Chat ID</strong>.</li>
                <li>Optional — you can skip this and configure it anytime from Settings.</li>
              </ol>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold mb-1">Telegram Bot Token</label>
                <input type="password" placeholder="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ" value={tgToken} onChange={(e) => setTgToken(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Your Telegram Chat ID</label>
                <input type="text" placeholder="e.g. 987654321" value={tgChatId} onChange={(e) => setTgChatId(e.target.value)} className={inputCls} />
              </div>

              {tgStatus && (
                <p className={`text-xs font-semibold p-2.5 rounded-xl border animate-pop-in ${
                  tgStatus.ok ? "text-[var(--primary)] bg-[var(--ember-0)] border-[var(--ember-line)]/35" : "text-red-300 bg-red-500/[0.08] border-red-500/30"
                }`}>
                  {tgStatus.text}
                </p>
              )}

              <button
                onClick={() => void handleTestTelegram()}
                disabled={busy}
                className="w-full py-2.5 surface-glass-base !rounded-xl disabled:opacity-40 text-xs font-bold glow-ring flex items-center justify-center gap-1.5 transition-colors"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                <span>Save &amp; Send Test Alert to Phone</span>
              </button>
            </div>

            <div className="flex gap-2 pt-2">
              <button onClick={() => setStep(1)} className={navBtn}><ArrowLeft size={16} /></button>
              <button onClick={() => void handleContinueTelegram()} disabled={busy} className={`flex-1 py-3 rounded-2xl text-xs ${primaryBtn}`}>
                <span>Continue to Tunnel Gateway</span>
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {/* STEP 3: TUNNEL */}
        {step === 3 && (
          <div className="space-y-5 animate-pop-in">
            <div className="p-4 rounded-2xl surface-glass-base space-y-1">
              <h4 className="text-sm font-bold flex items-center gap-2">
                <Globe size={16} className="text-[var(--primary)]" />
                <span>Choose Remote Access Tunnel</span>
              </h4>
              <p className="text-xs text-[var(--muted-foreground)]">
                Enables you to open this portal when away from home (cellular / office network) without opening router ports. The link always points at the portal UI — no port juggling.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setProvider("cloudflare")}
                aria-pressed={provider === "cloudflare"}
                className={`p-4 rounded-2xl border text-left transition-all duration-200 ${
                  provider === "cloudflare"
                    ? "border-[var(--ember-line)] bg-[var(--ember-0)] shadow-[0_0_20px_var(--glow-primary)]"
                    : "border-[var(--glass-border)] bg-transparent text-[var(--muted-foreground)] hover:border-[var(--glass-border-highlight)]"
                }`}
              >
                <span className="font-bold text-sm block">Cloudflare Tunnel</span>
                <span className="text-[11px] mt-1 block text-[var(--muted-foreground)]">✨ Recommended: Free • No Account • Auto Link</span>
              </button>
              <button
                onClick={() => setProvider("ngrok")}
                aria-pressed={provider === "ngrok"}
                className={`p-4 rounded-2xl border text-left transition-all duration-200 ${
                  provider === "ngrok"
                    ? "border-[var(--amber)]/50 bg-[var(--amber-glow)]/40 shadow-[0_0_20px_var(--amber-glow)]"
                    : "border-[var(--glass-border)] bg-transparent text-[var(--muted-foreground)] hover:border-[var(--glass-border-highlight)]"
                }`}
              >
                <span className="font-bold text-sm block">Ngrok Gateway</span>
                <span className="text-[11px] mt-1 block text-[var(--muted-foreground)]">Requires Ngrok account &amp; auth token</span>
              </button>
            </div>

            {provider === "ngrok" && (
              <div>
                <label className="block text-xs font-semibold mb-1">Ngrok Auth Token</label>
                <input type="password" placeholder="Paste your ngrok authtoken" value={ngrokToken} onChange={(e) => setNgrokToken(e.target.value)} className={inputCls} />
              </div>
            )}

            <div className="p-3.5 rounded-xl surface-glass-base flex items-center justify-between gap-3">
              <div className="min-w-0">
                <span className="text-xs font-semibold">Tunnel Status: </span>
                <span className={`text-xs font-bold font-mono ${
                  tunnelStatus === "active"
                    ? "text-[var(--primary)]"
                    : tunnelStatus === "error"
                      ? "text-red-300"
                      : "text-[var(--muted-foreground)]"
                }`}>
                  {(tunnelStatus ?? "not started").toUpperCase()}
                </span>
                {tunnelUrl && <p className="text-[10px] text-[var(--amber)] font-mono mt-0.5 truncate">{tunnelUrl}/parent</p>}
                {tunnelMsg && (
                  <p className="text-[10px] text-[var(--amber)] mt-0.5 break-words">{tunnelMsg}</p>
                )}
              </div>
              <button
                onClick={() => void handleToggleTunnel()}
                disabled={busy}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold shrink-0 transition-all active:scale-95 ${
                  tunnelStatus === "active"
                    ? "surface-glass-base hover:!border-red-500/40 hover:text-red-300"
                    : "bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white shadow-[0_4px_14px_var(--glow-primary)] hover:brightness-110"
                }`}
              >
                {busy ? "Working…" : tunnelStatus === "active" ? "Stop" : "Start Tunnel"}
              </button>
            </div>

            <div className="flex gap-2 pt-2">
              <button onClick={() => setStep(2)} className={navBtn}><ArrowLeft size={16} /></button>
              <button onClick={() => setStep(4)} className={`flex-1 py-3 rounded-2xl text-xs ${primaryBtn}`}>
                <span>Continue to Rules &amp; Profile</span>
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {/* STEP 4: RULES */}
        {step === 4 && (
          <div className="space-y-5 animate-pop-in">
            <div className="p-4 rounded-2xl surface-glass-base space-y-1">
              <h4 className="text-sm font-bold flex items-center gap-2">
                <User size={16} className="text-[var(--primary)]" />
                <span>Student Profile &amp; Supervision Preferences</span>
              </h4>
              <p className="text-xs text-[var(--muted-foreground)]">Customize the student name, daily goal, and AI nudge strictness.</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1">Student First Name</label>
                <input type="text" value={studentName} maxLength={60} onChange={(e) => setStudentName(e.target.value)} className={`${inputCls} !font-body`} />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Daily Target (Minutes)</label>
                <input type="number" min={10} max={600} value={dailyGoalMinutes} onChange={(e) => setDailyGoalMinutes(Number(e.target.value))} className={`${inputCls} !font-body`} />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold mb-2">AI Nudge Strictness</label>
              <div className="grid grid-cols-3 gap-2">
                {(UI_STRICTNESS).map((lvl) => (
                  <button
                    key={lvl}
                    onClick={() => setStrictness(lvl)}
                    aria-pressed={strictness === lvl}
                    className={`py-2 px-3 rounded-xl border text-xs font-bold capitalize transition-all duration-200 ${
                      strictness === lvl
                        ? "border-[var(--ember-line)] bg-[var(--ember-0)] text-[var(--primary)] shadow-[0_0_16px_var(--glow-primary)]"
                        : "border-[var(--glass-border)] bg-transparent text-[var(--muted-foreground)] hover:border-[var(--glass-border-highlight)]"
                    }`}
                  >
                    {STRICTNESS_LABEL[lvl]}
                  </button>
                ))}
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-[var(--ember-0)] border border-[var(--ember-line)]/40 flex items-center gap-3">
              <CheckCircle2 size={24} className="text-[var(--primary)] shrink-0" />
              <div className="text-xs">
                <strong className="text-[var(--primary)] block font-bold">All Set!</strong>
                <p className="mt-0.5">Parent Passcode active{tgToken ? ", Telegram connected" : ""}. You can adjust everything later in Settings.</p>
              </div>
            </div>

            <div className="flex gap-2">
              <button onClick={() => setStep(3)} className={navBtn}><ArrowLeft size={16} /></button>
              <button
                onClick={() => void handleFinish()}
                disabled={busy}
                className={`flex-1 py-3.5 rounded-2xl text-sm ${primaryBtn}`}
              >
                {busy ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
                <span>Finish Setup &amp; Open Parent Portal</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
