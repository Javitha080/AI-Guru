"use client";

/**
 * Parent "Ask Pass" lock screen (standalone portal chrome).
 * Server enforces PBKDF2 + brute-force lockout; this screen surfaces the
 * remaining-tries / lockout messages verbatim and never fakes success.
 * Ember Glass vault card with a GSAP shake on rejected PINs.
 */

import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, KeyRound, Loader2, Lock, ShieldCheck } from "lucide-react";
import { shakeEl } from "@/lib/motion/useGsapReveal";
import { pJson, storeParentTokens } from "@/lib/parent/parent-api";

interface PinLockProps {
  parentId: string;
  onUnlocked: () => void;
  onOpenWizard: () => void;
}

interface VerifyResponse {
  access_token?: string;
  refresh_token?: string;
  detail?: string;
}

export default function PinLock({ parentId, onUnlocked, onOpenWizard }: PinLockProps) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lockoutSecs, setLockoutSecs] = useState(0);
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Lockout countdown: backend reports e.g. "Locked out. Retry in 42s."
  // — disable the form and count down so parents aren't guessing.
  useEffect(() => {
    if (lockoutSecs <= 0) return;
    const t = setTimeout(() => setLockoutSecs((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [lockoutSecs]);

  const locked = lockoutSecs > 0;
  const tooShort = pin.length > 0 && pin.length < 4;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pin || busy || locked || pin.length < 4) return;
    setBusy(true);
    setError(null);
    try {
      const { ok, data } = await pJson<VerifyResponse>("/api/v1/parent/auth/verify-pin", {
        method: "POST",
        body: JSON.stringify({ pin, parent_id: parentId }),
      });
      if (ok && data?.access_token) {
        storeParentTokens(data.access_token, data.refresh_token);
        onUnlocked();
        return;
      }
      const detail = data?.detail || "Invalid Passcode PIN.";
      setError(detail);
      // Surface brute-force lockouts as a countdown, not a static string.
      const m = /(\d+)\s*s/i.exec(detail);
      if (/lock/i.test(detail)) setLockoutSecs(m ? parseInt(m[1], 10) : 30);
      shakeEl(cardRef.current);
    } catch {
      setError("Connection error. Please retry.");
      shakeEl(cardRef.current);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div
        ref={cardRef}
        className="w-full max-w-md bento-cell liquid-sheen !rounded-3xl p-8 text-center"
      >
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-[var(--primary)]/30 to-[var(--amber)]/15 border border-[var(--ember-line)]/40 flex items-center justify-center text-[var(--primary)] shadow-[0_0_32px_var(--glow-primary)]">
          <Lock size={28} />
        </div>

        <h1 className="font-display text-2xl font-bold">AI Guru Parent Portal</h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-2 mb-7">
          Enter your Parent Passcode PIN to access student monitoring.
        </p>

        <form onSubmit={submit} className="space-y-4">
          <input
            type="password"
            inputMode="numeric"
            autoComplete="off"
            maxLength={8}
            autoFocus
            placeholder="••••"
            value={pin}
            disabled={locked}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
            className="glass-input w-full px-4 py-3.5 text-center text-3xl tracking-[0.6em] font-mono focus:!shadow-[0_0_0_3px_var(--glow-primary),inset_0_2px_4px_rgba(0,0,0,0.04)]"
          />
          {tooShort && !locked && (
            <p className="text-[11px] text-[var(--muted-foreground)]">Passcodes are 4–8 digits.</p>
          )}

          {error && (
            <div className="p-3 rounded-xl bg-red-500/[0.08] border border-red-500/30 text-xs text-red-300 flex items-center gap-2 justify-center animate-pop-in">
              <AlertTriangle size={14} className="shrink-0" />
              <span>{error}{locked ? ` Retrying in ${lockoutSecs}s…` : ""}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={busy || locked || pin.length < 4}
            className="w-full py-3.5 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] hover:brightness-110 disabled:opacity-50 disabled:saturate-50 text-white font-bold transition-all duration-[var(--duration-fast,250ms)] ease-[var(--ease-smooth-out)] hover:-translate-y-0.5 hover:shadow-[0_12px_32px_var(--glow-primary)] shadow-[0_8px_28px_var(--glow-primary)] disabled:shadow-none disabled:hover:translate-y-0 flex items-center justify-center gap-2 active:scale-[0.96] active:translate-y-0"
          >
            {busy ? <Loader2 size={17} className="animate-spin" /> : <KeyRound size={17} />}
            <span>{busy ? "Verifying…" : "Unlock Parent Portal"}</span>
          </button>
        </form>

        <div className="mt-6 pt-4 border-t border-[var(--glass-border)] flex items-center justify-between text-xs">
          <button
            onClick={onOpenWizard}
            className="text-[var(--primary)] hover:brightness-125 hover:underline underline-offset-2"
          >
            Forgot passcode / change setup
          </button>
          <span className="text-[var(--muted-foreground)] flex items-center gap-1.5">
            <ShieldCheck size={13} />
            Local encryption active
          </span>
        </div>
      </div>
    </div>
  );
}
