"use client";

/**
 * Student identity enrollment card — photo-upload + live re-verify.
 * The photo is analyzed server-side and discarded; only the face embedding
 * is stored (encrypted). Works in both system-camera and browser modes:
 * - "Upload photo": file upload (POST /enroll-from-photo).
 * - "Use camera preview": examines the current pre-flight preview frame and
 *   uploads it (POST /enroll-from-photo). Available in both modes.
 * - "Use server camera" (system mode only): enrolls straight from the server
 *   camera (POST /enroll-from-camera, median template, no upload).
 * Re-verify is always a one-shot snapshot check (never enrolls).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
  UserCheck,
} from "lucide-react";
import { FACE_ENROLLED_KEY, monitoringApi } from "@/lib/monitoring/monitoringApi";
import { apiFetch } from "@/lib/api";

interface IdentityStatus {
  enrolled: boolean;
  identity_mode: string;
  dimension: number;
  sface_available: boolean;
  persisted: boolean;
}

interface VerifyResult {
  enrolled: boolean;
  match?: boolean | null;
  similarity: number;
  identity_mode: string;
  threshold: number;
  reason: string;
}

interface IdentityEnrollmentCardProps {
  /** Current camera preview as a data URL (system snapshot or video capture). */
  getSnapshot?: () => string | null;
  /** True when the pre-flight is using the server-side system camera. */
  systemMode?: boolean;
  onEnrolled?: () => void;
}

function dataUrlToBlob(dataUrl: string): Blob | null {
  try {
    const [head, b64] = dataUrl.split(",");
    const mime = /data:(.*?);/.exec(head)?.[1] || "image/jpeg";
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  } catch {
    return null;
  }
}

