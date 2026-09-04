"use client";

/**
 * AI Guru — global command palette (⌘K / Ctrl+K).
 *
 * Mounted once at the app root. Opens on the keyboard shortcut or via the
 * `aiguru:open-command-palette` CustomEvent (dispatched by HeaderBar).
 * Lists navigation, recent chat sessions, and global actions with fast filtering.
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Search,
  Moon,
  Sun,
  Sparkles,
  History,
  CornerDownLeft,
  GraduationCap,
  FileText,
  BookOpenCheck,
  User,
  MessageSquarePlus,
  X,
} from "lucide-react";
import PickerShell from "@/components/common/PickerShell";
import { apiFetch } from "@/lib/api";
import { DOCK_NAV } from "@/lib/navigation";
import { useAppShell } from "@/context/AppShellContext";

interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  keywords?: string[];
  icon: React.ComponentType<{ size?: number | string; className?: string }>;
  section: "navigate" | "recent" | "actions";
  run: () => void;
}

interface SessionSummary {
  session_id: string;
  title: string;
}

export const OPEN_COMMAND_PALETTE_EVENT = "aiguru:open-command-palette";

export function openCommandPalette(): void {
  window.dispatchEvent(new CustomEvent(OPEN_COMMAND_PALETTE_EVENT));
}

export default function CommandPalette() {
  const router = useRouter();
  const { t } = useTranslation();
  const { theme, setTheme } = useAppShell();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Global hotkey + external open event.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, onOpen);
    };
  }, []);

  // Fetch recent sessions lazily, only while open, once per opening.
  useEffect(() => {
    if (!open || sessions !== null) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await apiFetch("/api/v1/chat/sessions?limit=6", {
          skipAuthRedirect: true,
        });
        if (!res.ok) return;
        const data = (await res.json()) as unknown;
        const list = Array.isArray(data) ? data : [];
        if (!cancelled) setSessions(list as SessionSummary[]);
      } catch {
        /* offline — recents simply stay hidden */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, sessions]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActiveIdx(0);
  }, []);

  const handleQueryChange = (val: string) => {
    setQuery(val);
    setActiveIdx(0);
  };

  const clearQuery = () => {
    setQuery("");
    setActiveIdx(0);
    inputRef.current?.focus();
  };

  const items = useMemo<PaletteItem[]>(() => {
    // Primary navigation from DOCK_NAV
    const nav: PaletteItem[] = DOCK_NAV.map((entry) => {
      let category = t("Page");
      if (["/co-writer", "/book", "/agents"].includes(entry.href)) {
        category = t("Tool");
      } else if (["/parent", "/settings"].includes(entry.href)) {
        category = t("System");
      }
      return {
        id: `nav:${entry.href}`,
        label: t(entry.label),
        hint: category,
        keywords: [entry.href, entry.label.toLowerCase()],
        icon: entry.icon,
        section: "navigate",
        run: () => router.push(entry.href),
      };
    });

    // Additional standalone destinations not in the compact dock
    const extraPages: PaletteItem[] = [
      {
        id: "nav:/exam",
        label: t("Exam Room"),
        hint: t("Workspace"),
        keywords: ["exam", "test", "quiz", "paper", "assessment"],
        icon: GraduationCap,
        section: "navigate",
        run: () => router.push("/exam"),
      },
      {
        id: "nav:/papers",
        label: t("Past Papers"),
        hint: t("Workspace"),
        keywords: ["papers", "past papers", "exam", "test", "questions"],
        icon: FileText,
        section: "navigate",
        run: () => router.push("/papers"),
      },
      {
        id: "nav:/notebook",
        label: t("Notebook"),
        hint: t("Tool"),
        keywords: ["notebook", "notes", "summary", "records"],
        icon: BookOpenCheck,
        section: "navigate",
        run: () => router.push("/notebook"),
      },
      {
        id: "nav:/profile",
        label: t("User Profile"),
        hint: t("System"),
        keywords: ["profile", "account", "user", "stats"],
        icon: User,
        section: "navigate",
        run: () => router.push("/profile"),
      },
    ];

    // Recent chat sessions
    const recent: PaletteItem[] = (sessions ?? []).map((s) => ({
      id: `session:${s.session_id}`,
      label: s.title || t("Untitled session"),
      hint: t("Recent chat"),
      keywords: ["chat", "session", "history", s.title.toLowerCase()],
      icon: History,
      section: "recent",
      run: () => router.push(`/home/${s.session_id}`),
    }));

    // Quick Actions
    const isDark = theme !== "light" && theme !== "snow";
    const actions: PaletteItem[] = [
      {
        id: "action:new-chat",
        label: t("Start new chat"),
        hint: t("Chat"),
        keywords: ["new", "chat", "message", "conversation", "ask"],
        icon: MessageSquarePlus,
        section: "actions",
        run: () => {
          router.push("/home");
          window.dispatchEvent(new CustomEvent("aiguru:new-chat"));
        },
      },
      {
        id: "action:guru",
        label: t("Ask AI Guru"),
        hint: "Alt+Space",
        keywords: ["ai", "guru", "floating", "ask", "help", "assistant"],
        icon: Sparkles,
        section: "actions",
        run: () =>
          window.dispatchEvent(new CustomEvent("aiguru:open-floating-chat")),
      },
      {
        id: "action:theme",
        label: isDark ? t("Switch to light theme") : t("Switch to dark theme"),
        hint: t("Theme"),
        keywords: ["theme", "dark", "light", "mode", "color", "appearance"],
        icon: isDark ? Sun : Moon,
        section: "actions",
        run: () => setTheme(isDark ? "light" : "dark"),
      },
    ];

    return [...nav, ...extraPages, ...recent, ...actions];
  }, [router, sessions, setTheme, t, theme]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => {
      const matchLabel = item.label.toLowerCase().includes(q);
      const matchHint = (item.hint ?? "").toLowerCase().includes(q);
      const matchKeywords = item.keywords?.some((k) => k.includes(q)) ?? false;
      return matchLabel || matchHint || matchKeywords;
    });
  }, [items, query]);

  // Keep selection inside bounds as the filter narrows.
  const safeActiveIdx = activeIdx >= filtered.length ? 0 : activeIdx;

  const runItem = useCallback(
    (item: PaletteItem) => {
      close();
      item.run();
    },
    [close],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => Math.min(filtered.length - 1, i + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => Math.max(0, i - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = filtered[safeActiveIdx];
        if (item) runItem(item);
      }
    },
    [filtered, safeActiveIdx, runItem],
  );

  // Scroll the active row into view while arrowing through the list.
  useEffect(() => {
    const list = listRef.current;
    const el = list?.querySelector<HTMLElement>('[data-active="true"]');
    el?.scrollIntoView({ block: "nearest" });
  }, [safeActiveIdx]);

  let renderIdx = -1;
  const sections: Array<{ key: PaletteItem["section"]; title: string }> = [
    { key: "navigate", title: t("Navigation") },
    { key: "recent", title: t("Recent sessions") },
    { key: "actions", title: t("Quick actions") },
  ];

  return (
    <PickerShell
      open={open}
      onClose={close}
      ariaLabel={t("Command palette")}
      align="start"
      className="pt-[10vh] md:pt-[12vh] px-3"
      backdropClass="bg-black/60 backdrop-blur-md"
    >
      <div
        className="liquid-glass liquid-glass--strong liquid-glass--refract relative w-[min(640px,94vw)] overflow-hidden rounded-3xl shadow-[0_30px_70px_-15px_rgba(0,0,0,0.75)]"
        onKeyDown={onKeyDown}
      >
        {/* Specular Top Key-light Line */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-white/35 to-transparent z-20"
          aria-hidden="true"
        />

        {/* Search header row */}
        <div className="relative z-10 flex items-center gap-3.5 border-b border-[var(--glass-border)] px-5 py-4">
          <Search size={19} strokeWidth={2} className="shrink-0 text-[var(--primary)]" />
          <input
            ref={inputRef}
            data-autofocus
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder={t("Search pages, sessions, actions…")}
            aria-label={t("Command palette")}
            className="w-full bg-transparent text-[15px] font-medium text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/65 placeholder:font-normal"
          />
          {query.trim().length > 0 && (
            <button
              type="button"
              onClick={clearQuery}
              aria-label={t("Clear search")}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
            >
              <X size={13} />
            </button>
          )}
          <kbd className="ml-auto shrink-0 rounded-lg border border-[var(--glass-border)] bg-[var(--muted)]/60 px-2 py-0.5 font-mono text-[10px] font-bold text-[var(--muted-foreground)] shadow-sm">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div
          ref={listRef}
          className="relative z-10 max-h-[52vh] overflow-y-auto p-2.5 scrollbar-thin space-y-1"
          role="listbox"
        >
          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <Search size={26} className="text-[var(--muted-foreground)]/40 mb-2.5" />
              <p className="text-sm font-semibold text-[var(--foreground)]">
                {t("No matches found")}
              </p>
              <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                {t("Try searching for pages, actions, or recent chats")}
              </p>
            </div>
          )}
          {sections.map(({ key, title }) => {
            const sectionItems = filtered.filter((i) => i.section === key);
            if (sectionItems.length === 0) return null;
            const showHeader = key !== "navigate" || query.trim().length > 0;
            return (
              <div key={key} className="mb-2 last:mb-0">
                {showHeader && (
                  <p className="px-3 pb-1 pt-1.5 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]/80">
                    {title}
                  </p>
                )}
                {sectionItems.map((item) => {
                  renderIdx += 1;
                  const active = renderIdx === safeActiveIdx;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      data-active={active}
                      onMouseEnter={() => setActiveIdx(filtered.indexOf(item))}
                      onClick={() => runItem(item)}
                      className={`group flex w-full items-center gap-3.5 rounded-2xl px-3.5 py-2.5 text-left transition-all duration-[var(--duration-fast,200ms)] ease-[var(--ease-smooth-out,ease-out)] ${
                        active
                          ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm scale-[1.01]"
                          : "text-[var(--foreground)]/85 hover:bg-white/5"
                      }`}
                    >
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl transition-all duration-200 ${
                          active
                            ? "bg-[var(--primary)] text-white shadow-[0_2px_12px_var(--glow-primary)] scale-105"
                            : "bg-[var(--secondary)] text-[var(--muted-foreground)] group-hover:text-[var(--foreground)] group-hover:bg-white/10"
                        }`}
                      >
                        <item.icon size={16} />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[13px] font-semibold leading-snug">
                        {item.label}
                      </span>
                      {item.hint && (
                        <span
                          className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-bold ${
                            active
                              ? "bg-black/30 text-[var(--foreground)] border border-white/10"
                              : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                          }`}
                        >
                          {item.hint}
                        </span>
                      )}
                      <span
                        className={`shrink-0 ml-1 text-xs opacity-0 transition-all duration-150 ${
                          active ? "opacity-100 text-[var(--primary)] translate-x-0" : "-translate-x-1"
                        }`}
                      >
                        <CornerDownLeft size={14} />
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* Footer shortcuts helper */}
        <div className="relative z-10 flex items-center justify-between border-t border-[var(--glass-border)] bg-black/20 px-5 py-2.5 text-[11px] text-[var(--muted-foreground)]">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <kbd className="rounded-md border border-[var(--glass-border)] bg-[var(--muted)] px-1.5 font-mono text-[9px] font-bold">↑</kbd>
              <kbd className="rounded-md border border-[var(--glass-border)] bg-[var(--muted)] px-1.5 font-mono text-[9px] font-bold">↓</kbd>
              <span>{t("Navigate")}</span>
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded-md border border-[var(--glass-border)] bg-[var(--muted)] px-1.5 font-mono text-[9px] font-bold">↵</kbd>
              <span>{t("Select")}</span>
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded-md border border-[var(--glass-border)] bg-[var(--muted)] px-1.5 font-mono text-[9px] font-bold">ESC</kbd>
              <span>{t("Close")}</span>
            </span>
          </div>
          <span className="font-display font-semibold text-[10px] tracking-wide text-[var(--muted-foreground)]/70 hidden sm:inline">
            AI GURU
          </span>
        </div>
      </div>
    </PickerShell>
  );
}
