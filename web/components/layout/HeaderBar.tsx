"use client";

import { useTranslation } from "react-i18next";
import { usePathname } from "next/navigation";
import { BookOpenCheck, Search, User } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { openCommandPalette } from "@/components/common/CommandPalette";
import { useUserProfile } from "@/hooks/useUserProfile";
import { UserAvatar } from "@/components/UserAvatar";

interface HeaderBarProps {
  /** Current workspace/page title */
  title?: string;
  /** Slot for model selector or other controls */
  actionSlot?: React.ReactNode;
}

export default function HeaderBar({ title, actionSlot }: HeaderBarProps) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const { profile } = useUserProfile();

  const isConfigured = Boolean(profile?.is_configured && profile?.display_name);
  const onPapers = pathname.startsWith("/papers");

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
          href="/papers"
          aria-label="Paper Bank"
          title="Paper Bank — built-in past papers"
          aria-current={onPapers ? "page" : undefined}
          className={`surface-glass-base hidden sm:flex h-8.5 items-center gap-2 rounded-full px-3.5 text-xs font-bold transition-all border active:scale-95 ${
            onPapers
              ? "text-[var(--primary)] border-[var(--ember-line)]/50 shadow-[0_0_16px_var(--glow-primary)]"
              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)] border-[var(--glass-border)] hover:border-[var(--glass-border-highlight)]"
          }`}
        >
          <BookOpenCheck size={15} strokeWidth={2} className={onPapers ? "text-[var(--primary)]" : ""} />
          <span>Paper Bank</span>
        </Link>

        {isConfigured ? (
          <Link
            href="/profile"
            className="surface-glass-base flex h-8.5 items-center gap-2 rounded-full px-2.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--glass-border-highlight)] transition-all border border-[var(--glass-border)] active:scale-95 group"
            aria-label={t("Profile")}
            title={`${t("Profile")} — ${profile?.display_name}`}
          >
            <UserAvatar
              username={profile?.display_name || "Student"}
              userId={profile?.student_id}
              avatar={profile?.avatar}
              role={profile?.role}
              size={20}
            />
            <span className="hidden md:inline font-body text-xs font-semibold text-[var(--foreground)] max-w-[120px] truncate group-hover:text-[var(--primary)] transition-colors">
              {profile?.display_name}
            </span>
          </Link>
        ) : (
          <Link
            href="/profile"
            className="surface-glass-base flex h-8.5 w-8.5 items-center justify-center rounded-full text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--glass-border-highlight)] transition-all border border-[var(--glass-border)] active:scale-95"
            aria-label={t("Profile")}
            title={t("Profile")}
          >
            <User size={16} strokeWidth={1.8} />
          </Link>
        )}
      </div>
    </header>
  );
}
