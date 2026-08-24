"use client";

/**
 * AI Guru — floating, always-available chat bubble (Cluely-style).
 *
 * - Draggable bubble docked anywhere on screen (position persisted).
 * - Expandable chat panel backed by the unified WS agent loop.
 * - Alt+Space toggles the panel from anywhere in the app.
 * - Select text on any page → "Ask Guru about selection" chip.
 * - Detaches into an always-on-top Document Picture-in-Picture window
 *   (Chrome/Edge) that keeps streaming while the tab is backgrounded.
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createRoot, type Root } from "react-dom/client";
import { Sparkles, X, MonitorUp } from "lucide-react";
import FloatingGuruPanel, { type FloatingPanelPrefill } from "./FloatingGuruPanel";
import {
  FLOATING_EMPTY_SNAPSHOT,
  getFloatingChatStore,
  type FloatingChatStoreLike,
} from "@/lib/floating/floatingChatStore";
import { FloatingChannel, FloatingMirrorStore } from "@/lib/floating/floatingSync";

const POS_KEY = "aiguru.floating.pos";
const HIDDEN_KEY = "aiguru.floating.hidden";
const OPEN_EVENT = "aiguru:open-floating-chat";

type Point = { x: number; y: number };

function clampToViewport(p: Point): Point {
  const pad = 12;
  return {
    x: Math.min(Math.max(pad, p.x), window.innerWidth - pad - 56),
    y: Math.min(Math.max(pad, p.y), window.innerHeight - pad - 56),
  };
}

function readStoredPos(): Point | null {
  try {
    const raw = window.localStorage.getItem(POS_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Point;
    if (typeof p?.x === "number" && typeof p?.y === "number") return p;
  } catch {
    /* ignore */
  }
  return null;
}

/** Clone every stylesheet into the PiP document so Tailwind styles apply. */
function copyStylesInto(doc: Document): void {
  try {
    Array.from(document.styleSheets).forEach((sheet) => {
      try {
        const rules = sheet.cssRules;
        const style = doc.createElement("style");
        style.textContent = Array.from(rules)
          .map((r) => r.cssText)
          .join("\n");
        doc.head.appendChild(style);
      } catch {
        // Cross-origin sheet (<link> to another origin): clone the node itself.
        if (sheet.ownerNode instanceof HTMLLinkElement) {
          const link = doc.createElement("link");
          link.rel = sheet.ownerNode.rel;
          link.href = sheet.ownerNode.href;
          link.crossOrigin = "anonymous";
          doc.head.appendChild(link);
        }
      }
    });
    // Base target for relative asset URLs inside the PiP document.
    const base = doc.createElement("base");
    base.href = window.location.origin;
    doc.head.appendChild(base);
  } catch {
    /* best-effort styling */
  }
}

