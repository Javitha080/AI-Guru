"use client";

import { useTranslation } from "react-i18next";
import { Search, User } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { openCommandPalette } from "@/components/common/CommandPalette";

interface HeaderBarProps {
  /** Current workspace/page title */
  title?: string;
  /** Slot for model selector or other controls */
  actionSlot?: React.ReactNode;
}

export default function HeaderBar({ title, actionSlot }: HeaderBarProps) {
  const { t } = useTranslation();

  return (
    <header className="relative flex h-14 shrink-0 items-center justify-between px-4 md:px-6 z-30">
      {/* Left: Logo + Title */}
      <div className="flex items-center gap-3 min-w-0">
        <Link href="/" className="flex items-center gap-2.5 shrink-0 group">
          <div className="relative">
            <Image
              src="/logo.png"
              alt="AI Guru"
              width={26}
              height={26}
              className="h-6.5 w-6.5 rounded-lg shadow-sm group-hover:scale-105 transition-transform duration-200"
            />
          </div>
          <span className="font-display font-bold text-sm tracking-tight text-[var(--foreground)] hidden sm:inline">
            AI Guru
          </span>
        </Link>
        {title && (
          <>
            <span className="text-[var(--border)] text-sm opacity-60">/</span>
            <span className="text-xs font-semibold text-[var(--muted-foreground)] truncate">
              {title}
            </span>
          </>
        )}
      </div>

      {/* Center: Search Launcher — opens the global ⌘K command palette */}
      <div className="hidden md:flex absolute left-1/2 -translate-x-1/2">
        <button
          type="button"
          onClick={() => openCommandPalette()}
          className="flex items-center gap-2.5 px-4 py-1.5 rounded-full surface-glass-base border border-[var(--glass-border)] hover:border-[var(--glass-border-highlight)] hover:shadow-[0_0_20px_var(--glow-primary)] text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-all duration-200 group active:scale-95"
          aria-label={t("Search")}
          title={t("Search (⌘K)")}
        >
          <Search size={14} strokeWidth={1.8} className="text-[var(--primary)] group-hover:scale-110 transition-transform duration-200" />
          <span className="font-body text-xs font-medium">{t("Search")}</span>
          <kbd className="ml-1.5 text-[10px] font-mono font-bold opacity-75 border border-[var(--glass-border)] rounded-md px-1.5 py-0.5 bg-[var(--muted)]/50">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Right: Action slot + Mobile Search + Avatar */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => openCommandPalette()}
          className="flex md:hidden surface-glass-base h-8.5 w-8.5 items-center justify-center rounded-full text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors border border-[var(--glass-border)]"
          aria-label={t("Search")}
          title={t("Search")}
        >
          <Search size={16} strokeWidth={1.8} />
        </button>

        {actionSlot}
        <Link
          href="/profile"
          className="surface-glass-base flex h-8.5 w-8.5 items-center justify-center rounded-full text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--glass-border-highlight)] transition-all border border-[var(--glass-border)] active:scale-95"
          aria-label={t("Profile")}
          title={t("Profile")}
        >
          <User size={16} strokeWidth={1.8} />
        </Link>
      </div>
    </header>
  );
}
