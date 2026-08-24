"use client";

/**
 * Security audit log panel — renders GET /parent/audit-log/{id}: pin
 * set/change attempts, lockouts, tunnel events, vault seals, logins.
 * Ember Glass list on a bento cell.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, ScrollText } from "lucide-react";
import { pFetch } from "@/lib/parent/parent-api";
import type { AuditEvent } from "@/lib/parent/types";

const ACTION_LABELS: Record<string, string> = {
  "pin.set_initial": "Passcode created",
  "pin.changed": "Passcode changed",
  "pin.change_failed": "Passcode change failed",
  "pin.verify_success": "Portal unlocked",
  "pin.verify_failed": "Wrong passcode attempt",
  "pin.lockout": "Brute-force lockout",
  "auth.logout": "Portal locked",
  "telegram.config_saved": "Telegram config saved",
  "telegram.test_sent": "Telegram test sent",
  "telegram.link_sent": "Portal link sent",
  "tunnel.start": "Tunnel started",
  "tunnel.stop": "Tunnel stopped",
  "vault.sealed": "Vault sealed",
  "vault.decrypted": "Vault item decrypted",
  "vault.decrypt_denied": "Vault decrypt denied (wrong PIN)",
  "rules.updated": "Supervision rules updated",
  "pair.generated": "Pairing code generated",
  "pair.verified": "Pairing verified",
  "pair.revoked": "Pairing revoked",
  "live.snapshot_accessed": "Live snapshot viewed",
};

interface AuditLogPanelProps {
  parentId: string;
}

export default function AuditLogPanel({ parentId }: AuditLogPanelProps) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await pFetch(`/api/v1/parent/audit-log/${encodeURIComponent(parentId)}?limit=50`);
      if (res.ok) setEvents((await res.json()) as AuditEvent[]);
    } catch {
      /* keep previous */
    } finally {
      setLoading(false);
    }
  }, [parentId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="bento-cell space-y-3 p-5">
      <div className="flex items-center justify-between relative z-[2]">
        <h4 className="font-semibold text-sm flex items-center gap-2">
          <ScrollText size={16} className="text-[var(--primary)]" />
          <span>Security Activity Log</span>
        </h4>
        <button onClick={() => void load()} disabled={loading} className="glass-btn-ghost disabled:opacity-40" aria-label="Refresh audit log">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        </button>
      </div>

      {!events ? (
        <p className="text-xs text-[var(--muted-foreground)] py-2 relative z-[2]">Loading…</p>
      ) : events.length === 0 ? (
        <p className="text-xs text-[var(--muted-foreground)] py-2 relative z-[2]">No security activity recorded yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--glass-border)] surface-glass-base rounded-xl overflow-hidden max-h-72 overflow-y-auto relative z-[2]">
          {events.map((e) => {
            const label = ACTION_LABELS[e.action] ?? e.action.replace(/[._]/g, " ");
            const tone =
              e.action.includes("failed") || e.action.includes("lockout") || e.action.includes("denied")
                ? "text-red-300"
                : e.action.includes("success") || e.action.includes("set_initial")
                  ? "text-[var(--primary)]"
                  : "";
            return (
              <li key={e.id || `${e.timestamp}-${e.action}`} className="flex items-center justify-between gap-3 px-3.5 py-2 hover:bg-[var(--ember-0)] transition-colors">
                <div className="min-w-0">
                  <span className={`text-xs font-semibold ${tone}`}>{label}</span>
                  {e.ip_address ? <span className="ml-2 text-[10px] font-mono text-[var(--muted-foreground)] opacity-70">{e.ip_address}</span> : null}
                </div>
                <span className="text-[11px] text-[var(--muted-foreground)] shrink-0">
                  {e.timestamp ? new Date(e.timestamp * 1000).toLocaleString() : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
