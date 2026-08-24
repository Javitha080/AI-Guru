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
    <header className="flex h-12 shrink-0 items-center justify-between px-4 md:px-6">
      {/* Left: Logo + Title */}
      <div className="flex items-center gap-3 min-w-0">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <Image
            src="/logo.png"
            alt="AI Guru"
            width={24}
            height={24}
            className="h-6 w-6 rounded-md"
          />
          <span className="font-display font-semibold text-sm text-[var(--foreground)] hidden sm:inline">
            AI Guru
          </span>
        </Link>
        {title && (
          <>
            <span className="text-[var(--border)] text-sm">/</span>
            <span className="text-sm font-body text-[var(--muted-foreground)] truncate">
              {title}
            </span>
          </>
        )}
      </div>

      {/* Center: Search Launcher — opens the global ⌘K command palette */}
      <button
        type="button"
        onClick={() => openCommandPalette()}
        className="hidden md:flex items-center gap-2 glass-capsule px-4 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
        aria-label={t("Search")}
        title={t("Search")}
      >
        <Search size={14} strokeWidth={1.6} />
        <span className="font-body text-xs">{t("Search")}</span>
        <kbd className="ml-2 text-[10px] font-mono opacity-50 border border-[var(--glass-border)] rounded px-1">
          ⌘K
        </kbd>
      </button>

      {/* Right: Action slot + Avatar */}
      <div className="flex items-center gap-2">
        {actionSlot}
        <button
          type="button"
          className="glass-btn-ghost flex h-8 w-8 items-center justify-center rounded-full"
          aria-label={t("Profile")}
        >
          <User size={16} strokeWidth={1.6} />
        </button>
      </div>
    </header>
  );
}
