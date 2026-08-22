"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  History,
  Plus,
  Search,
  Trash2,
  MessageSquare,
  ArrowRight,
  X,
  Clock,
  Sparkles,
  Loader2,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useOptionalUnifiedChat } from "@/context/UnifiedChatContext";
import {
  deleteSession,
  listSessions,
  type SessionSummary,
} from "@/lib/session-api";

interface HistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

function formatDateGroup(timestamp?: string | number): "today" | "yesterday" | "week" | "older" {
  if (!timestamp) return "older";
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0 && date.getDate() === now.getDate()) return "today";
  if (diffDays <= 1) return "yesterday";
  if (diffDays <= 7) return "week";
  return "older";
}

function formatTimeAgo(timestamp?: string | number): string {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function HistoryDrawer({ isOpen, onClose }: HistoryDrawerProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const chatCtx = useOptionalUnifiedChat();
  const newSession = chatCtx?.newSession;
  const cancelStreamingTurn = chatCtx?.cancelStreamingTurn;
  const selectedSessionId = chatCtx?.selectedSessionId;
  const sidebarRefreshToken = chatCtx?.sidebarRefreshToken;

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSessions(40, 0, { force: true });
      setSessions(data);
    } catch (err) {
      console.error("Failed to load sessions in HistoryDrawer:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      void fetchSessions();
    }
  }, [isOpen, fetchSessions, sidebarRefreshToken]);

  // Handle escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const handleNewChat = useCallback(() => {
    cancelStreamingTurn?.();
    newSession?.();
    onClose();
    router.push("/home");
  }, [cancelStreamingTurn, newSession, onClose, router]);

  const handleSelectSession = useCallback(
    (sessionId: string) => {
      onClose();
      router.push(`/home/${sessionId}`);
    },
    [onClose, router]
  );

  const handleDeleteSession = useCallback(
    async (e: React.MouseEvent, sessionId: string) => {
      e.stopPropagation();
      setDeletingId(sessionId);
      try {
        await deleteSession(sessionId);
        setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
        if (selectedSessionId === sessionId) {
          handleNewChat();
        }
      } catch (err) {
        console.error("Failed to delete session:", err);
      } finally {
        setDeletingId(null);
      }
    },
    [handleNewChat, selectedSessionId]
  );

  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => (s.title || s.session_id).toLowerCase().includes(q));
  }, [searchQuery, sessions]);

  const groupedSessions = useMemo(() => {
    const groups: {
      today: SessionSummary[];
      yesterday: SessionSummary[];
      week: SessionSummary[];
      older: SessionSummary[];
    } = { today: [], yesterday: [], week: [], older: [] };

    filteredSessions.forEach((s) => {
      const g = formatDateGroup(s.updated_at || s.created_at);
      groups[g].push(s);
    });

    return groups;
  }, [filteredSessions]);

  const groupLabels: Record<string, string> = {
    today: t("Today"),
    yesterday: t("Yesterday"),
    week: t("Previous 7 Days"),
    older: t("Older"),
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        onClick={onClose}
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
        aria-hidden
      />

      {/* Floating Glass Drawer */}
      <motion.div
        initial={{ opacity: 0, y: 30, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 20, scale: 0.96 }}
        transition={{ type: "spring", stiffness: 450, damping: 32 }}
        className="fixed bottom-20 md:bottom-24 left-1/2 -translate-x-1/2 z-50 w-[94vw] max-w-lg max-h-[72vh] flex flex-col rounded-3xl overflow-hidden shadow-2xl"
        style={{
          background: "rgba(10, 14, 20, 0.88)",
          backdropFilter: "blur(32px)",
          WebkitBackdropFilter: "blur(32px)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderTopColor: "rgba(255, 255, 255, 0.24)",
          boxShadow: "0 24px 60px rgba(0, 0, 0, 0.75), 0 0 30px var(--glow-primary), inset 0 1px 0 rgba(255, 255, 255, 0.20)",
        }}
      >
        {/* Header Bar */}
        <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-[var(--glass-border)]">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--primary)]/15 text-[var(--primary)]">
              <History size={16} strokeWidth={2} />
            </div>
            <div>
              <h2 className="font-display font-semibold text-sm text-[var(--foreground)] flex items-center gap-2">
                {t("Chat History")}
                <span className="text-[11px] font-mono font-medium px-2 py-0.5 rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">
                  {sessions.length}
                </span>
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleNewChat}
              className="inline-flex items-center gap-1.5 glass-btn-primary px-3 py-1.5 text-xs font-semibold"
            >
              <Plus size={13} strokeWidth={2.2} />
              <span>{t("New Chat")}</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-full text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)] transition-colors"
              aria-label={t("Close")}
            >
              <X size={15} />
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="px-4 py-2.5 border-b border-[var(--glass-border)]/60 bg-[var(--glass-0)]/30">
          <div className="relative flex items-center">
            <Search size={14} className="absolute left-3 text-[var(--muted-foreground)] pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("Search conversations...")}
              className="w-full pl-9 pr-8 py-1.5 rounded-xl bg-[var(--input)]/40 border border-[var(--border)] text-xs text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/60 outline-none focus:border-[var(--primary)]/60 transition-colors"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                <X size={12} />
              </button>
            )}
          </div>
        </div>

        {/* Sessions Scroll List */}
        <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-4 [scrollbar-gutter:stable]">
          {loading && sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-[var(--muted-foreground)] gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--primary)]" />
              <span className="text-xs">{t("Loading chats...")}</span>
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--muted)]/40 text-[var(--muted-foreground)] mb-3">
                <MessageSquare size={20} strokeWidth={1.5} />
              </div>
              <p className="text-sm font-medium text-[var(--foreground)]">
                {searchQuery ? t("No conversations found") : t("No chat history yet")}
              </p>
              <p className="mt-1 text-xs text-[var(--muted-foreground)] max-w-xs">
                {searchQuery
                  ? t("Try a different search keyword.")
                  : t("Start your first discussion with AI Guru!")}
              </p>
              {!searchQuery && (
                <button
                  type="button"
                  onClick={handleNewChat}
                  className="mt-4 glass-btn-primary px-4 py-2 text-xs font-semibold"
                >
                  {t("Start a Conversation")}
                </button>
              )}
            </div>
          ) : (
            Object.entries(groupedSessions).map(([groupKey, groupItems]) => {
              if (groupItems.length === 0) return null;
              return (
                <div key={groupKey} className="space-y-1.5">
                  <div className="px-2 text-[10.5px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]/70">
                    {groupLabels[groupKey]}
                  </div>
                  <div className="space-y-1">
                    {groupItems.map((session) => {
                      const isActive = pathname === `/home/${session.session_id}`;
                      const isDeleting = deletingId === session.session_id;

                      return (
                        <div
                          key={session.session_id}
                          onClick={() => handleSelectSession(session.session_id)}
                          className={`group relative flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-2xl cursor-pointer transition-all duration-200 ${
                            isActive
                              ? "bg-[color-mix(in_srgb,var(--primary)_16%,var(--glass-1))] border border-[var(--primary)]/40 shadow-sm"
                              : "hover:bg-[var(--glass-1)] hover:border-[var(--glass-border-highlight)] border border-transparent"
                          }`}
                        >
                          <div className="flex items-center gap-3 min-w-0 flex-1">
                            <MessageSquare
                              size={15}
                              strokeWidth={1.8}
                              className={`shrink-0 ${
                                isActive
                                  ? "text-[var(--primary)]"
                                  : "text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]"
                              }`}
                            />
                            <div className="min-w-0 flex-1">
                              <h4
                                className={`text-xs font-medium truncate ${
                                  isActive
                                    ? "text-[var(--foreground)] font-semibold"
                                    : "text-[var(--foreground)]/85 group-hover:text-[var(--foreground)]"
                                }`}
                              >
                                {session.title || t("Untitled Chat")}
                              </h4>
                              <div className="flex items-center gap-2 mt-0.5 text-[10.5px] text-[var(--muted-foreground)]">
                                {session.updated_at && (
                                  <span className="flex items-center gap-1">
                                    <Clock size={10} />
                                    {formatTimeAgo(session.updated_at)}
                                  </span>
                                )}
                                {session.message_count !== undefined && session.message_count > 0 && (
                                  <span>· {session.message_count} msgs</span>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Delete Action Button on Hover */}
                          <div className="flex items-center opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              type="button"
                              onClick={(e) => handleDeleteSession(e, session.session_id)}
                              disabled={isDeleting}
                              title={t("Delete chat")}
                              className="p-1.5 rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--destructive)]/15 hover:text-[var(--destructive)] transition-colors"
                            >
                              {isDeleting ? (
                                <Loader2 size={13} className="animate-spin" />
                              ) : (
                                <Trash2 size={13} />
                              )}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer Link to Full Learning Space History */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-[var(--glass-border)] bg-[var(--glass-0)]/40 text-xs">
          <span className="text-[var(--muted-foreground)] text-[11.5px]">
            {t("View full archives")}
          </span>
          <button
            type="button"
            onClick={() => {
              onClose();
              router.push("/space/chat-history");
            }}
            className="inline-flex items-center gap-1.5 font-semibold text-[var(--primary)] hover:underline"
          >
            <span>{t("All in Space")}</span>
            <ArrowRight size={13} />
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
