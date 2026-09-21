"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus, type AuthStatus } from "@/lib/auth";
import { useUserProfile } from "@/hooks/useUserProfile";
import { UserAvatar } from "@/components/UserAvatar";

interface ProfileLinkProps {
  collapsed?: boolean;
}

export function ProfileLink({ collapsed = false }: ProfileLinkProps) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const { profile } = useUserProfile();

  useEffect(() => {
    fetchAuthStatus().then((next) => {
      setAuthStatus(next);
    });
  }, []);

  // When auth is enabled, require authenticated session.
  // When auth is disabled, allow local mode student profile.
  const isAuthEnabled = Boolean(authStatus?.enabled);
  const isAuthenticated = Boolean(authStatus?.authenticated);

  if (isAuthEnabled && !isAuthenticated) {
    return null;
  }

  // Precedence: prefer the friendly student profile name when the user has
  // configured one; fall back to the auth identity (often an email/username).
  const hasFriendlyName =
    Boolean(profile?.is_configured) &&
    Boolean(profile?.display_name) &&
    profile?.display_name !== "Student";
  const displayName = hasFriendlyName
    ? String(profile?.display_name)
    : isAuthEnabled
      ? authStatus?.username || ""
      : profile?.display_name || "Student";

  const userId = isAuthEnabled ? authStatus?.user_id : profile?.student_id;
  const avatarMarker =
    hasFriendlyName && profile?.avatar ? profile.avatar : isAuthEnabled ? authStatus?.avatar : profile?.avatar;
  const role = isAuthEnabled ? authStatus?.role : profile?.role;

  if (!displayName) return null;

  const active = pathname.startsWith("/profile");
  const avatar = (
    <UserAvatar
      username={displayName}
      userId={userId}
      avatar={avatarMarker}
      role={role}
      size={collapsed ? 18 : 16}
    />
  );

  if (collapsed) {
    return (
      <Link
        href="/profile"
        className={`rounded-lg p-2 transition-colors ${
          active
            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
        }`}
        aria-label={t("My profile")}
        title={`${t("My profile")} — ${displayName}`}
      >
        {avatar}
      </Link>
    );
  }

  return (
    <Link
      href="/profile"
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
        active
          ? "bg-[var(--primary)]/10 text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
      }`}
      title={t("My profile")}
    >
      {avatar}
      <span className="truncate">{displayName}</span>
    </Link>
  );
}
