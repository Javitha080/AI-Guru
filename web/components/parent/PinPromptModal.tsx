"use client";

/**
 * Accessible PIN-entry modal — replaces every browser prompt()/alert() in the
 * parent portal (vault seal/decrypt etc.). Returns errors inline; the caller
 * decides what success means via onSubmit. Ember Glass styling; wrong PINs
 * shake the card via GSAP.
 */

import React, { useEffect, useRef, useState } from "react";
import { KeyRound, Loader2, X } from "lucide-react";
import { shakeEl } from "@/lib/motion/useGsapReveal";

interface PinPromptModalProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  /** Compatibility alias for confirmLabel (older call sites). */
  submitLabel?: string;
  /** Optional external busy override (call sites that manage their own state). */
  busy?: boolean;
  /** Optional externally-controlled error line shown above internal ones. */
  error?: string | null;
  /** Return an error string to show; resolving/returning null/void = success. */
  onSubmit: (pin: string) => Promise<string | null | void> | string | null | void;
  onClose: () => void;
}

export default function PinPromptModal({
  open,
  title,
  description,
  confirmLabel,
  submitLabel,
  busy: externalBusy,
  error: externalError,
  onSubmit,
  onClose,
}: PinPromptModalProps) {
  const [pin, setPin] = useState("");
  const [internalError, setInternalError] = useState<string | null>(null);
  const [internalBusy, setInternalBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const busy = Boolean(externalBusy) || internalBusy;
  const error = externalError ?? internalError;
  const actionLabel = submitLabel ?? confirmLabel ?? "Confirm";

  useEffect(() => {
    if (open) {
      // Reset the entry form each time the modal opens.
      /* eslint-disable react-hooks/set-state-in-effect */
      setPin("");
      setInternalError(null);
      setInternalBusy(false);
      /* eslint-enable react-hooks/set-state-in-effect */
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  if (!open) return null;

  const submit = async () => {
    if (!pin || busy) return;
    setInternalBusy(true);
    setInternalError(null);
    try {
      const err = await onSubmit(pin);
      if (typeof err === "string" && err.length > 0) {
        setInternalError(err);
        setInternalBusy(false);
        shakeEl(cardRef.current);
      }
      // On success the caller closes the modal via onClose().
    } catch {
      setInternalError("Unexpected error. Please retry.");
      setInternalBusy(false);
      shakeEl(cardRef.current);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center p-4 animate-overlay-in"
      style={{ background: "var(--overlay)", backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)" }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        ref={cardRef}
        className="w-full max-w-sm bento-cell liquid-sheen !rounded-2xl p-6 space-y-4 animate-pop-in"
      >
        <div className="flex items-start justify-between gap-3 relative z-[2]">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-[var(--amber-glow)] border border-[var(--amber)]/35 flex items-center justify-center text-[var(--amber)] shadow-[0_0_16px_var(--amber-glow)]">
              <KeyRound size={17} />
            </div>
            <h3 className="text-sm font-bold">{title}</h3>
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            className="glass-btn-ghost disabled:opacity-40"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {description && (
          <p className="text-xs text-[var(--muted-foreground)] leading-relaxed relative z-[2]">{description}</p>
        )}

        <input
          ref={inputRef}
          type="password"
          inputMode="numeric"
          autoComplete="off"
          maxLength={8}
          placeholder="Parent Passcode PIN"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
            if (e.key === "Escape" && !busy) onClose();
          }}
          className="glass-input w-full px-4 py-3 text-center text-2xl font-mono tracking-[0.5em] relative z-[2]"
        />

        {error && (
          <p className="text-xs font-semibold text-red-300 bg-red-500/[0.08] border border-red-500/30 rounded-lg px-3 py-2 relative z-[2] animate-pop-in">
            {error}
          </p>
        )}

        <button
          onClick={() => void submit()}
          disabled={!pin || busy}
          className="w-full py-2.5 rounded-xl bg-gradient-to-r from-[var(--amber)] to-[#E8C05F] hover:brightness-110 disabled:opacity-40 text-black text-sm font-bold transition-all flex items-center justify-center gap-2 active:scale-[0.98] relative z-[2] shadow-[0_6px_20px_var(--amber-glow)] disabled:shadow-none"
        >
          {busy && <Loader2 size={15} className="animate-spin" />}
          <span>{busy ? "Working…" : actionLabel}</span>
        </button>
      </div>
    </div>
  );
}