export default function FloatingGuru() {
  const store = useMemo<FloatingChatStoreLike>(() => getFloatingChatStore(), []);
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    () => FLOATING_EMPTY_SNAPSHOT,
  );

  const [hidden, setHidden] = useState(true); // start hidden until mounted check
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<Point>({ x: 24, y: 160 });
  const [prefill, setPrefill] = useState<FloatingPanelPrefill | null>(null);
  const [selText, setSelText] = useState("");
  const [pipSupported, setPipSupported] = useState(false);

  const pipWindowRef = useRef<Window | null>(null);
  const pipRootRef = useRef<Root | null>(null);
  const channelRef = useRef<FloatingChannel | null>(null);
  const dragState = useRef<{ pointerId: number; dx: number; dy: number } | null>(null);
  const bubbleRef = useRef<HTMLDivElement | null>(null);

  // ---- mount-time restore -------------------------------------------------
  useEffect(() => {
    setHidden(window.localStorage.getItem(HIDDEN_KEY) === "1");
    setPipSupported("documentPictureInPicture" in window);
    setPos(clampToViewport(readStoredPos() ?? { x: 24, y: Math.round(window.innerHeight / 2.6) }));
  }, []);

  // ---- channel: publish our state, obey mirror control messages ------------
  useEffect(() => {
    const channel = new FloatingChannel();
    channelRef.current = channel;
    channel.onMessage((msg) => {
      switch (msg.kind) {
        case "send":
          store.send(msg.text, msg.contextPrefix);
          setOpen(true);
          break;
        case "cancel":
          store.cancel();
          break;
        case "reset":
          store.reset();
          break;
        case "hello":
          channel.publishState(store.getSnapshot());
          break;
        case "popback":
          closePip();
          break;
      }
    });
    const unsub = store.subscribe(() => {
      channel.publishState(store.getSnapshot());
    });
    return () => {
      unsub();
      channel.close();
      channelRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store]);

  // ---- drag ----------------------------------------------------------------
  const onHeaderPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const rect = bubbleRef.current?.getBoundingClientRect();
      if (!rect) return;
      dragState.current = { pointerId: e.pointerId, dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    },
    []
  );

  useEffect(() => {
    const move = (e: PointerEvent) => {
      const st = dragState.current;
      if (!st || st.pointerId !== e.pointerId) return;
      setPos(clampToViewport({ x: e.clientX - st.dx - 28, y: e.clientY - st.dy - 28 }));
    };
    const up = () => {
      if (!dragState.current) return;
      dragState.current = null;
      try {
        window.localStorage.setItem(POS_KEY, JSON.stringify(pos));
      } catch {
        /* ignore */
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [pos]);

  // ---- global hotkey + external open event ---------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.code === "Space") {
        const t = e.target as HTMLElement | null;
        const editable =
          t &&
          (t.tagName === "INPUT" ||
            t.tagName === "TEXTAREA" ||
            t.isContentEditable ||
            t.closest?.("[contenteditable=true]"));
        if (editable) return;
        e.preventDefault();
        setOpen((v) => !v);
        setHidden(false);
      }
    };
    const onOpenEvent = (e: Event) => {
      setHidden(false);
      setOpen(true);
      const ctx = (e as CustomEvent<{ context?: string }>).detail?.context;
      if (ctx) {
        setPrefill({
          contextPrefix: `Context from page:\n"""\n${ctx}\n"""`,
          nonce: Date.now(),
        });
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpenEvent);
    };
  }, []);

  // ---- text-selection capture ----------------------------------------------
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onSelChange = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        if (pipWindowRef.current) return; // detached mode: skip
        const sel = window.getSelection()?.toString().trim() ?? "";
        setSelText(sel.length >= 3 ? sel.slice(0, 1200) : "");
      }, 400);
    };
    document.addEventListener("selectionchange", onSelChange);
    return () => {
      document.removeEventListener("selectionchange", onSelChange);
      if (timer) clearTimeout(timer);
    };
  }, []);

  // ---- PiP detach -----------------------------------------------------------
  const closePip = useCallback(() => {
    const w = pipWindowRef.current;
    if (w) {
      try {
        w.close();
      } catch {
        /* ignore */
      }
    }
    if (pipRootRef.current) {
      try {
        pipRootRef.current.unmount();
      } catch {
        /* ignore */
      }
    }
    pipWindowRef.current = null;
    pipRootRef.current = null;
  }, []);

  const openPip = useCallback(async () => {
    if (!("documentPictureInPicture" in window)) return;
    try {
      const existing = pipWindowRef.current;
      if (existing && !existing.closed) {
        existing.focus();
        return;
      }
      // @ts-expect-error — Document PiP API not yet in TS DOM lib
      const pip: Window = await window.documentPictureInPicture.requestWindow({
        width: 420,
        height: 620,
      });
      copyStylesInto(pip.document);
      pip.document.documentElement.className = document.documentElement.className;
      pip.document.body.className = `${document.body.className} pip-floating-body`;
      const host = pip.document.createElement("div");
      host.id = "floating-guru-pip-root";
      host.style.height = "100%";
      pip.document.body.appendChild(host);

      const mirrorChannel = new FloatingChannel();
      const mirror = new FloatingMirrorStore(mirrorChannel);
      const root = createRoot(host);
      root.render(
        <FloatingGuruPanel
          store={mirror}
          pipMode
          onPopBack={() => {
            closePip();
          }}
        />
      );
      pipWindowRef.current = pip;
      pipRootRef.current = root;
      pip.addEventListener("pagehide", () => closePip(), { once: true });
      setOpen(false); // main-window panel collapses while detached
    } catch (err) {
      console.warn("Floating Guru: failed to open PiP", err);
    }
  }, [closePip]);

  useEffect(() => () => closePip(), [closePip]);

  // ---- handlers -------------------------------------------------------------
  const toggleHidden = (next: boolean) => {
    setHidden(next);
    try {
      window.localStorage.setItem(HIDDEN_KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  const askAboutSelection = () => {
    if (!selText) return;
    setPrefill({
      contextPrefix: `Selected text from page:\n"""\n${selText}\n"""`,
      nonce: Date.now(),
    });
    setSelText("");
    setOpen(true);
  };

  const hasUnread = snapshot.status === "streaming" && !open;

  if (hidden) {
    return (
      <button
        aria-label="Open AI Guru chat"
        onClick={() => toggleHidden(false)}
        className="fixed bottom-5 right-5 z-[9999] flex h-12 w-12 items-center justify-center rounded-full border border-[var(--glass-border)] bg-gradient-to-br from-[#E06D44] to-[#B85A38] text-white shadow-xl transition hover:scale-105"
      >
        <Sparkles size={20} />
      </button>
    );
  }

  return (
    <>
      {/* Selection capture chip */}
      {selText && !open && !pipWindowRef.current && (
        <div className="fixed bottom-24 left-1/2 z-[9999] -translate-x-1/2">
          <button
            onClick={askAboutSelection}
            className="flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/95 px-4 py-2 text-xs font-medium text-slate-100 shadow-2xl backdrop-blur hover:bg-[var(--muted)]"
          >
            <Sparkles size={14} className="text-[var(--primary)]" />
            Ask Guru about “{selText.slice(0, 40)}
            {selText.length > 40 ? "…" : ""}”
            <X
              size={13}
              className="ml-1 opacity-60 hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                setSelText("");
              }}
            />
          </button>
        </div>
      )}

      {/* Bubble */}
      {!open && (
        <div
          ref={bubbleRef}
          className="fixed z-[9998]"
          style={{ left: pos.x, top: pos.y }}
        >
          <button
            aria-label="AI Guru floating chat"
            onDoubleClick={() => setOpen(true)}
            className={`relative flex h-14 w-14 items-center justify-center rounded-full border border-[var(--glass-border)] bg-gradient-to-br from-[#E06D44] to-[#B85A38] text-white shadow-2xl transition hover:scale-105 ${
              hasUnread ? "ring-4 ring-[var(--glow-primary)]" : ""
            }`}
            onClick={() => setOpen(true)}
          >
            <Sparkles size={22} />
            {hasUnread && (
              <span className="absolute -right-0.5 -top-0.5 h-3.5 w-3.5 animate-pulse rounded-full bg-emerald-400 ring-2 ring-slate-900" />
            )}
          </button>
          <button
            aria-label="Hide AI Guru"
            onClick={() => toggleHidden(true)}
            className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-slate-700 text-white opacity-70 shadow hover:opacity-100"
            style={{ pointerEvents: "auto" }}
          >
            <X size={11} />
          </button>
        </div>
      )}

      {/* Panel */}
      {open && (
        <div
          className="fixed bottom-5 right-5 z-[9999]"
          ref={bubbleRef}
        >
          <FloatingGuruPanel
            store={store}
            pipSupported={pipSupported}
            prefill={prefill}
            onClose={() => setOpen(false)}
            onHide={() => {
              setOpen(false);
              toggleHidden(true);
            }}
            onOpenPip={() => void openPip()}
            onHeaderPointerDown={onHeaderPointerDown}
            onHeaderDoubleClick={() => setOpen(false)}
          />
        </div>
      )}
    </>
  );
}
