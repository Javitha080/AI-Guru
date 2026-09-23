"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getUserProfile,
  notifyProfileUpdated,
  PROFILE_UPDATED_EVENT,
  updateUserProfile as apiUpdateUserProfile,
  type UserProfile,
  type UserProfileUpdate,
} from "@/lib/user-profile-api";

export interface UserProfileState {
  profile: UserProfile | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<UserProfile | null>;
  updateProfile: (data: UserProfileUpdate) => Promise<UserProfile>;
}

// In-flight deduplication: when Header, Sidebar, and Home mount together,
// perform only one network request and share the result.
let inflightPromise: Promise<UserProfile | null> | null = null;
let cachedProfile: UserProfile | null = null;

/** Clear the module-level cache — must be called on logout/user-switch. */
export function clearProfileCache(): void {
  cachedProfile = null;
  inflightPromise = null;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(PROFILE_UPDATED_EVENT, { detail: null }));
  }
}

function statusOf(err: unknown): number | null {
  if (typeof err === "object" && err !== null && "status" in err) {
    const status = (err as { status: unknown }).status;
    if (typeof status === "number" && Number.isFinite(status)) return status;
  }
  const msg = err instanceof Error ? err.message : String(err ?? "");
  const match = /HTTP\s+(\d{3})/.exec(msg);
  return match ? Number(match[1]) : null;
}

function isTransientProfileError(err: unknown): boolean {
  const status = statusOf(err);
  // No status = network failure / backend unreachable (startup race).
  if (status === null) return true;
  return status === 502 || status === 503 || status === 504 || status >= 500;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchProfileWithRetry(attempts = 3): Promise<UserProfile> {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await getUserProfile();
    } catch (err) {
      lastError = err;
      // 401 means logged-out (redirect pending) — never retry, never log loudly.
      if (statusOf(err) === 401) throw err;
      if (attempt >= attempts || !isTransientProfileError(err)) throw err;
      await sleep(attempt === 1 ? 400 : 800);
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

function loadUserProfile(): Promise<UserProfile | null> {
  if (cachedProfile) {
    return Promise.resolve(cachedProfile);
  }
  if (!inflightPromise) {
    inflightPromise = fetchProfileWithRetry()
      .then((data) => {
        cachedProfile = data;
        return data;
      })
      .catch((err) => {
        // 401 is an expected logged-out state (apiFetch redirects to /login);
        // don't spam the console for it.
        if (statusOf(err) !== 401) {
          console.error("Failed to load user profile:", err);
        }
        return null;
      })
      .finally(() => {
        inflightPromise = null;
      });
  }
  return inflightPromise;
}

export function useUserProfile(): UserProfileState {
  const [profile, setProfile] = useState<UserProfile | null>(cachedProfile);
  const [loading, setLoading] = useState(!cachedProfile);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getUserProfile();
      cachedProfile = data;
      setProfile(data);
      return data;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const updateProfile = useCallback(async (data: UserProfileUpdate) => {
    setError(null);
    try {
      const updated = await apiUpdateUserProfile(data);
      cachedProfile = updated;
      setProfile(updated);
      notifyProfileUpdated(updated);
      return updated;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      throw err;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    if (!cachedProfile) {
      loadUserProfile().then((data) => {
        if (alive) {
          setProfile(data);
          setLoading(false);
        }
      });
    } else {
      setLoading(false);
    }

    const handleProfileUpdated = (event: Event) => {
      const customEvent = event as CustomEvent<UserProfile | null>;
      if (customEvent.detail) {
        cachedProfile = customEvent.detail;
        setProfile(customEvent.detail);
      } else if (customEvent.detail === null) {
        // Cache was cleared (logout/user-switch): reset local state.
        setProfile(null);
        setLoading(false);
      } else {
        void refresh();
      }
    };

    window.addEventListener(PROFILE_UPDATED_EVENT, handleProfileUpdated);
    return () => {
      alive = false;
      window.removeEventListener(PROFILE_UPDATED_EVENT, handleProfileUpdated);
    };
  }, [refresh]);

  return {
    profile,
    loading,
    error,
    refresh,
    updateProfile,
  };
}
