"use client";

/**
 * AI Guru — global command palette (⌘K / Ctrl+K).
 *
 * Mounted once at the app root. Opens on the keyboard shortcut or via the
 * `aiguru:open-command-palette` CustomEvent (dispatched by the HeaderBar
 * search capsule). Lists primary navigation, recent chat sessions, and a few
 * global actions; everything filters from one query.
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
import { Search, Moon, Sun, Sparkles, History, CornerDownLeft } from "lucide-react";
import PickerShell from "@/components/common/PickerShell";
import { apiFetch } from "@/lib/api";
import { DOCK_NAV } from "@/lib/navigation";
import { useAppShell } from "@/context/AppShellContext";

interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
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

  const items = useMemo<PaletteItem[]>(() => {
    const nav: PaletteItem[] = DOCK_NAV.map((entry) => ({
      id: `nav:${entry.href}`,
      label: t(entry.label),
      hint: entry.href,
      icon: entry.icon,
      section: "navigate",
      run: () => router.push(entry.href),
    }));

    const recent: PaletteItem[] = (sessions ?? []).map((s) => ({
      id: `session:${s.session_id}`,
      label: s.title || t("Untitled session"),
      hint: "/home",
      icon: History,
      section: "recent",
      run: () => router.push(`/home/${s.session_id}`),
    }));

    const isDark = theme !== "light" && theme !== "snow";
    const actions: PaletteItem[] = [
      {
        id: "action:theme",
        label: isDark ? t("Switch to light theme") : t("Switch to dark theme"),
        icon: isDark ? Sun : Moon,
        section: "actions",
        run: () => setTheme(isDark ? "light" : "dark"),
      },
      {
        id: "action:guru",
        label: t("Ask AI Guru"),
        hint: "Alt+Space",
        icon: Sparkles,
        section: "actions",
        run: () =>
          window.dispatchEvent(new CustomEvent("aiguru:open-floating-chat")),
      },
    ];

    return [...nav, ...recent, ...actions];
  }, [router, sessions, setTheme, t, theme]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        (item.hint ?? "").toLowerCase().includes(q),
    );
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
    { key: "navigate", title: t("Navigate") },
    { key: "recent", title: t("Recent sessions") },
    { key: "actions", title: t("Actions") },
  ];

  return (
    <PickerShell open={open} onClose={close} ariaLabel={t("Command palette")} align="start" className="pt-[12vh]">
      <div
        className="surface-glass-elevated liquid-sheen relative w-[min(560px,92vw)] overflow-hidden rounded-2xl"
        onKeyDown={onKeyDown}
      >
        {/* Search row */}
        <div className="relative z-10 flex items-center gap-2.5 border-b border-[var(--glass-border)] px-4 py-3">
          <Search size={16} strokeWidth={1.6} className="shrink-0 text-[var(--muted-foreground)]" />
          <input
            ref={inputRef}
            data-autofocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Search pages, sessions, actions…")}
            aria-label={t("Command palette")}
            className="w-full bg-transparent text-sm text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
          />
          <kbd className="ml-auto shrink-0 rounded border border-[var(--glass-border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted-foreground)]">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="relative z-10 max-h-[52vh] overflow-y-auto p-2" role="listbox">
          {filtered.length === 0 && (
            <p className="px-3 py-8 text-center text-sm text-[var(--muted-foreground)]">
              {t("No matches.")}
            </p>
          )}
          {sections.map(({ key, title }) => {
            const sectionItems = filtered.filter((i) => i.section === key);
            if (sectionItems.length === 0) return null;
            const showHeader = key !== "navigate" || query.trim().length > 0;
            return (
              <div key={key} className="mb-1 last:mb-0">
                {showHeader && (
                  <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
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
                      className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors ${
                        active
                          ? "bg-[var(--accent)] text-[var(--foreground)]"
                          : "text-[var(--foreground)]/85 hover:bg-[var(--muted)]"
                      }`}
                    >
                      <span
                        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
                          active
                            ? "bg-[color-mix(in_srgb,var(--primary)_22%,transparent)] text-[var(--primary)]"
                            : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                        }`}
                      >
                        <item.icon size={15} />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                        {item.label}
                      </span>
                      {item.hint && (
                        <span className="shrink-0 font-mono text-[10px] text-[var(--muted-foreground)]">
                          {item.hint}
                        </span>
                      )}
                      {active && (
                        <CornerDownLeft size={13} className="shrink-0 text-[var(--muted-foreground)]" />
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </PickerShell>
  );
}
