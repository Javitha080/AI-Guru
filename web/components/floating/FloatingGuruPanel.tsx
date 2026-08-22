"use client";

import React, {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowDownToLine,
  Minus,
  Monitor,
  Send,
  Sparkles,
  Square,
  Trash2,
  X,
} from "lucide-react";

import type {
  FloatingChatMessage,
  FloatingChatStoreLike,
} from "@/lib/floating/floatingChatStore";
import {
  FLOATING_EMPTY_SNAPSHOT,
  getFloatingChatStore,
} from "@/lib/floating/floatingChatStore";
import {
  FloatingChannel,
  FloatingMirrorStore,
} from "@/lib/floating/floatingSync";

export interface FloatingPanelPrefill {
  /** Page-selection context prepended to the next outgoing message. */
  contextPrefix: string;
  /** Bump to re-apply the prefill + focus the composer. */
  nonce: number;
}

export interface FloatingGuruPanelProps {
  /** Omit inside a detached PiP window — a channel-backed mirror is used. */
  store?: FloatingChatStoreLike;
  pipMode?: boolean;
  pipSupported?: boolean;
  prefill?: FloatingPanelPrefill | null;
  /** Collapse to bubble (main window). */
  onClose?: () => void;
  /** Hide the widget entirely (main window). */
  onHide?: () => void;
  onOpenPip?: () => void;
  /** Detached panel asks the owner window to close the PiP. */
  onPopBack?: () => void;
  /** Whole header acts as a drag handle in the main window. */
  onHeaderPointerDown?: (event: React.PointerEvent<HTMLDivElement>) => void;
  onHeaderDoubleClick?: () => void;
  className?: string;
}

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-2 whitespace-pre-wrap last:mb-0 leading-relaxed">{children}</p>
  ),
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-[var(--primary)] underline underline-offset-2"
    >
      {children}
    </a>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mb-2 list-disc space-y-1 pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-4 last:mb-0">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-2 text-sm font-bold last:mb-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-2 text-sm font-bold last:mb-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-1.5 text-xs font-semibold last:mb-0">{children}</h3>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="mb-2 border-l-2 border-[var(--border)] pl-2 text-[var(--muted-foreground)] last:mb-0">
      {children}
    </blockquote>
  ),
  code: ({
    className,
    children,
  }: {
    className?: string;
    children?: React.ReactNode;
  }) => {
    const isBlock = /language-/.test(className ?? "");
    if (isBlock) {
      return (
        <code className={`${className ?? ""} block font-mono text-[11px]`}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-[11px]">
        {children}
      </code>
    );
  },
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg border border-[var(--border)] bg-black/40 p-2 last:mb-0">
      {children}
    </pre>
  ),
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-[11px]">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="border border-[var(--border)] px-1.5 py-1 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="border border-[var(--border)] px-1.5 py-1">{children}</td>
  ),
};

const MarkdownBlock = memo(function MarkdownBlock({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {content}
    </ReactMarkdown>
  );
});

function StreamingCaret() {
  return (
    <span
      aria-hidden
      className="ml-0.5 inline-block h-3 w-[7px] translate-y-[2px] animate-pulse rounded-sm bg-[var(--primary)]"
    />
  );
}

