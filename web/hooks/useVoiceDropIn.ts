"use client";

/**
 * Student voice drop-in — auto-answer intercom + text announcements.
 *
 * Polls the local backend for an active parent call, auto-answers WebRTC
 * audio (no reject button by design), and speaks text announcements via
 * speechSynthesis. The call always shows a banner, auto-ends at the
 * backend duration cap, and the student keeps volume + own-mic mute.
 *
 * Audio unlock: browsers block autoplay without a prior gesture. The study
 * room creates/resumes an AudioContext on Pre-Flight continue, so by the
 * time this hook runs the page already has a gesture grant.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { monitoringApi } from "@/lib/monitoring/monitoringApi";
import { apiFetch } from "@/lib/api";

export interface VoiceCallState {
  call_id: string;
  session_id: string;
  active: boolean;
  seconds_left: number;
  mode: string;
}

interface IncomingResponse {
  call?: VoiceCallState | null;
  signals?: { type: string; payload: string; ts: number }[];
  announcements?: { text: string; ts: number }[];
}

const POLL_MS = 2000;
const RTC_CONFIG: RTCConfiguration = {
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
};

function speakText(text: string): void {
  try {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const utter = new SpeechSynthesisUtterance(text.slice(0, 280));
    utter.rate = 1;
    window.speechSynthesis.speak(utter);
  } catch {
    /* TTS is best-effort */
  }
}

export function useVoiceDropIn({
  sessionId,
  enabled,
  onNotice,
}: {
  sessionId: string | null;
  enabled: boolean;
  onNotice?: (notice: { kind: "error" | "warn"; text: string } | null) => void;
}) {
  const [call, setCall] = useState<VoiceCallState | null>(null);
  const [micMuted, setMicMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [announcement, setAnnouncement] = useState<string | null>(null);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const callIdRef = useRef<string | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const cleanupPeer = useCallback(() => {
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
    callIdRef.current = null;
  }, []);

  const postSignal = useCallback(
    async (type: string, payload: string) => {
      if (!sessionId) return;
      try {
        await apiFetch(monitoringApi.voiceSignal, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, type, payload }),
        });
      } catch {
        /* signaling retry happens on next poll */
      }
    },
    [sessionId]
  );

  const answerOffer = useCallback(
    async (offerSdp: string) => {
      if (!sessionId || !enabledRef.current) return;
      // One active peer per call — a re-offer replaces the old one.
      cleanupPeer();
      try {
        const pc = new RTCPeerConnection(RTC_CONFIG);
        pcRef.current = pc;

        pc.ontrack = (ev) => {
          const stream = ev.streams?.[0];
          if (!stream) return;
          let el = audioRef.current;
          if (!el) {
            el = document.createElement("audio");
            el.autoplay = true;
            // playsInline keeps iOS Safari from forcing fullscreen audio.
            (el as HTMLAudioElement & { playsInline?: boolean }).playsInline = true;
            audioRef.current = el;
            document.body.appendChild(el);
          }
          el.srcObject = stream;
          el.volume = 1;
          void el.play().catch(() => {
            onNotice?.({ kind: "warn", text: "Parent is calling — tap anywhere to hear the audio." });
          });
        };

        pc.onicecandidate = (ev) => {
          if (ev.candidate) {
            void postSignal("ice", JSON.stringify(ev.candidate.toJSON()));
          }
        };

        // Back-channel mic so the parent hears the student. Muted state
        // applies on next negotiation; live toggle flips the sender track.
        try {
          const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true },
            video: false,
          });
          streamRef.current = mic;
          mic.getAudioTracks().forEach((t) => {
            t.enabled = !micMuted;
            pc.addTrack(t, mic);
          });
        } catch {
          // Mic denied — still answer recvonly so parent voice is heard.
          onNotice?.({ kind: "warn", text: "Mic blocked — you can hear the parent but they can't hear you." });
        }

        await pc.setRemoteDescription({ type: "offer", sdp: offerSdp });
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        await postSignal("answer", answer.sdp ?? "");
        onNotice?.({ kind: "warn", text: "Parent voice check-in connected." });
      } catch {
        onNotice?.({ kind: "warn", text: "Could not connect parent voice — try the text announcement fallback." });
      }
    },
    [sessionId, cleanupPeer, postSignal, micMuted, onNotice]
  );

  // Live mic-mute toggle without renegotiation.
  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((t) => {
      t.enabled = !micMuted;
    });
  }, [micMuted]);

  // Live output volume.
  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = Math.min(1, Math.max(0, volume));
  }, [volume]);

  // Poll loop: incoming call + signals + announcements.
  useEffect(() => {
    if (!sessionId || !enabled) {
      setCall(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      try {
        const res = await apiFetch(monitoringApi.voiceIncoming(sessionId), { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as IncomingResponse;
        if (cancelled) return;

        for (const a of data.announcements ?? []) {
          if (a.text) {
            setAnnouncement(a.text);
            speakText(a.text);
            window.setTimeout(() => {
              if (!cancelled) setAnnouncement(null);
            }, 8000);
          }
        }

        const active = data.call && data.call.active ? data.call : null;
        setCall(active);
        if (!active) {
          if (callIdRef.current) cleanupPeer();
          return;
        }
        if (callIdRef.current !== active.call_id) {
          callIdRef.current = active.call_id;
        }
        for (const s of data.signals ?? []) {
          if (s.type === "offer" && s.payload) {
            void answerOffer(s.payload);
          } else if (s.type === "ice" && s.payload) {
            try {
              const cand = JSON.parse(s.payload) as RTCIceCandidateInit;
              await pcRef.current?.addIceCandidate(new RTCIceCandidate(cand));
            } catch {
              /* malformed candidate — skip */
            }
          } else if (s.type === "bye") {
            cleanupPeer();
            setCall(null);
          }
        }
      } catch {
        /* offline blip — next poll retries */
      }
    };

    void poll();
    timer = setInterval(() => void poll(), POLL_MS);
    const onWsVoice = (e: Event) => {
      void poll();
      void (e as CustomEvent).detail;
    };
    window.addEventListener("aiguru:voice-signal", onWsVoice as EventListener);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      window.removeEventListener("aiguru:voice-signal", onWsVoice as EventListener);
    };
  }, [sessionId, enabled, answerOffer, cleanupPeer]);

  // End of session / unmount: release mic + peer, remove audio element.
  useEffect(() => {
    if (!sessionId) {
      cleanupPeer();
      setCall(null);
    }
  }, [sessionId, cleanupPeer]);

  useEffect(() => {
    return () => {
      cleanupPeer();
      if (audioRef.current) {
        try {
          audioRef.current.srcObject = null;
          audioRef.current.remove();
        } catch {
          /* ignore */
        }
        audioRef.current = null;
      }
      try {
        if (typeof window !== "undefined" && "speechSynthesis" in window) {
          window.speechSynthesis.cancel();
        }
      } catch {
        /* ignore */
      }
    };
  }, [cleanupPeer]);

  return { call, micMuted, setMicMuted, volume, setVolume, announcement };
}
