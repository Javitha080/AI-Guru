"use client";

/**
 * Settings tab — Telegram alerts, passcode change (server-enforced current
 * PIN), supervision rules, student pairing, and the security activity log.
 * All feedback inline; no browser alert()/prompt().
 * Ember Glass forms on bento cells.
 */

import React, { useCallback, useEffect, useState } from "react";
import { KeyRound, Loader2, Send, ShieldAlert } from "lucide-react";
import AuditLogPanel from "./AuditLogPanel";
import PairingCard from "./PairingCard";
import { pFetch, pJson } from "@/lib/parent/parent-api";

interface SettingsTabProps {
  parentId: string;
  /** Notify parent page that rules changed (dashboard fallback name). */
  onRulesChanged?: () => void;
}

interface TelegramConfigPayload {
  configured?: boolean;
  bot_token_masked?: string;
  chat_id?: string;
  enabled?: boolean;
}

interface RulesPayload {
  student_name?: string;
  daily_goal_minutes?: number;
  alert_strictness?: string; // gentle | balanced | strict
}

type Strictness = "lenient" | "normal" | "strict";

const inputCls =
  "glass-input w-full text-sm";

export default function SettingsTab({ parentId, onRulesChanged }: SettingsTabProps) {
  // Telegram
  const [tgConfigured, setTgConfigured] = useState(false);
  const [tgMasked, setTgMasked] = useState("");
  const [tgToken, setTgToken] = useState("");
  const [tgChatId, setTgChatId] = useState("");
  const [tgBusy, setTgBusy] = useState(false);
  const [tgStatus, setTgStatus] = useState<{ ok: boolean; text: string } | null>(null);

  // Change PIN
  const [currentPin, setCurrentPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [pinBusy, setPinBusy] = useState(false);
  const [pinStatus, setPinStatus] = useState<{ ok: boolean; text: string } | null>(null);

  // Rules
  const [studentName, setStudentName] = useState("Student");
  const [dailyGoalMinutes, setDailyGoalMinutes] = useState(60);
  const [strictness, setStrictness] = useState<Strictness>("normal");
  const [rulesBusy, setRulesBusy] = useState(false);
  const [rulesStatus, setRulesStatus] = useState<{ ok: boolean; text: string } | null>(null);

  const digitsOnly = (v: string) => v.replace(/\D/g, "");
  const toUiStrictness = (s?: string): Strictness =>
    s === "gentle" ? "lenient" : s === "strict" ? "strict" : "normal";

  useEffect(() => {
    (async () => {
      try {
        const { ok, data } = await pJson<TelegramConfigPayload>(
          `/api/v1/parent/telegram/config?parent_id=${encodeURIComponent(parentId)}`
        );
        if (ok && data?.configured) {
          setTgConfigured(true);
          setTgMasked(data.bot_token_masked || "");
          setTgChatId(data.chat_id || "");
        }
      } catch {
        /* leave defaults */
      }
    })();
  }, [parentId]);

  const hydrateRules = useCallback(async () => {
    try {
      const { ok, data } = await pJson<RulesPayload>(
        `/api/v1/parent/supervision-rules?parent_id=${encodeURIComponent(parentId)}`
      );
      if (ok && data) {
        if (data.student_name) setStudentName(data.student_name);
        if (typeof data.daily_goal_minutes === "number") setDailyGoalMinutes(data.daily_goal_minutes);
        setStrictness(toUiStrictness(data.alert_strictness));
      }
    } catch {
      /* keep defaults */
    }
  }, [parentId]);

  useEffect(() => {
    void hydrateRules();
  }, [hydrateRules]);

  // ------------------------------------------------------------- telegram
  const saveTelegram = async (): Promise<boolean> => {
    // Blank token is allowed when already configured: the backend keeps the
    // saved credential so a Chat-ID-only edit can't silently kill alerts.
    if ((!tgConfigured && !tgToken.trim()) || !tgChatId.trim()) {
      setTgStatus({ ok: false, text: "Fill in BOTH the Bot Token and Chat ID." });
      return false;
    }
    const { ok, data } = await pJson<{ detail?: string }>("/api/v1/parent/telegram/config", {
      method: "POST",
      body: JSON.stringify({
        bot_token: tgToken.trim(),
        chat_id: tgChatId.trim(),
        enabled: true,
        parent_id: parentId,
      }),
    });
    if (!ok) {
      setTgStatus({ ok: false, text: String(data?.detail || "Failed to save Telegram credentials.") });
      return false;
    }
    setTgConfigured(true);
    setTgToken("");
    return true;
  };

  const handleSaveTelegram = async () => {
    setTgBusy(true);
    setTgStatus(null);
    if (await saveTelegram()) {
      setTgStatus({ ok: true, text: "Telegram credentials saved." });
    }
    setTgBusy(false);
  };

  const handleTestTelegram = async () => {
    setTgBusy(true);
    setTgStatus(null);
    if (!(await saveTelegram())) {
      setTgBusy(false);
      return;
    }
    try {
      const { ok, data } = await pJson<{ detail?: string }>(
        `/api/v1/parent/telegram/test?parent_id=${encodeURIComponent(parentId)}`,
        { method: "POST" }
      );
      if (ok) {
        setTgStatus({ ok: true, text: "✅ Test message delivered to your Telegram!" });
        setTgMasked("saved");
      } else {
        setTgStatus({ ok: false, text: `❌ ${data?.detail || "Delivery failed — verify Token and Chat ID."}` });
      }
    } catch {
      setTgStatus({ ok: false, text: "❌ Network error sending test message." });
    }
    setTgBusy(false);
  };

  // ------------------------------------------------------------ change pin
  const handleChangePin = async () => {
    setPinStatus(null);
    if (newPin.length < 4 || newPin.length > 8) {
      setPinStatus({ ok: false, text: "New PIN must be 4–8 digits." });
      return;
    }
    if (newPin !== confirmPin) {
      setPinStatus({ ok: false, text: "New PIN confirmation does not match." });
      return;
    }
    setPinBusy(true);
    try {
      const { ok, status, data } = await pJson<{ detail?: string }>("/api/v1/parent/auth/change-pin", {
        method: "POST",
        body: JSON.stringify({ pin: newPin, current_pin: currentPin, parent_id: parentId }),
      });
      if (ok) {
        setPinStatus({ ok: true, text: "Passcode updated." });
        setCurrentPin("");
        setNewPin("");
        setConfirmPin("");
      } else {
        const detail = String(data?.detail || `Update failed (${status}).`);
        setPinStatus({
          ok: false,
          text: detail === "current_pin_required" ? "Current passcode is required." : detail,
        });
      }
    } catch {
      setPinStatus({ ok: false, text: "Network error updating passcode." });
    } finally {
      setPinBusy(false);
    }
  };

  // ----------------------------------------------------------------- rules
  const backendStrictness = (s: Strictness) =>
    s === "lenient" ? "gentle" : s === "strict" ? "strict" : "balanced";

  const handleSaveRules = async () => {
    setRulesBusy(true);
    setRulesStatus(null);
    try {
      const { ok } = await pFetch("/api/v1/parent/supervision-rules", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_name: studentName.trim() || "Student",
          daily_goal_minutes: Math.min(600, Math.max(10, Number(dailyGoalMinutes) || 60)),
          alert_strictness: backendStrictness(strictness),
          parent_id: parentId,
        }),
      });
      setRulesStatus(
        ok ? { ok: true, text: "Supervision rules saved." } : { ok: false, text: "Failed to save rules." }
      );
      if (ok) onRulesChanged?.();
    } catch {
      setRulesStatus({ ok: false, text: "Error saving rules." });
    } finally {
      setRulesBusy(false);
    }
  };

  const statusBanner = (s: { ok: boolean; text: string }) => (
    <p
      className={`text-xs font-semibold px-3 py-2 rounded-lg border animate-pop-in ${
        s.ok
          ? "text-[var(--primary)] bg-[var(--ember-0)] border-[var(--ember-line)]/35"
          : "text-red-300 bg-red-500/[0.08] border-red-500/30"
      }`}
    >
      {s.text}
    </p>
  );

  return (
    <div className="space-y-5 max-w-3xl">
      <h3 className="font-display text-lg font-bold">Security &amp; Notification Configuration</h3>

      {/* Telegram */}
      <section className="bento-cell space-y-4 p-5" data-section>
        <h4 className="font-semibold text-sm flex items-center gap-2 relative z-[2]">
          <Send size={16} className="text-[var(--primary)]" />
          <span>Telegram Bot Alerts</span>
          {tgConfigured && (
            <span className="ml-auto text-[11px] font-normal text-[var(--primary)] bg-[var(--ember-0)] border border-[var(--ember-line)]/35 rounded-full px-2 py-0.5">
              configured{tgMasked && tgMasked !== "saved" ? ` · ${tgMasked}` : ""}
            </span>
          )}
        </h4>
        <p className="text-xs text-[var(--muted-foreground)] relative z-[2]">
          Create a free bot via @BotFather, then paste the Bot Token and your Chat ID to receive instant alerts and portal links.
        </p>
        <div className="space-y-3 relative z-[2]">
          <label className="block">
            <span className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">Bot Token</span>
            <input type="password" placeholder={tgConfigured ? "Leave blank to keep saved token" : "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"} value={tgToken} onChange={(e) => setTgToken(e.target.value)} className={`${inputCls} font-mono text-xs`} />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">Chat ID</span>
            <input type="text" placeholder="e.g. 987654321" value={tgChatId} onChange={(e) => setTgChatId(e.target.value)} className={`${inputCls} font-mono text-xs`} />
          </label>
          {tgStatus && statusBanner(tgStatus)}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={() => void handleSaveTelegram()}
              disabled={tgBusy}
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] disabled:opacity-50 text-white text-xs font-bold transition-all shadow-[0_4px_16px_var(--glow-primary)] disabled:shadow-none hover:brightness-110 active:scale-95 flex items-center gap-1.5"
            >
              {tgBusy && <Loader2 size={13} className="animate-spin" />} Save Setup
            </button>
            <button
              onClick={() => void handleTestTelegram()}
              disabled={tgBusy}
              className="px-4 py-2 surface-glass-base !rounded-xl disabled:opacity-50 text-xs font-semibold glow-ring transition-colors"
            >
              Save &amp; Send Test Alert
            </button>
          </div>
        </div>
      </section>

      {/* Change passcode */}
      <section className="bento-cell space-y-4 p-5" data-section>
        <h4 className="font-semibold text-sm flex items-center gap-2 relative z-[2]">
          <KeyRound size={16} className="text-[var(--amber)]" />
          <span>Change Parent Passcode PIN</span>
        </h4>
        <p className="text-xs text-[var(--muted-foreground)] relative z-[2]">Requires your CURRENT passcode — enforced server-side.</p>
        <input
          type="password"
          inputMode="numeric"
          maxLength={8}
          placeholder="Current PIN"
          value={currentPin}
          onChange={(e) => setCurrentPin(digitsOnly(e.target.value))}
          className={`${inputCls} text-center font-mono tracking-[0.5em] relative z-[2]`}
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 relative z-[2]">
          <input
            type="password"
            inputMode="numeric"
            maxLength={8}
            placeholder="New PIN (4–8 digits)"
            value={newPin}
            onChange={(e) => setNewPin(digitsOnly(e.target.value))}
            className={`${inputCls} text-center font-mono`}
          />
          <input
            type="password"
            inputMode="numeric"
            maxLength={8}
            placeholder="Confirm New PIN"
            value={confirmPin}
            onChange={(e) => setConfirmPin(digitsOnly(e.target.value))}
            onKeyDown={(e) => e.key === "Enter" && void handleChangePin()}
            className={`${inputCls} text-center font-mono`}
          />
        </div>
        {pinStatus && <div className="relative z-[2]">{statusBanner(pinStatus)}</div>}
        <button
          onClick={() => void handleChangePin()}
          disabled={pinBusy || !currentPin || !newPin}
          className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--amber)] to-[#E8C05F] disabled:opacity-50 text-black text-xs font-bold transition-all shadow-[0_4px_16px_var(--amber-glow)] disabled:shadow-none hover:brightness-110 active:scale-95 flex items-center gap-1.5 relative z-[2]"
        >
          {pinBusy && <Loader2 size={13} className="animate-spin" />} Update Passcode PIN
        </button>
      </section>

      {/* Supervision rules */}
      <section className="bento-cell space-y-4 p-5" data-section>
        <h4 className="font-semibold text-sm flex items-center gap-2 relative z-[2]">
          <ShieldAlert size={16} className="text-[var(--primary)]" />
          <span>Supervision Rules</span>
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 relative z-[2]">
          <label className="block">
            <span className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">Student Name</span>
            <input value={studentName} maxLength={60} onChange={(e) => setStudentName(e.target.value)} className={inputCls} />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">Daily Goal (minutes)</span>
            <input type="number" min={10} max={600} value={dailyGoalMinutes} onChange={(e) => setDailyGoalMinutes(Number(e.target.value))} className={inputCls} />
          </label>
        </div>
        <div className="relative z-[2]">
          <span className="block text-xs font-medium text-[var(--muted-foreground)] mb-1.5">Alert Strictness</span>
          <div className="flex gap-2">
            {(["lenient", "normal", "strict"] as const).map((lvl) => (
              <button
                key={lvl}
                onClick={() => setStrictness(lvl)}
                aria-pressed={strictness === lvl}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all duration-200 ${
                  strictness === lvl
                    ? "bg-[var(--primary)] text-white shadow-[0_4px_14px_var(--glow-primary)] scale-[1.03]"
                    : "surface-glass-base text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {lvl === "lenient" ? "Gentle" : lvl === "normal" ? "Balanced" : "Strict"}
              </button>
            ))}
          </div>
        </div>
        {rulesStatus && <div className="relative z-[2]">{statusBanner(rulesStatus)}</div>}
        <button
          onClick={() => void handleSaveRules()}
          disabled={rulesBusy}
          className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] disabled:opacity-50 text-white text-xs font-bold transition-all shadow-[0_4px_16px_var(--glow-primary)] disabled:shadow-none hover:brightness-110 active:scale-95 flex items-center gap-1.5 relative z-[2]"
        >
          {rulesBusy && <Loader2 size={13} className="animate-spin" />} Save Supervision Rules
        </button>
      </section>

      {/* Student pairing */}
      <PairingCard parentId={parentId} onLinkedChanged={onRulesChanged} />

      {/* Security audit log */}
      <AuditLogPanel parentId={parentId} />
    </div>
  );
}