function MessageBubble({ message }: { message: FloatingChatMessage }) {
  if (message.role === "system") {
    return (
      <div className="flex justify-center">
        <span className="rounded-full bg-[var(--secondary)] px-2 py-0.5 font-mono text-[10px] text-[var(--muted-foreground)]">
          {message.content}
        </span>
      </div>
    );
  }

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[var(--primary)] px-3 py-2 text-xs leading-relaxed text-white shadow-md shadow-[var(--glow-primary)]">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[88%] break-words rounded-2xl rounded-bl-md border px-3 py-2 text-xs text-[var(--foreground)] ${
          message.error
            ? "border-red-500/40 bg-red-500/10 text-red-300"
            : "border-[var(--border)] bg-[var(--card)]"
        }`}
      >
        <MarkdownBlock content={message.content || "…"} />
        {message.streaming ? <StreamingCaret /> : null}
      </div>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span title={label}>
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        onPointerDown={(event) => event.stopPropagation()}
        className={`rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-white/10 hover:text-[var(--foreground)] ${
          disabled ? "cursor-not-allowed opacity-40 hover:bg-transparent hover:text-[var(--muted-foreground)]" : ""
        }`}
      >
        {children}
      </button>
    </span>
  );
}

export default function FloatingGuruPanel({
  store,
  pipMode = false,
  pipSupported = true,
  prefill = null,
  onClose,
  onHide,
  onOpenPip,
  onPopBack,
  onHeaderPointerDown,
  onHeaderDoubleClick,
  className = "",
}: FloatingGuruPanelProps) {
  // Resolve the data source exactly once per mounted instance:
  // injected store > channel mirror (PiP) > process-wide singleton.
  const [activeStore] = useState<FloatingChatStoreLike>(() => {
    if (store) return store;
    if (pipMode) return new FloatingMirrorStore(new FloatingChannel());
    return getFloatingChatStore();
  });

  const snapshot = useSyncExternalStore(
    (listener) => activeStore.subscribe(listener),
    () => activeStore.getSnapshot(),
    () => FLOATING_EMPTY_SNAPSHOT,
  );

  const [input, setInput] = useState("");
  const [pendingContext, setPendingContext] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const appliedPrefillNonce = useRef<number>(0);

  const streaming = snapshot.status !== "idle";

  // Prefill + focus whenever the owner bumps the nonce.
  useEffect(() => {
    if (!prefill || prefill.nonce === appliedPrefillNonce.current) return;
    appliedPrefillNonce.current = prefill.nonce;
    const ctx = prefill.contextPrefix;
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.focus();
      const end = textarea.value.length;
      textarea.setSelectionRange(end, end);
    }
    if (!ctx) return;
    // Defer the state update so we never setState synchronously inside the effect.
    const id = window.setTimeout(() => setPendingContext(ctx), 0);
    return () => window.clearTimeout(id);
  }, [prefill]);

  // Autosize composer.
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
  }, [input]);

  // Stick to the bottom of the transcript.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }, [snapshot]);

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || snapshot.status !== "idle") return;
    activeStore.send(trimmed, pendingContext ?? undefined);
    setInput("");
    setPendingContext(null);
  }, [input, pendingContext, snapshot.status, activeStore]);

  const handleComposerKeyDown = (
    event: React.KeyboardEvent<HTMLTextAreaElement>,
  ) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      handleSend();
    }
  };

  const statusLabel =
    snapshot.status === "streaming"
      ? "Generating…"
      : snapshot.status === "connecting"
        ? "Connecting…"
        : "Ready";

  return (
    <div
      className={`flex flex-col overflow-hidden rounded-2xl border border-[var(--glass-border-highlight)] bg-[var(--glass-1)] text-[var(--foreground)] shadow-2xl shadow-black/50 backdrop-blur-xl ${className}`}
    >
      {/* Header */}
      <div
        onPointerDown={onHeaderPointerDown}
        onDoubleClick={onHeaderDoubleClick}
        className={`flex items-center gap-2 border-b border-[var(--border)] bg-[var(--glass-0)] px-3 py-2.5 ${
          onHeaderPointerDown ? "cursor-grab active:cursor-grabbing" : ""
        }`}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <div className="rounded-lg bg-[var(--accent)] p-1.5 text-[var(--primary)]">
            <Sparkles size={15} />
          </div>
          <div className="min-w-0">
            <p className="truncate text-xs font-bold">AI Guru</p>
            <p className="flex items-center gap-1.5 text-[10px] text-[var(--muted-foreground)]">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  streaming
                    ? "animate-pulse bg-[var(--primary)]"
                    : "bg-emerald-400"
                }`}
              />
              {statusLabel}
              {pipMode ? " · Pop-out" : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-0.5">
          {pipMode ? (
            <IconButton label="Pop back" onClick={onPopBack}>
              <ArrowDownToLine size={15} />
            </IconButton>
          ) : (
            <IconButton
              label={pipSupported ? "Detach into Picture-in-Picture" : "Needs Chrome/Edge"}
              onClick={pipSupported ? onOpenPip : undefined}
              disabled={!pipSupported}
            >
              <Monitor size={15} />
            </IconButton>
          )}
          {!pipMode && (
            <>
              <IconButton label="Minimize" onClick={onClose}>
                <Minus size={15} />
              </IconButton>
              <IconButton label="Hide Guru" onClick={onHide}>
                <X size={15} />
              </IconButton>
            </>
          )}
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 space-y-2.5 overflow-y-auto px-3 py-3"
      >
        {snapshot.messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3 text-[var(--primary)]">
              <Sparkles size={22} />
            </div>
            <p className="text-xs font-semibold">Your study copilot</p>
            <p className="max-w-[240px] text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              Ask questions, paste math, or select text anywhere on the page and
              pick it up right here.
            </p>
          </div>
        ) : (
          snapshot.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-[var(--border)] bg-[var(--glass-0)] p-2.5">
        {pendingContext ? (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1.5">
            <Sparkles size={12} className="shrink-0 text-[var(--primary)]" />
            <p className="min-w-0 flex-1 truncate text-[10px] text-[var(--muted-foreground)]">
              Context attached · selected text from page
            </p>
            <button
              type="button"
              aria-label="Remove attached context"
              onClick={() => setPendingContext(null)}
              className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <X size={12} />
            </button>
          </div>
        ) : null}
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            rows={1}
            placeholder={pendingContext ? "Ask about this…" : "Ask AI Guru…"}
            className="max-h-[140px] min-h-[36px] flex-1 resize-none rounded-xl border-0 bg-[var(--input)] px-3 py-2 text-xs text-[var(--foreground)] placeholder-[var(--muted-foreground)] outline-none focus:ring-1 focus:ring-[var(--ring)]"
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => activeStore.cancel()}
              className="flex shrink-0 items-center gap-1 rounded-xl bg-[var(--destructive)] px-2.5 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90"
            >
              <Square size={12} fill="currentColor" />
              Stop
            </button>
          ) : (
            <button
              type="button"
              aria-label="Send message"
              onClick={handleSend}
              disabled={!input.trim()}
              className="shrink-0 rounded-xl bg-[var(--primary)] p-2 text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Send size={14} />
            </button>
          )}
          <IconButton label="Clear chat" onClick={() => activeStore.reset()}>
            <Trash2 size={14} />
          </IconButton>
        </div>
        {!pipMode && (
          <p className="mt-1.5 text-center text-[9px] text-[var(--muted-foreground)]">
            Enter to send · Shift+Enter for newline · Alt+Space to toggle
          </p>
        )}
      </div>
    </div>
  );
}
