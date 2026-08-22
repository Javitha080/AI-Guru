"use client";

import { useRef, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  House,
  HeartHandshake,
  Bot,
  PenLine,
  Library,
  LayoutGrid,
  Brain,
  BookOpen,
  Timer,
  Trophy,
  Shield,
  Settings,
  Lock,
  History,
  type LucideIcon,
} from "lucide-react";
import { Tooltip } from "@/components/ui/Tooltip";
import { useCapabilityAccess } from "@/components/access/CapabilityAccessContext";
import type { Capability } from "@/lib/capability-routes";

interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
  tooltipKey?: string;
  requires?: Capability;
}

const DOCK_NAV: NavEntry[] = [
  { href: "/home", label: "Home", icon: House, tooltipKey: "Home tooltip", requires: "llm" },
  { href: "/study-room", label: "Study Room", icon: Timer, tooltipKey: "Study Room" },
  { href: "/achievements", label: "Achievements", icon: Trophy, tooltipKey: "Achievements" },
  { href: "/partners", label: "Partners", icon: HeartHandshake, tooltipKey: "Partners tooltip", requires: "llm" },
  { href: "/agents", label: "My Agents", icon: Bot, tooltipKey: "Agents tooltip" },
  { href: "/co-writer", label: "Co-Writer", icon: PenLine, tooltipKey: "Co-Writer tooltip", requires: "llm" },
  { href: "/book", label: "Book", icon: Library, tooltipKey: "Book tooltip", requires: "llm" },
  { href: "/space", label: "Learning Space", icon: LayoutGrid, tooltipKey: "Space tooltip" },
  { href: "/parent", label: "Parent Portal", icon: Shield, tooltipKey: "Parent Portal" },
  { href: "/memory", label: "Memory", icon: Brain, tooltipKey: "Memory tooltip" },
  { href: "/knowledge", label: "Knowledge Center", icon: BookOpen, tooltipKey: "Knowledge tooltip" },
  { href: "/settings", label: "Settings", icon: Settings },
];

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

  return (
    <>
      {/* Desktop: Floating bottom dock */}
      <nav
        ref={dockRef}
        className="hidden md:flex fixed bottom-5 left-1/2 -translate-x-1/2 z-40 items-center gap-1 px-2.5 py-1.5 rounded-full"
        style={{
          borderRadius: 9999,
          background: "rgba(10, 14, 20, 0.78)",
          backdropFilter: "blur(28px)",
          WebkitBackdropFilter: "blur(28px)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderTopColor: "rgba(255, 255, 255, 0.24)",
          boxShadow: "0 16px 48px rgba(0, 0, 0, 0.65), 0 0 24px var(--glow-primary), inset 0 1px 0 rgba(255, 255, 255, 0.18)",
        }}
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
              className="relative flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
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
                className={`relative flex h-9 w-9 items-center justify-center rounded-full transition-colors z-10 ${
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
        <div className="flex items-center justify-around px-2 py-1.5 safe-bottom">
          {DOCK_NAV.filter((_, i) => i < 5).map((item) => {
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
          {/* More menu for remaining items */}
          <Link
            href="/space"
            className={`flex flex-col items-center gap-0.5 py-1 px-2 rounded-lg transition-colors ${
              ["/space", "/memory", "/knowledge", "/settings"].some(p => pathname.startsWith(p))
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <LayoutGrid size={18} strokeWidth={1.5} />
            <span className="text-[9px] font-body leading-none">{t("More")}</span>
          </Link>
        </div>
      </nav>
    </>
  );
}
