"use client";

/**
 * Parent Voice Drop-in — call the student mid-study.
 *
 * Two transports, best-first:
 * 1. WebRTC voice (auto-answered by the study room, time-boxed, audited).
 * 2. Text announcement fallback (spoken aloud student-side via TTS).
 *
 * Signaling goes through the local backend over plain HTTPS polling so it
 * works through the Next /api rewrite (which does not proxy WS upgrades).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, PhoneCall, PhoneOff, Send } from "lucide-react";
import {
  endParentVoiceCall,
  getParentVoiceStatus,
  pollParentVoiceSignal,
  postParentVoiceSignal,
  sendParentVoiceAnnouncement,
  startParentVoiceCall,
  type ParentVoiceCall,
} from "@/lib/parent/parent-api";

interface VoiceTabProps {
  studentId: string | null;
  studentName?: string;
}

type Phase = "idle" | "starting" | "live" | "ending" | "error";

const RTC_CONFIG: RTCConfiguration = {
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
};

export default function VoiceTab({ studentId, studentName }: VoiceTabProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [call, setCall] = useState<ParentVoiceCall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [announce, setAnnounce] = useState("");
  const [announceBusy, setAnnounceBusy] = useState(false);
  const [announceStatus, setAnnounceStatus] = useState<string | null>(null);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionRef = useRef<string>("current");

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const teardownPeer = useCallback(() => {
    stopPoll();
    try {
      pcRef.current?.close();
    } catch {
      /* ignore */
    }
    pcRef.current = null;
    try {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    } catch {
      /* ignore */
    }
    streamRef.current = null;
    if (audioRef.current) {
      try {
        audioRef.current.srcObject = null;
      } catch {
        /* ignore */
      }
    }
  }, [stopPoll]);

  const handleSignalPoll = useCallback(async () => {
    const sessionId = sessionRef.current;
    const { ok, data } = await pollParentVoiceSignal(sessionId);
    if (!ok || !data) return;
    if (data.call) setCall(data.call);
    if (data.call && !data.call.active) {
      teardownPeer();
      setPhase("idle");
      setError("Call ended.");
      return;
    }
    for (const s of data.signals ?? []) {
      try {
        if (s.type === "answer" && s.payload) {
          await pcRef.current?.setRemoteDescription({ type: "answer", sdp: s.payload });
        } else if (s.type === "ice" && s.payload) {
          const cand = JSON.parse(s.payload) as RTCIceCandidateInit;
          await pcRef.current?.addIceCandidate(new RTCIceCandidate(cand));
        } else if (s.type === "bye") {
          teardownPeer();
          setPhase("idle");
          setCall(null);
        }
      } catch {
        /* malformed signal — skip */
      }
    }
  }, [teardownPeer]);

  const startCall = useCallback(async () => {
    setError(null);
    setPhase("starting");
    try {
      const res = await startParentVoiceCall("current", studentId);
      if (!res.ok || !res.data?.call) {
        setPhase("error");
        setError(
          res.status === 404
            ? "No active study session — the student is not studying right now."
            : res.status === 429
              ? "Voice check-ins are cooling down. Try again in a minute."
              : res.status === 403
                ? "Voice check-ins are not permitted for this student."
                : `Could not start the call (${res.status}).`
        );
        return;
      }
      const activeCall = res.data.call;
      setCall(activeCall);
      sessionRef.current = activeCall.session_id ?? "current";

      const pc = new RTCPeerConnection(RTC_CONFIG);
      pcRef.current = pc;
      pc.ontrack = (ev) => {
        const stream = ev.streams?.[0];
        if (!stream) return;
        let el = audioRef.current;
        if (!el) {
          el = new Audio();
          el.autoplay = true;
          audioRef.current = el;
        }
        el.srcObject = stream;
        void el.play().catch(() => {});
      };
      pc.onicecandidate = (ev) => {
        if (ev.candidate) {
          void postParentVoiceSignal(
            sessionRef.current,
            "ice",
            JSON.stringify(ev.candidate.toJSON())
          );
        }
      };

      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      streamRef.current = mic;
      mic.getAudioTracks().forEach((t) => pc.addTrack(t, mic));

      const offer = await pc.createOffer({ offerToReceiveAudio: true });
      await pc.setLocalDescription(offer);
      const posted = await postParentVoiceSignal(sessionRef.current, "offer", offer.sdp ?? "");
      if (!posted.ok) {
        throw new Error("signaling failed");
      }
      setPhase("live");
      pollRef.current = setInterval(() => void handleSignalPoll(), 1000);
    } catch (err) {
      teardownPeer();
      setPhase("error");
      setError(
        err instanceof Error && /permission|denied|not allowed/i.test(err.message)
          ? "Mic blocked — allow microphone access to talk, or send a text announcement below."
          : "Could not open the mic or signaling channel. Send a text announcement below instead."
      );
    }
  }, [studentId, handleSignalPoll, teardownPeer]);

  const endCall = useCallback(async () => {
    setPhase("ending");
    try {
      await postParentVoiceSignal(sessionRef.current, "bye", "ended").catch(() => {});
      await endParentVoiceCall(sessionRef.current);
    } catch {
      /* best-effort */
    } finally {
      teardownPeer();
      setCall(null);
      setPhase("idle");
    }
  }, [teardownPeer]);

  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((t) => {
      t.enabled = !muted;
    });
  }, [muted]);

  useEffect(() => {
    return () => teardownPeer();
  }, [teardownPeer]);

  // Honest countdown from the backend expiry (auto-end guard).
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  useEffect(() => {
    if (phase !== "live" || !call?.ends_at) {
      setSecondsLeft(null);
      return;
    }
    const tick = () => {
      const left = Math.max(0, Math.round((call.ends_at ?? 0) - Date.now() / 1000));
      setSecondsLeft(left);
      if (left <= 0) void endCall();
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [phase, call?.ends_at, endCall]);

  const sendAnnouncement = async () => {
    const text = announce.trim();
    if (!text) return;
    setAnnounceBusy(true);
    setAnnounceStatus(null);
    try {
      const sessionId = call?.session_id ?? "current";
      const { ok, status, data } = await sendParentVoiceAnnouncement(sessionId, text.slice(0, 280), studentId);
      const detail =
        typeof (data as { detail?: unknown } | null)?.detail === "string"
          ? ((data as { detail: string }).detail ?? "")
          : "";
      if (ok) {
        setAnnounceStatus("Announcement sent — it will be read aloud in the study room.");
      } else if (status === 404) {
        setAnnounceStatus("No active study session to announce to.");
      } else if (status === 429) {
        const wait = /(\d+)s/.exec(detail)?.[1];
        setAnnounceStatus(
          wait
            ? `Sending too fast — wait ${wait}s and try again.`
            : "Sending too fast — wait a few seconds and try again."
        );
      } else if (status === 403) {
        setAnnounceStatus("Voice announcements are not permitted for this student.");
      } else {
        setAnnounceStatus(detail ? `Could not send: ${detail}` : "Could not send the announcement.");
      }
      if (ok) setAnnounce("");
    } catch {
      setAnnounceStatus("Network error sending the announcement.");
    } finally {
      setAnnounceBusy(false);
    }
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <section className="bento-cell space-y-4 p-5">
        <h4 className="font-semibold text-sm flex items-center gap-2 relative z-[2]">
          <PhoneCall size={16} className="text-[var(--primary)]" />
          <span>Voice Drop-in{studentName ? ` — ${studentName}` : ""}</span>
          {phase === "live" && (
            <span className="ml-auto text-[11px] font-mono font-bold text-[var(--primary)]">
              {secondsLeft !== null ? `${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, "0")} left` : "LIVE"}
            </span>
          )}
        </h4>
        <p className="text-xs text-[var(--muted-foreground)] relative z-[2]">
          Calls auto-answer in the study room — no accept button for the student. Every call is
          time-boxed (2 min), cooling-down protected, and audit-logged. The student always sees a
          banner and keeps volume + own-mic control.
        </p>
        {error && (
          <p className="text-xs font-semibold px-3 py-2 rounded-lg border text-red-300 bg-red-500/[0.08] border-red-500/30 relative z-[2]">
            {error}
          </p>
        )}
        <div className="flex flex-wrap gap-2 relative z-[2]">
          {phase === "live" ? (
            <>
              <button
                onClick={() => setMuted((m) => !m)}
                aria-pressed={muted}
                className="px-4 py-2 surface-glass-base !rounded-xl text-xs font-semibold glow-ring transition-colors flex items-center gap-1.5"
              >
                <Mic size={14} />
                {muted ? "Unmute me" : "Mute me"}
              </button>
              <button
                onClick={() => void endCall()}
                className="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/35 text-xs font-bold transition-colors flex items-center gap-1.5"
              >
                <PhoneOff size={14} />
                End call
              </button>
            </>
          ) : (
            <button
              onClick={() => void startCall()}
              disabled={phase === "starting" || phase === "ending"}
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] disabled:opacity-50 text-white text-xs font-bold transition-all shadow-[0_4px_16px_var(--glow-primary)] hover:brightness-110 active:scale-95 flex items-center gap-1.5"
            >
              {(phase === "starting" || phase === "ending") && <Loader2 size={13} className="animate-spin" />}
              {phase === "starting" ? "Calling…" : "Call student now"}
            </button>
          )}
          <button
            onClick={async () => {
              const { ok, data } = await getParentVoiceStatus("current", studentId);
              if (ok && data) setCall(data.call ?? null);
            }}
            className="px-4 py-2 surface-glass-base !rounded-xl text-xs font-semibold glow-ring transition-colors"
          >
            Refresh status
          </button>
        </div>
      </section>

      <section className="bento-cell space-y-3 p-5">
        <h4 className="font-semibold text-sm flex items-center gap-2 relative z-[2]">
          <Send size={16} className="text-[var(--amber)]" />
          <span>Text announcement fallback</span>
        </h4>
        <p className="text-xs text-[var(--muted-foreground)] relative z-[2]">
          Works even without mic permissions — the study room reads it aloud and shows it on screen.
        </p>
        <div className="flex gap-2 relative z-[2]">
          <input
            value={announce}
            maxLength={280}
            onChange={(e) => setAnnounce(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void sendAnnouncement()}
            placeholder="e.g. Dinner in 10 minutes — wrap up this section."
            className="glass-input w-full text-sm"
          />
          <button
            onClick={() => void sendAnnouncement()}
            disabled={announceBusy || !announce.trim()}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--amber)] to-[#E8C05F] disabled:opacity-50 text-black text-xs font-bold hover:brightness-110 active:scale-95 flex items-center gap-1.5 shrink-0"
          >
            {announceBusy && <Loader2 size={13} className="animate-spin" />}
            Send
          </button>
        </div>
        {announceStatus && (
          <p className="text-xs font-semibold relative z-[2] text-[var(--muted-foreground)]">{announceStatus}</p>
        )}
      </section>
    </div>
  );
}
