"use client";

/**
 * First-run gate:
 * 1. Checks whether the user has created their student profile. If unconfigured,
 *    mounts ProfileSetupModal first.
 * 2. If the user completes or skips profile setup, checks whether a usable LLM
 *    provider is configured. If not, mounts AIWizard.
 *
 * Uses two distinct flag sets to keep profile setup and provider configuration
 * completely independent:
 * - Profile: aiguru.profile.configured (localStorage) / aiguru.profile.suppressed-session (sessionStorage)
 * - Provider: aiguru.onboarded (localStorage) / aiguru.onboarding.suppressed-session (sessionStorage)
 */

import React, { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { apiFetch, apiUrl } from "@/lib/api";
import { getUserProfileStatus } from "@/lib/user-profile-api";

const ProfileSetupModal = dynamic(
  () =>
    import("@/components/onboarding/ProfileSetupModal").then((m) => ({
      default: m.ProfileSetupModal,
    })),
  { ssr: false },
);

const AIWizard = dynamic(
  () =>
    import("@/components/onboarding/AIWizard").then((m) => ({
      default: m.AIWizard,
    })),
  { ssr: false },
);

const FLAG_PROFILE_KEY = "aiguru.profile.configured";
const SESSION_PROFILE_SUPPRESS_KEY = "aiguru.profile.suppressed-session";

const FLAG_PROVIDER_KEY = "aiguru.onboarded";
const SESSION_PROVIDER_SUPPRESS_KEY = "aiguru.onboarding.suppressed-session";

interface ProviderStatus {
  mode?: string;
  persisted_tutoring_mode?: string | null;
  configured?: boolean;
  cloud?: { health?: { available?: boolean } };
  ollama?: { health?: { available?: boolean } };
  offline?: { health?: { available?: boolean } };
}

export default function FirstRunGate() {
  const [showProfile, setShowProfile] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [checked, setChecked] = useState(false);

  const checkProviderNeedsSetup = useCallback(async (): Promise<boolean> => {
    try {
      if (window.sessionStorage.getItem(SESSION_PROVIDER_SUPPRESS_KEY) === "1")
        return false;

      // Always consult the server: a per-browser localStorage flag from a
      // previous user must never skip setup for a new user on this browser.
      const res = await apiFetch(apiUrl("/api/v1/ai-provider/status"));
      if (!res.ok) return false;
      const status: ProviderStatus | null = await res.json().catch(() => null);
      if (!status) return false;

      const offlineChosen = status.persisted_tutoring_mode === "offline";
      const hasLocalOllama = Boolean(status.ollama?.health?.available);
      const configured =
        Boolean(status.configured) ||
        Boolean(status.cloud?.health?.available) ||
        Boolean(status.offline?.health?.available) ||
        hasLocalOllama ||
        offlineChosen;

      try {
        if (configured) {
          window.localStorage.setItem(FLAG_PROVIDER_KEY, "1");
        } else {
          // Clear a stale "onboarded" flag left by a previous user.
          window.localStorage.removeItem(FLAG_PROVIDER_KEY);
        }
      } catch {
        /* ignore */
      }

      return !configured;
    } catch {
      return false; // Backend unreachable — don't block
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      try {
        // 1. Check Profile Configuration — always consult the server when the
        // onboarding gate is reachable. A stale per-browser localStorage flag
        // from a previous user must never skip setup for a new user.
        const profileSuppressed =
          window.sessionStorage.getItem(SESSION_PROFILE_SUPPRESS_KEY) === "1";

        let profileNeedsSetup = false;
        if (!profileSuppressed) {
          const status = await getUserProfileStatus();
          if (cancelled) return;
          if (!status.is_configured) {
            profileNeedsSetup = true;
            // Clear a stale "configured" flag left by a previous user.
            try {
              window.localStorage.removeItem(FLAG_PROFILE_KEY);
            } catch {
              /* ignore */
            }
          } else {
            // Self-heal localStorage flag if server says it's already configured
            try {
              window.localStorage.setItem(FLAG_PROFILE_KEY, "1");
            } catch {
              /* ignore */
            }
          }
        }

        if (profileNeedsSetup && !cancelled) {
          setShowProfile(true);
          return;
        }

        // 2. Check AI Provider Configuration if Profile is already handled
        const providerNeedsSetup = await checkProviderNeedsSetup();
        if (cancelled) return;
        if (providerNeedsSetup) {
          setShowWizard(true);
        }
      } catch {
        /* backend unreachable — fail open so the app is not blocked */
      } finally {
        if (!cancelled) setChecked(true);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [checkProviderNeedsSetup]);

  const handleProfileComplete = async () => {
    setShowProfile(false);
    // Chain directly to provider wizard if provider is still unconfigured
    const providerNeeds = await checkProviderNeedsSetup();
    if (providerNeeds) {
      setShowWizard(true);
    }
  };

  const handleProfileClose = async () => {
    setShowProfile(false);
    // Check if provider wizard also needs to be shown
    const providerNeeds = await checkProviderNeedsSetup();
    if (providerNeeds) {
      setShowWizard(true);
    }
  };

  if (!checked) return null;

  return (
    <>
      {showProfile && (
        <ProfileSetupModal
          isOpen={showProfile}
          onComplete={handleProfileComplete}
          onClose={handleProfileClose}
        />
      )}

      {showWizard && (
        <div className="fixed inset-0 z-[var(--z-onboarding)] overflow-auto bg-black/70 backdrop-blur-sm">
          <div className="min-h-full flex items-center justify-center p-4">
            <div className="w-full max-w-2xl">
              <AIWizard
                isOpen
                onComplete={() => {
                  try {
                    window.localStorage.setItem(FLAG_PROVIDER_KEY, "1");
                    window.sessionStorage.removeItem(
                      SESSION_PROVIDER_SUPPRESS_KEY,
                    );
                  } catch {
                    /* ignore */
                  }
                  setShowWizard(false);
                }}
                onClose={() => {
                  try {
                    window.sessionStorage.setItem(
                      SESSION_PROVIDER_SUPPRESS_KEY,
                      "1",
                    );
                  } catch {
                    /* ignore */
                  }
                  setShowWizard(false);
                }}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
