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

function loadUserProfile(): Promise<UserProfile | null> {
  if (cachedProfile) {
    return Promise.resolve(cachedProfile);
  }
  if (!inflightPromise) {
    inflightPromise = getUserProfile()
      .then((data) => {
        cachedProfile = data;
        return data;
      })
      .catch((err) => {
        console.error("Failed to load user profile:", err);
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
      const customEvent = event as CustomEvent<UserProfile>;
      if (customEvent.detail) {
        cachedProfile = customEvent.detail;
        setProfile(customEvent.detail);
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