export default function IdentityEnrollmentCard({
  getSnapshot,
  systemMode,
  onEnrolled,
}: IdentityEnrollmentCardProps) {
  const [status, setStatus] = useState<IdentityStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"upload" | "camera" | "verify" | "remove" | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "warn" | "error"; text: string } | null>(null);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [previewName, setPreviewName] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setStatusFailed(false);
    setStatusError(null);
    try {
      const res = await apiFetch(monitoringApi.identityStatus);
      if (!res.ok) {
        if (res.status === 401) throw new Error("Sign-in required — identity check needs auth.");
        throw new Error(`Identity check failed (HTTP ${res.status}). Is the backend running?`);
      }
      const s = (await res.json()) as IdentityStatus;
      setStatus(s);
      // Heal the local enrolled flag when the server still has a baseline
      // (backend restarts used to strand the client in a false "enrolled"
      // state — and the reverse after a server-side clear).
      try {
        if (s.enrolled) window.localStorage.setItem(FACE_ENROLLED_KEY, "1");
        else window.localStorage.removeItem(FACE_ENROLLED_KEY);
      } catch {
        /* storage unavailable */
      }
    } catch (err) {
      setStatusFailed(true);
      setStatusError(
        err instanceof TypeError
          ? "Backend unreachable — start the backend (port 8001) and retry."
          : err instanceof Error
            ? err.message
            : "Identity status unavailable — enrollment needs the backend."
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const uploadBlob = useCallback(
    async (blob: Blob, label: string, force: boolean) => {
      setBusy("upload");
      setNotice(null);
      setVerify(null);
      try {
        const form = new FormData();
        form.append("photo", blob, label);
        const res = await apiFetch(monitoringApi.enrollFromPhoto(force), {
          method: "POST",
          body: form,
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data?.enrolled) {
          try {
            window.localStorage.setItem(FACE_ENROLLED_KEY, "1");
          } catch {
            /* ignore */
          }
          setConfirmReplace(false);
          setPreviewName(null);
          setNotice({ kind: "ok", text: String(data.message || "Face enrolled.") });
          await load();
          onEnrolled?.();
        } else if (res.ok && data?.already_enrolled) {
          setConfirmReplace(true);
          setNotice({
            kind: "warn",
            text: "A face is already enrolled on this device. Replace it with this photo?",
          });
        } else {
          const detail = String(
            data?.detail || data?.reason || `HTTP ${res.status}`
          ).replace(/_/g, " ");
          setNotice({
            kind: "error",
            text:
              res.status === 503
                ? `Server vision engine unavailable — ${detail}`
                : `Could not enroll this photo — ${detail}`,
          });
        }
      } catch {
        setNotice({ kind: "error", text: "Upload failed — backend unreachable." });
      } finally {
        setBusy(null);
      }
    },
    [load, onEnrolled]
  );

  const enrollViaServerCamera = useCallback(async () => {
    setBusy("camera");
    setNotice(null);
    setVerify(null);
    try {
      const res = await apiFetch(monitoringApi.enrollFromCamera(confirmReplace), {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data?.enrolled) {
        try {
          window.localStorage.setItem(FACE_ENROLLED_KEY, "1");
        } catch {
          /* ignore */
        }
        setConfirmReplace(false);
        setNotice({
          kind: "ok",
          text:
            data?.identity_mode === "sface"
              ? `Enrolled from server camera (neural, ${data?.samples ?? ""} samples).`.replace("  ", " ")
              : "Enrolled from server camera (basic mode).",
        });
        await load();
        onEnrolled?.();
      } else if (data?.already_enrolled) {
        setConfirmReplace(true);
        setNotice({
          kind: "warn",
          text: "A face is already enrolled on this device. Press again to replace it from the server camera.",
        });
      } else {
        const reason = String(data?.reason || data?.detail || `HTTP ${res.status}`).replace(/_/g, " ");
        if (reason.includes("no face")) {
          setNotice({
            kind: "error",
            text: "Server camera saw no face — sit centered in good light, or use the preview snapshot below.",
          });
        } else if (res.status === 503 || reason.includes("unavailable")) {
          setNotice({
            kind: "error",
            text: `Server camera unavailable — ${reason}. Use the preview snapshot instead.`,
          });
        } else {
          setNotice({ kind: "error", text: `Server-camera enroll failed — ${reason}.` });
        }
      }
    } catch {
      setNotice({ kind: "error", text: "Server-camera enroll failed — backend unreachable." });
    } finally {
      setBusy(null);
    }
  }, [confirmReplace, load, onEnrolled]);

  const onFileChosen = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      e.target.value = "";
      if (!f) return;
      setPreviewName(f.name);
      void uploadBlob(f, f.name, confirmReplace);
    },
    [confirmReplace, uploadBlob]
  );

  const usePreviewPhoto = useCallback(() => {
    const snap = getSnapshot?.() ?? null;
    if (!snap) {
      setNotice({ kind: "warn", text: "No camera preview available yet." });
      return;
    }
    const blob = dataUrlToBlob(snap);
    if (!blob) {
      setNotice({ kind: "error", text: "Could not read the preview frame." });
      return;
    }
    void uploadBlob(blob, "camera-preview.jpg", confirmReplace);
  }, [confirmReplace, getSnapshot, uploadBlob]);

  const reverify = useCallback(async () => {
    const snap = getSnapshot?.() ?? null;
    if (!snap) {
      setNotice({ kind: "warn", text: "No camera preview available yet — wait for the live feed, then retry." });
      return;
    }
    const b64 = snap.includes(",") ? snap.split(",")[1] : snap;
    setBusy("verify");
    setNotice(null);
    try {
      const res = await apiFetch(monitoringApi.verifyIdentity, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jpeg_b64: b64 }),
      });
      const data = (await res.json().catch(() => null)) as (VerifyResult & { detail?: string }) | null;
      if (!res.ok || !data) throw new Error(String((data as { detail?: string } | null)?.detail || "verify failed"));
      setVerify(data);
    } catch (err) {
      setNotice({
        kind: "error",
        text: err instanceof TypeError
          ? "Verification check failed — backend unreachable."
          : `Verification check failed — ${err instanceof Error ? err.message : "try again."}`,
      });
    } finally {
      setBusy(null);
    }
  }, [getSnapshot]);

  const remove = useCallback(async () => {
    if (!window.confirm("Remove the enrolled face? Monitoring will run unverified until you enroll again.")) return;
    setBusy("remove");
    setNotice(null);
    try {
      const res = await apiFetch(monitoringApi.clearBaseline, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      try {
        window.localStorage.removeItem(FACE_ENROLLED_KEY);
      } catch {
        /* ignore */
      }
      setVerify(null);
      setConfirmReplace(false);
      setNotice({ kind: "ok", text: "Enrolled face removed." });
      await load();
    } catch {
      setNotice({ kind: "error", text: "Could not remove the enrolled face." });
    } finally {
      setBusy(null);
    }
  }, [load]);

  const enrolled = status?.enrolled === true;
  const modeLabel =
    status == null
      ? "checking…"
      : !enrolled
        ? "Not enrolled"
        : status.identity_mode === "sface"
          ? "Enrolled · neural"
          : "Enrolled · basic";

  return (
    <div className="p-3 rounded-xl surface-glass-base border border-[var(--glass-border)] space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold flex items-center gap-1.5 text-[var(--muted-foreground)]">
          <UserCheck size={15} className="text-[var(--primary)]" />
          Student Identity
        </span>
        <span
          className={`text-[10px] px-2 py-0.5 rounded-full font-bold tracking-wide border ${
            enrolled
              ? status?.identity_mode === "sface"
                ? "bg-[var(--ember-0)] text-[var(--primary)] border-[var(--ember-line)]/40"
                : "bg-[var(--amber-glow)]/60 text-[var(--amber)] border-[var(--amber)]/35"
              : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--glass-border)]"
          }`}
        >
          {modeLabel}
        </span>
      </div>

      {statusFailed ? (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {statusError || "Identity status unavailable — enrollment needs the backend."}{" "}
          <button onClick={() => void load()} className="underline font-bold hover:text-[var(--primary)]">
            Retry
          </button>
        </p>
      ) : (
        <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed">
          {enrolled
            ? status?.identity_mode === "sface"
              ? "This device recognizes the student. Only matching faces count as present."
              : "Enrolled in basic mode — re-enroll once the neural model is active for real impostor detection."
            : "Upload a clear front-facing photo so Vision Guard knows who is studying. The photo is analyzed and discarded — only a face signature is kept, encrypted on this device."}
        </p>
      )}

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={onFileChosen}
        aria-label="Upload student photo"
      />

      <div className="flex flex-wrap gap-1.5">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy !== null}
          className="flex-1 min-w-[120px] px-3 py-1.5 rounded-lg bg-gradient-to-r from-[var(--primary)] to-[#E8895F] disabled:opacity-50 text-white text-xs font-bold transition-all flex items-center justify-center gap-1.5 hover:brightness-110 active:scale-95"
        >
          {busy === "upload" ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
          <span>{enrolled ? (confirmReplace ? "Confirm replace" : "Replace photo") : "Upload photo"}</span>
        </button>
        <button
          onClick={usePreviewPhoto}
          disabled={busy !== null}
          title="Examine the current preview frame and enroll from it (upload)"
          className="flex-1 min-w-[120px] px-3 py-1.5 rounded-lg surface-glass-base glow-ring text-xs font-bold transition-colors flex items-center justify-center gap-1.5 hover:text-[var(--primary)] disabled:opacity-50"
        >
          {busy === "upload" ? <Loader2 size={13} className="animate-spin" /> : <Camera size={13} />}
          <span>Use camera preview</span>
        </button>
      </div>
      {systemMode && (
        <button
          onClick={() => void enrollViaServerCamera()}
          disabled={busy !== null}
          title="Enroll straight from the server camera (median template, no upload)"
          className="w-full px-3 py-1.5 rounded-lg surface-glass-base border border-[var(--glass-border)] text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 hover:text-[var(--primary)] disabled:opacity-50"
        >
          {busy === "camera" ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
          <span>{confirmReplace ? "Replace from server camera" : "Use server camera"}</span>
        </button>
      )}

      {previewName && (
        <p className="text-[10px] text-[var(--muted-foreground)] truncate">Selected: {previewName}</p>
      )}

      {enrolled && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          <button
            onClick={() => void reverify()}
            disabled={busy !== null}
            className="flex-1 min-w-[110px] px-3 py-1.5 rounded-lg surface-glass-base border border-[var(--glass-border)] text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 hover:text-[var(--primary)] disabled:opacity-50"
          >
            {busy === "verify" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            <span>Re-verify live</span>
          </button>
          <button
            onClick={() => void remove()}
            disabled={busy !== null}
            className="px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            {busy === "remove" ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
            <span>Remove</span>
          </button>
        </div>
      )}

      {verify && (
        <div
          className={`p-2.5 rounded-lg text-[11px] flex items-start gap-1.5 border ${
            verify.match
              ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/25"
              : verify.match === false
                ? "bg-red-500/10 text-red-300 border-red-500/25"
                : "bg-[var(--amber-glow)]/50 text-[var(--amber)] border-[var(--amber)]/30"
          }`}
        >
          {verify.match ? (
            <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          )}
          <span>
            {verify.match == null
              ? `Could not judge this frame (${verify.reason.replace(/_/g, " ")}).`
              : verify.match
                ? `Match — similarity ${(verify.similarity * 100).toFixed(0)}% (needs ${(verify.threshold * 100).toFixed(0)}%).`
                : `No match — similarity ${(verify.similarity * 100).toFixed(0)}% (needs ${(verify.threshold * 100).toFixed(0)}%). Sit centered in good light and retry.`}
          </span>
        </div>
      )}

      {notice && (
        <div
          className={`p-2.5 rounded-lg text-[11px] flex items-start gap-1.5 border ${
            notice.kind === "ok"
              ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/25"
              : notice.kind === "warn"
                ? "bg-[var(--amber-glow)]/50 text-[var(--amber)] border-[var(--amber)]/30"
                : "bg-red-500/10 text-red-300 border-red-500/25"
          }`}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span className="flex-1">{notice.text}</span>
          {notice.kind === "warn" && confirmReplace && (
            <button
              onClick={() => setConfirmReplace(false)}
              className="shrink-0 underline font-bold hover:brightness-110"
            >
              Keep
            </button>
          )}
        </div>
      )}

      {enrolled && !status?.sface_available && (
        <p className="text-[10px] text-[var(--muted-foreground)] leading-relaxed flex items-start gap-1">
          <ShieldCheck size={11} className="mt-0.5 shrink-0" />
          <span>Neural recognition inactive on the server — basic mode cannot tell people apart reliably.</span>
        </p>
      )}
    </div>
  );
}
