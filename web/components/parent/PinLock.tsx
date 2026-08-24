"use client";

/**
 * Parent "Ask Pass" lock screen (standalone portal chrome).
 * Server enforces PBKDF2 + brute-force lockout; this screen surfaces the
 * remaining-tries / lockout messages verbatim and never fakes success.
 * Ember Glass vault card with a GSAP shake on rejected PINs.
 */

import React, { useRef, useState } from "react";
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
  const cardRef = useRef<HTMLDivElement | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pin || busy) return;
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
      setError(data?.detail || "Invalid Passcode PIN.");
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
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
            className="glass-input w-full px-4 py-3.5 text-center text-3xl tracking-[0.6em] font-mono focus:!shadow-[0_0_0_3px_var(--glow-primary),inset_0_2px_4px_rgba(0,0,0,0.04)]"
          />

          {error && (
            <div className="p-3 rounded-xl bg-red-500/[0.08] border border-red-500/30 text-xs text-red-300 flex items-center gap-2 justify-center animate-pop-in">
              <AlertTriangle size={14} className="shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !pin}
            className="w-full py-3.5 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] hover:brightness-110 disabled:opacity-50 disabled:saturate-50 text-white font-bold transition-all shadow-[0_8px_28px_var(--glow-primary)] disabled:shadow-none flex items-center justify-center gap-2 active:scale-[0.98]"
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
            Change setup / PIN
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
