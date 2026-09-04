"use client";

/**
 * Student pairing card — wires the previously-unreachable backend endpoints:
 * POST /pair/generate, POST /pair/verify, GET /linked-students/{id},
 * POST /pair/revoke/{link_id}. Real data only; honest empty states.
 * Ember Glass bento cell.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Link2, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { pFetch, pJson } from "@/lib/parent/parent-api";

interface LinkedStudent {
  student_id: string;
  student_name?: string;
  link_id?: string;
  permissions?: Record<string, boolean>;
  paired_at?: number;
}

interface GeneratePayload {
  code?: string;
  expires_in?: number;
  detail?: string;
}

interface PairingCardProps {
  parentId: string;
  onLinkedChanged?: () => void;
}

export default function PairingCard({ parentId, onLinkedChanged }: PairingCardProps) {
  const [linked, setLinked] = useState<LinkedStudent[]>([]);
  const [code, setCode] = useState<{ code: string; expiresAt: number | null } | null>(null);
  const [verifyInput, setVerifyInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  const refreshLinked = useCallback(async () => {
    try {
      const res = await pFetch(`/api/v1/parent/linked-students/${encodeURIComponent(parentId)}`);
      if (res.ok) setLinked((await res.json()) as LinkedStudent[]);
    } catch {
      /* keep previous list */
    }
  }, [parentId]);

  useEffect(() => {
    void refreshLinked();
  }, [refreshLinked]);

  const handleGenerate = async () => {
    setBusy(true);
    setStatus(null);
    try {
      const { ok, data } = await pJson<GeneratePayload>("/api/v1/parent/pair/generate", {
        method: "POST",
        body: JSON.stringify({ student_id: "student-primary", parent_id: parentId }),
      });
      if (ok && data?.code) {
        // Backend returns a TTL (expires_in seconds), not a timestamp.
        const ttl = typeof data.expires_in === "number" ? data.expires_in : 900;
        setCode({ code: data.code, expiresAt: Date.now() / 1000 + ttl });
        await refreshLinked();
        onLinkedChanged?.();
      } else {
        setStatus({ ok: false, text: data?.detail || "Could not generate a pairing code." });
      }
    } catch {
      setStatus({ ok: false, text: "Network error generating code." });
    } finally {
      setBusy(false);
    }
  };

  const handleVerify = async () => {
    if (!verifyInput.trim()) return;
    setBusy(true);
    setStatus(null);
    try {
      const { ok, data } = await pJson<Record<string, unknown>>("/api/v1/parent/pair/verify", {
        method: "POST",
        body: JSON.stringify({ parent_id: parentId, code: verifyInput.trim() }),
      });
      if (ok) {
        setStatus({ ok: true, text: "Pairing verified — student linked." });
        setVerifyInput("");
        setCode(null);
        await refreshLinked();
        onLinkedChanged?.();
      } else {
        setStatus({ ok: false, text: String(data?.detail || "Invalid or expired code.") });
      }
    } catch {
      setStatus({ ok: false, text: "Network error verifying code." });
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (linkId: string) => {
    setBusy(true);
    try {
      await pFetch(`/api/v1/parent/pair/revoke/${encodeURIComponent(linkId)}`, { method: "POST" });
      await refreshLinked();
      onLinkedChanged?.();
    } catch {
      /* best-effort */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bento-cell space-y-4 p-5">
      <div className="flex items-center justify-between relative z-[2]">
        <h4 className="font-semibold text-sm flex items-center gap-2">
          <Link2 size={16} className="text-[var(--primary)]" />
          <span>Student Pairing</span>
        </h4>
        <button onClick={() => void refreshLinked()} className="glass-btn-ghost" aria-label="Refresh linked students">
          <RefreshCw size={14} />
        </button>
      </div>
      <p className="text-xs text-[var(--muted-foreground)] relative z-[2]">
        Link a student device so the dashboard tracks them by name and honors per-student permissions.
      </p>

      <div className="flex flex-wrap gap-2 relative z-[2]">
        <button
          onClick={() => void handleGenerate()}
          disabled={busy}
          className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] disabled:opacity-40 text-white text-xs font-bold transition-all shadow-[0_4px_16px_var(--glow-primary)] disabled:shadow-none hover:brightness-110 active:scale-95 flex items-center gap-1.5"
        >
          {busy && <Loader2 size={13} className="animate-spin" />}
          Generate Pairing Code
        </button>
      </div>

      {code && (
        <div className="p-3.5 rounded-xl surface-glass-base space-y-1 animate-pop-in relative z-[2]">
          <span className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">Enter this code on the student device</span>
          <p className="font-mono text-lg font-bold tracking-[0.25em] text-[var(--primary)] [text-shadow:0_0_18px_var(--glow-primary)]">{code.code}</p>
          {code.expiresAt ? (
            <p className="text-[11px] text-[var(--muted-foreground)]">Expires {new Date(code.expiresAt * 1000).toLocaleTimeString()}</p>
          ) : null}
        </div>
      )}

      <div className="flex gap-2 relative z-[2]">
        <input
          type="text"
          placeholder="Paste a code to verify/link…"
          value={verifyInput}
          onChange={(e) => setVerifyInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void handleVerify()}
          className="glass-input flex-1 !py-2 text-xs font-mono"
        />
        <button
          onClick={() => void handleVerify()}
          disabled={busy || !verifyInput.trim()}
          className="px-3 py-2 surface-glass-base !rounded-xl disabled:opacity-40 text-xs font-semibold glow-ring transition-colors"
        >
          Verify
        </button>
      </div>

      {status && (
        <p
          className={`text-xs font-semibold px-3 py-2 rounded-lg border animate-pop-in relative z-[2] ${
            status.ok
              ? "text-[var(--primary)] bg-[var(--ember-0)] border-[var(--ember-line)]/35"
              : "text-red-300 bg-red-500/[0.08] border-red-500/30"
          }`}
        >
          {status.text}
        </p>
      )}

      <div className="relative z-[2]">
        <span className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)] block mb-1.5">Linked students</span>
        {linked.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)]">No students paired yet — the portal monitors this computer&apos;s primary student.</p>
        ) : (
          <ul className="space-y-1.5">
            {linked.map((s) => (
              <li key={s.student_id} className="flex items-center justify-between px-3 py-2 rounded-lg surface-glass-base transition-colors hover:border-[var(--ember-line)]/35">
                <div className="min-w-0">
                  <span className="text-xs font-semibold">{s.student_name || s.student_id}</span>
                  {s.permissions?.can_view_live === false && (
                    <span className="ml-2 text-[10px] text-[var(--muted-foreground)]">(live view off)</span>
                  )}
                </div>
                {s.link_id && (
                  <button
                    onClick={() => void handleRevoke(s.link_id as string)}
                    disabled={busy}
                    className="p-1.5 rounded-lg surface-glass-base glow-ring text-[var(--muted-foreground)] hover:!text-red-300 transition-colors disabled:opacity-40"
                    aria-label={`Unpair ${s.student_name || s.student_id}`}
                    title="Unpair"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
