"use client";

/**
 * Encrypted Video Vault tab — lists sealed items + pending captures.
 * All PIN entry goes through PinPromptModal (no browser prompt/alert).
 * Ember Glass: sealed tiles, amber encryption identity, honest states.
 */

import React, { useCallback, useEffect, useState } from "react";
import { KeyRound, Loader2, Lock, RefreshCw, ShieldCheck } from "lucide-react";
import PinPromptModal from "./PinPromptModal";
import { pJson } from "@/lib/parent/parent-api";
import type { VaultItem } from "@/lib/parent/types";

interface VaultListPayload {
  items?: VaultItem[];
  pending_count?: number;
}

export default function VaultTab() {
  const [items, setItems] = useState<VaultItem[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [sealOpen, setSealOpen] = useState(false);
  const [decryptTarget, setDecryptTarget] = useState<VaultItem | null>(null);

  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [previewClip, setPreviewClip] = useState<{ frames: string[]; fps: number } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const fetchSnapshots = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { ok, data } = await pJson<VaultListPayload>("/api/v1/parent/vault/snapshots");
      if (!ok || !data) {
        setError("Failed to load vault contents.");
        return;
      }
      setItems(Array.isArray(data.items) ? data.items : []);
      setPendingCount(typeof data.pending_count === "number" ? data.pending_count : 0);
    } catch {
      setError("Network error loading the vault.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchSnapshots();
  }, [fetchSnapshots]);

  const handleSeal = async (pin: string): Promise<string | null> => {
    const { ok, status, data } = await pJson<{ sealed?: number; detail?: string }>("/api/v1/parent/vault/seal", {
      method: "POST",
      body: JSON.stringify({ pin }),
    });
    if (!ok) return String(data?.detail || `Sealing failed (${status}).`);
    setSealOpen(false);
    setNotice(`Sealed ${data?.sealed ?? 0} capture(s) into the encrypted vault.`);
    await fetchSnapshots();
    return null;
  };

  const handleDecrypt = async (pin: string): Promise<string | null> => {
    if (!decryptTarget) return null;
    const { ok, status, data } = await pJson<{
      kind?: string;
      frames_base64?: string[];
      fps?: number;
      image_base64?: string;
      detail?: string;
    }>("/api/v1/parent/vault/decrypt", {
      method: "POST",
      body: JSON.stringify({ clip_id: decryptTarget.clip_id, pin }),
    });
    if (status === 403) return "Wrong Parent Passcode.";
    if (!ok || !data) return "Decryption failed — item missing or corrupted.";
    setDecryptTarget(null);
    if (data.kind === "clip" && Array.isArray(data.frames_base64)) {
      setPreviewClip({ frames: data.frames_base64, fps: Number(data.fps ?? 5) });
      setPreviewImage(null);
    } else if (data.image_base64) {
      setPreviewImage(`data:image/jpeg;base64,${data.image_base64}`);
      setPreviewClip(null);
    }
    return null;
  };

  return (
    <div className="bento-cell p-6 space-y-6">
      <div className="flex items-start justify-between gap-4 relative z-[2]">
        <div>
          <h3 className="font-display text-lg font-bold flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-[var(--amber-glow)] border border-[var(--amber)]/30 text-[var(--amber)] shadow-[0_0_16px_var(--amber-glow)]">
              <Lock size={16} />
            </span>
            <span>Encrypted Local Video Vault</span>
          </h3>
          <p className="text-xs text-[var(--muted-foreground)] mt-1.5 flex items-center gap-1.5">
            <ShieldCheck size={13} className="text-[var(--primary)]" />
            Incident captures are encrypted with your Parent Passcode. Students cannot open raw files on this computer.
          </p>
        </div>
        <button
          onClick={() => void fetchSnapshots()}
          className="glass-btn-ghost shrink-0"
          aria-label="Refresh vault"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {pendingCount > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl bg-[var(--amber-glow)]/50 border border-[var(--amber)]/35 animate-pop-in relative z-[2]">
          <div className="text-sm text-[var(--amber)]">
            <strong>{pendingCount}</strong> monitoring capture(s) staged and waiting to be encrypted.
          </div>
          <button
            onClick={() => setSealOpen(true)}
            className="px-4 py-2 rounded-lg bg-[var(--amber)] text-black text-xs font-bold flex items-center gap-1.5 transition-all hover:brightness-110 active:scale-95 shadow-[0_4px_16px_var(--amber-glow)]"
          >
            <KeyRound size={14} /> Seal Now
          </button>
        </div>
      )}

      {error && (
        <p className="text-xs text-red-300 bg-red-500/[0.08] border border-red-500/30 rounded-xl px-3 py-2.5 relative z-[2]">
          {error}
        </p>
      )}

      {notice && !error && (
        <p className="text-xs font-semibold text-[var(--primary)] bg-[var(--ember-0)] border border-[var(--ember-line)]/35 rounded-xl px-3 py-2.5 animate-pop-in relative z-[2]">
          {notice}
        </p>
      )}

      {/* Decrypted previews */}
      {previewClip && (
        <div className="rounded-xl p-4 border border-[var(--amber)]/25 bg-black/40 relative z-[2] animate-pop-in">
          <h4 className="text-sm font-semibold text-[var(--amber)] mb-3">
            Decrypted clip · {previewClip.frames.length} frames @ {previewClip.fps} fps
          </h4>
          <div className="flex gap-2 overflow-x-auto pb-2">
            {previewClip.frames.map((f, i) => (
              <img
                key={i}
                src={`data:image/jpeg;base64,${f}`}
                alt={`Frame ${i + 1}`}
                className="h-40 rounded-lg object-contain bg-black shrink-0 border border-[var(--glass-border)]"
              />
            ))}
          </div>
          <button
            onClick={() => setPreviewClip(null)}
            className="mt-3 px-4 py-1.5 surface-glass-base !rounded-lg text-xs font-medium glow-ring"
          >
            Close Preview
          </button>
        </div>
      )}
      {previewImage && (
        <div className="rounded-xl p-4 inline-block border border-[var(--amber)]/25 bg-black/40 relative z-[2] animate-pop-in">
          <h4 className="text-sm font-semibold text-[var(--amber)] mb-2">Decrypted snapshot</h4>
          <img src={previewImage} alt="Decrypted snapshot" className="max-h-80 rounded-xl object-contain border border-[var(--glass-border)]" />
          <button
            onClick={() => setPreviewImage(null)}
            className="mt-3 px-4 py-1.5 surface-glass-base !rounded-lg text-xs font-medium glow-ring"
          >
            Close Preview
          </button>
        </div>
      )}

      {/* Vault grid — sealed envelopes */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 relative z-[2]">
        {loading ? (
          <div className="col-span-full py-12 flex justify-center text-[var(--muted-foreground)]">
            <Loader2 size={22} className="animate-spin text-[var(--primary)]" />
          </div>
        ) : items.length === 0 ? (
          <div className="col-span-full py-12 text-center text-[var(--muted-foreground)]">
            <Lock size={36} className="mx-auto mb-3 opacity-40" />
            <p className="text-sm">No encrypted incident clips in the vault yet.</p>
            <p className="text-xs mt-1">Captures appear here after monitoring incidents are recorded and sealed.</p>
          </div>
        ) : (
          items.map((item) => (
            <div
              key={item.clip_id}
              className="bento-cell bento-cell--hover tilt-glare p-4 flex flex-col justify-between space-y-3 group"
            >
              <div className="min-w-0 relative z-[2]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] px-2 py-0.5 rounded-md bg-[var(--amber-glow)]/70 text-[var(--amber)] border border-[var(--amber)]/30 font-mono">
                    {item.event_type}
                  </span>
                  <Lock size={13} className="text-[var(--muted-foreground)] transition-colors duration-300 group-hover:text-[var(--amber)]" />
                </div>
                <p className="text-[11px] font-mono text-[var(--muted-foreground)] mt-2 truncate">{item.clip_id}</p>
                <p className="text-[11px] text-[var(--muted-foreground)]/80 mt-0.5">
                  {item.timestamp ? new Date(item.timestamp * 1000).toLocaleString() : "—"}
                </p>
              </div>
              <button
                onClick={() => setDecryptTarget(item)}
                className="w-full py-2 rounded-lg bg-[var(--amber)]/15 hover:bg-[var(--amber)] hover:text-black text-[var(--amber)] border border-[var(--amber)]/35 text-xs font-bold flex items-center justify-center gap-1.5 transition-all duration-200 active:scale-[0.98] relative z-[2]"
              >
                <KeyRound size={14} />
                <span>Decrypt &amp; View</span>
              </button>
            </div>
          ))
        )}
      </div>

      <PinPromptModal
        open={sealOpen}
        title="Encrypt Pending Captures"
        description="Enter your Parent Passcode to encrypt all staged monitoring captures into the vault."
        confirmLabel="Seal Captures"
        onSubmit={handleSeal}
        onClose={() => setSealOpen(false)}
      />
      <PinPromptModal
        open={decryptTarget !== null}
        title="Decrypt Vault Item"
        description="Enter your Parent Passcode to decrypt and view this local recording."
        confirmLabel="Decrypt"
        onSubmit={handleDecrypt}
        onClose={() => setDecryptTarget(null)}
      />
    </div>
  );
}
