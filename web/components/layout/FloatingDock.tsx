"use client";

import { useRef, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  LayoutGrid,
  Lock,
  History,
  X,
} from "lucide-react";
import { Tooltip } from "@/components/ui/Tooltip";
import { useCapabilityAccess } from "@/components/access/CapabilityAccessContext";
import { DOCK_NAV, MOBILE_PRIMARY_COUNT, type NavEntry } from "@/lib/navigation";

interface FloatingDockProps {
  onNewChat?: () => void;
  onShowHistory?: () => void;
}

export default function FloatingDock({ onNewChat, onShowHistory }: FloatingDockProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const { has } = useCapabilityAccess();
  const dockRef = useRef<HTMLDivElement>(null);
  const [activeRect, setActiveRect] = useState<{ left: number; width: number } | null>(null);
  // Mobile "More" sheet — exposes the destinations that don't fit in the
  // 5-slot tab bar instead of silently dumping users onto /space.
  const [moreOpen, setMoreOpen] = useState(false);

  const navLocked = (item: NavEntry) => item.requires ? !has(item.requires) : false;

  // Measure the active item position for the sliding indicator
  useEffect(() => {
    if (!dockRef.current) return;
    const activeEl = dockRef.current.querySelector('[data-active="true"]') as HTMLElement | null;
    if (activeEl) {
      const dockRect = dockRef.current.getBoundingClientRect();
      const itemRect = activeEl.getBoundingClientRect();
      setActiveRect({
        left: itemRect.left - dockRect.left,
        width: itemRect.width,
      });
    } else {
      setActiveRect(null);
    }
  }, [pathname]);

  const handleHomeClick = (event: React.MouseEvent) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    onNewChat?.();
    router.push("/home");
  };

  // Close the mobile More sheet on route change.
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (prevPathname !== pathname) {
    setPrevPathname(pathname);
    setMoreOpen(false);
  }

  useEffect(() => {
    if (!moreOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMoreOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [moreOpen]);

  return (
    <>
      {/* Desktop: Floating bottom dock */}
      <nav
        ref={dockRef}
        className="surface-glass-dock hidden md:flex fixed bottom-5 left-1/2 -translate-x-1/2 z-40 items-center gap-1 px-2.5 py-1.5 rounded-full"
      >
        {/* Sliding active indicator */}
        {activeRect && (
          <motion.div
            className="absolute rounded-full"
            style={{
              background: "color-mix(in srgb, var(--primary) 22%, transparent)",
              border: "1px solid color-mix(in srgb, var(--primary) 40%, transparent)",
              boxShadow: "0 0 16px var(--glow-primary)",
              height: 36,
              top: 6,
            }}
            animate={{ left: activeRect.left, width: activeRect.width }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
          />
        )}

        {/* History trigger */}
        {onShowHistory && (
          <Tooltip label={t("Recents")} side="top">
            <button
              type="button"
              onClick={onShowHistory}
              className="relative flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition-all hover:text-[var(--foreground)] hover:scale-110 active:scale-95 duration-200"
            >
              <History size={17} strokeWidth={1.6} />
            </button>
          </Tooltip>
        )}

        {onShowHistory && <div className="w-px h-5 bg-[var(--glass-border)] mx-1" />}

        {DOCK_NAV.map((item) => {
          const active = pathname.startsWith(item.href);
          const locked = navLocked(item);

          if (locked) {
            return (
              <Tooltip key={item.href} label={t(item.label)} description={t("Locked — contact your administrator to get access.")} side="top">
                <div
                  aria-disabled
                  className="relative flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)]/40 cursor-not-allowed"
                >
                  <item.icon size={17} strokeWidth={1.6} />
                  <Lock size={8} strokeWidth={2} className="absolute bottom-0.5 right-0.5 text-[var(--muted-foreground)]/70" />
                </div>
              </Tooltip>
            );
          }

          return (
            <Tooltip key={item.href} label={t(item.label)} description={item.tooltipKey ? t(item.tooltipKey) : undefined} side="top">
              <Link
                href={item.href}
                onClick={item.href === "/home" ? handleHomeClick : undefined}
                data-active={active}
                className={`relative flex h-9 w-9 items-center justify-center rounded-full transition-all duration-200 z-10 hover:scale-110 active:scale-95 ${
                  active
                    ? "text-[var(--primary)]"
                    : "text-[var(--foreground)]/70 hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={17} strokeWidth={active ? 2 : 1.6} />
              </Link>
            </Tooltip>
          );
        })}
      </nav>

      {/* Mobile: Fixed bottom tab bar */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 surface-glass-elevated" style={{ borderRadius: '1rem 1rem 0 0' }}>
        {/* More sheet — remaining destinations above the tab bar */}
        <AnimatePresence>
          {moreOpen && (
            <>
              <motion.div
                key="more-scrim"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                onClick={() => setMoreOpen(false)}
                aria-hidden
                className="fixed inset-0 -z-10 bg-[var(--overlay)]"
              />
              <motion.div
                key="more-sheet"
                role="menu"
                aria-label={t("More")}
                initial={{ opacity: 0, y: 14, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.98 }}
                transition={{ type: "spring", stiffness: 420, damping: 32 }}
                className="surface-glass-elevated absolute bottom-full left-2 right-2 mb-2 overflow-hidden rounded-2xl p-2"
              >
                <div className="flex items-center justify-between px-2 pb-1.5 pt-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                    {t("More")}
                  </span>
                  <button
                    type="button"
                    onClick={() => setMoreOpen(false)}
                    aria-label={t("Close")}
                    className="rounded-full p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                  >
                    <X size={14} />
                  </button>
                </div>
                <div className="grid grid-cols-3 gap-1">
                  {DOCK_NAV.slice(MOBILE_PRIMARY_COUNT).map((item) => {
                    const active = pathname.startsWith(item.href);
                    const locked = navLocked(item);
                    const content = (
                      <>
                        <item.icon size={18} strokeWidth={active ? 2 : 1.5} />
                        <span className="text-[9px] font-body leading-none">{t(item.label)}</span>
                      </>
                    );
                    if (locked) {
                      return (
                        <div
                          key={item.href}
                          aria-disabled
                          className="flex flex-col items-center gap-1 rounded-xl px-1 py-2.5 text-[var(--muted-foreground)]/30"
                        >
                          {content}
                        </div>
                      );
                    }
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        role="menuitem"
                        onClick={() => setMoreOpen(false)}
                        className={`flex flex-col items-center gap-1 rounded-xl px-1 py-2.5 transition-colors ${
                          active
                            ? "bg-[var(--accent)] text-[var(--primary)]"
                            : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        {content}
                      </Link>
                    );
                  })}
                </div>
              </motion.div>
            </>
          )}
        </AnimatePresence>

        <div className="flex items-center justify-around px-2 py-1.5 safe-bottom">
          {DOCK_NAV.filter((_, i) => i < MOBILE_PRIMARY_COUNT).map((item) => {
            const active = pathname.startsWith(item.href);
            const locked = navLocked(item);
            return (
              <Link
                key={item.href}
                href={locked ? "#" : item.href}
                onClick={item.href === "/home" && !locked ? handleHomeClick : undefined}
                aria-disabled={locked}
                className={`flex flex-col items-center gap-0.5 py-1 px-2 rounded-lg transition-colors ${
                  locked
                    ? "text-[var(--muted-foreground)]/30 cursor-not-allowed"
                    : active
                      ? "text-[var(--primary)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={18} strokeWidth={active ? 2 : 1.5} />
                <span className="text-[9px] font-body leading-none">{t(item.label)}</span>
              </Link>
            );
          })}
          {/* More trigger — opens the destination sheet */}
          <button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            aria-expanded={moreOpen}
            aria-haspopup="menu"
            className={`flex flex-col items-center gap-0.5 py-1 px-2 rounded-lg transition-colors ${
              moreOpen || DOCK_NAV.slice(MOBILE_PRIMARY_COUNT).some(p => pathname.startsWith(p.href))
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <LayoutGrid size={18} strokeWidth={1.5} />
            <span className="text-[9px] font-body leading-none">{t("More")}</span>
          </button>
        </div>
      </nav>
    </>
  );
}
