"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createElement } from "react";
import {
  ArrowLeft,
  BookOpen,
  Check,
  CheckCircle2,
  Clock,
  Flame,
  GraduationCap,
  ImageUp,
  Loader2,
  LogOut,
  Save,
  ShieldCheck,
  Sparkles,
  Trophy,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus, logout, type AuthStatus } from "@/lib/auth";
import {
  uploadAvatarImage,
  removeAvatarImage,
} from "@/lib/profile-api";
import {
  getUserProfile,
  updateUserProfile,
  DAILY_GOAL_OPTIONS,
  FOCUS_SUBJECT_OPTIONS,
  GRADE_LEVEL_OPTIONS,
  LEARNING_STYLE_OPTIONS,
  TUTOR_TONE_OPTIONS,
  type UserProfile,
} from "@/lib/user-profile-api";
import {
  AVATAR_COLOR_NAMES,
  AVATAR_COLORS,
  AVATAR_ICON_NAMES,
  fallbackAvatarFor,
  UserAvatar,
  AVATAR_ICONS,
} from "@/components/UserAvatar";
import { parseAvatarMarker } from "@/lib/avatar";

const AVATAR_OUTPUT_SIZE = 256;
const MAX_SOURCE_BYTES = 20 * 1024 * 1024;

/** Center-crop to a square and downscale; canvas re-encode also strips EXIF. */
async function cropToSquareBlob(file: File): Promise<Blob> {
  let source: CanvasImageSource;
  let width: number;
  let height: number;
  try {
    const bitmap = await createImageBitmap(file, {
      imageOrientation: "from-image",
    });
    source = bitmap;
    width = bitmap.width;
    height = bitmap.height;
  } catch {
    const url = URL.createObjectURL(file);
    try {
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const el = new Image();
        el.onload = () => resolve(el);
        el.onerror = () => reject(new Error("Could not decode image"));
        el.src = url;
      });
      source = image;
      width = image.naturalWidth;
      height = image.naturalHeight;
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  if (!width || !height) throw new Error("Could not decode image");

  const side = Math.min(width, height);
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_OUTPUT_SIZE;
  canvas.height = AVATAR_OUTPUT_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not decode image");
  ctx.drawImage(
    source,
    (width - side) / 2,
    (height - side) / 2,
    side,
    side,
    0,
    0,
    AVATAR_OUTPUT_SIZE,
    AVATAR_OUTPUT_SIZE,
  );
  if (typeof ImageBitmap !== "undefined" && source instanceof ImageBitmap) {
    source.close();
  }

  const toBlob = (type: string, quality?: number) =>
    new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, type, quality),
    );
  const blob =
    (await toBlob("image/webp", 0.85)) ?? (await toBlob("image/png"));
  if (!blob) throw new Error("Could not encode image");
  return blob;
}

export default function ProfilePage() {
  const router = useRouter();
  const { t } = useTranslation();

  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Editable form fields
  const [displayName, setDisplayName] = useState("");
  const [selectedAvatar, setSelectedAvatar] = useState("");
  const [gradeLevel, setGradeLevel] = useState("Grade 12 (A/L)");
  const [school, setSchool] = useState("");
  const [learningStyle, setLearningStyle] = useState("visual");
  const [targetMinutes, setTargetMinutes] = useState(60);
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([]);
  const [tutorTone, setTutorTone] = useState("encouraging");

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const prof = await getUserProfile();
      setProfile(prof);
      setDisplayName(prof.display_name === "Student" ? "" : prof.display_name);
      setSelectedAvatar(prof.avatar);
      if (prof.grade_level) setGradeLevel(prof.grade_level);
      setSchool(prof.school || "");
      if (prof.learning_style) setLearningStyle(prof.learning_style);
      if (prof.target_daily_minutes) setTargetMinutes(prof.target_daily_minutes);
      if (prof.preferred_subjects) setSelectedSubjects(prof.preferred_subjects);
      if (prof.tutor_tone) setTutorTone(prof.tutor_tone);
    } catch (err) {
      // Surface the backend's status/detail when available; fall back to i18n.
      const msg = err instanceof Error && /HTTP \d{3}/.test(err.message)
        ? err.message
        : t("Failed to load profile");
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const st = await fetchAuthStatus();
        if (cancelled) return;
        setAuthStatus(st);

        // If auth is enabled but user is not signed in, redirect to login
        if (st?.enabled && !st.authenticated) {
          router.replace("/login");
          return;
        }

        await loadProfile();
      } catch {
        if (!cancelled) setError(t("Failed to load profile"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, t]);

  const toggleSubject = (subj: string) => {
    setSelectedSubjects((prev) =>
      prev.includes(subj) ? prev.filter((s) => s !== subj) : [...prev, subj],
    );
  };

  const applyAvatarMarker = useCallback(
    async (marker: string) => {
      setSelectedAvatar(marker);
      setBusy(true);
      setError(null);
      try {
        const updated = await updateUserProfile({ avatar: marker });
        setProfile(updated);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const handleUpload = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      try {
        if (file.size > MAX_SOURCE_BYTES) {
          throw new Error(t("Image is too large"));
        }
        const blob = await cropToSquareBlob(file);
        const marker = await uploadAvatarImage(blob);
        setSelectedAvatar(marker);
        const updated = await updateUserProfile({ avatar: marker });
        setProfile(updated);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [t],
  );

  const handleRemoveImage = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await removeAvatarImage();
      setSelectedAvatar("");
      const updated = await updateUserProfile({ avatar: "" });
      setProfile(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const handleSaveChanges = async () => {
    if (!displayName.trim()) {
      setError(t("Display name cannot be empty"));
      return;
    }
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const updated = await updateUserProfile({
        display_name: displayName.trim(),
        avatar: selectedAvatar,
        grade_level: gradeLevel,
        school: school.trim(),
        learning_style: learningStyle,
        target_daily_minutes: targetMinutes,
        preferred_subjects: selectedSubjects,
        tutor_tone: tutorTone,
      });
      setProfile(updated);
      setSuccessMsg(t("Profile & personalizations saved successfully!"));
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to save profile"));
    } finally {
      setBusy(false);
    }
  };

  const handleSignOut = useCallback(async () => {
    await logout();
    router.replace("/login");
  }, [router]);

  const descriptor = parseAvatarMarker(selectedAvatar || profile?.avatar);
  const hasImage = descriptor.kind === "image";
  const fallback = fallbackAvatarFor(displayName || profile?.username || "Student");
  const currentIcon =
    descriptor.kind === "icon"
      ? descriptor.icon
      : hasImage
        ? null
        : fallback.icon;
  const currentColor =
    descriptor.kind === "icon"
      ? descriptor.color
      : hasImage
        ? null
        : fallback.color;

  const isAdmin = authStatus?.enabled && authStatus?.role === "admin";

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-8 [scrollbar-gutter:stable] md:py-10">
      <div className="mx-auto max-w-3xl">
        {/* Navigation Bar */}
        <div className="mb-6 flex items-center justify-between">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back to Workspace")}
          </Link>
          <button
            type="button"
            onClick={handleSaveChanges}
            disabled={busy}
            className="flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2 text-xs font-bold text-[var(--primary-foreground)] shadow-md transition-transform hover:brightness-110 active:scale-95 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Save size={14} />
            )}
            <span>{t("Save Changes")}</span>
          </button>
        </div>

        {/* Page Title */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
            {t("Student Profile & Personalizations")}
          </h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t("Customize your display name, visual avatar, learning style, and study targets.")}
          </p>
        </div>

        {error && (
          <div className="mb-6 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {successMsg && (
          <div className="mb-6 flex items-center gap-2 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 size={16} />
            <span>{successMsg}</span>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center rounded-3xl border border-[var(--border)] bg-[var(--card)] py-20 text-sm text-[var(--muted-foreground)] shadow-sm">
            <Loader2 size={24} className="mr-2 animate-spin text-[var(--primary)]" />
            <span>{t("Loading profile…")}</span>
          </div>
        ) : !profile ? (
          <div className="flex flex-col items-center justify-center rounded-3xl border border-[var(--border)] bg-[var(--card)] px-6 py-16 text-center shadow-sm">
            <p className="text-sm font-semibold text-[var(--foreground)]">
              {t("Could not load your profile")}
            </p>
            <p className="mt-1 max-w-sm text-xs text-[var(--muted-foreground)]">
              {error ?? t("The server may still be starting. Try again in a moment.")}
            </p>
            <button
              type="button"
              onClick={() => void loadProfile()}
              className="mt-4 rounded-xl bg-[var(--primary)] px-5 py-2 text-xs font-bold text-[var(--primary-foreground)] shadow-md transition-transform hover:brightness-110 active:scale-95"
            >
              {t("Retry")}
            </button>
          </div>
        ) : (
          <div className="space-y-6">
            {/* 1. Identity Card */}
            <div className="rounded-3xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
                <UserAvatar
                  username={displayName || profile.display_name || "Student"}
                  userId={profile.student_id}
                  avatar={selectedAvatar}
                  role={profile.role}
                  size={80}
                />
                <div className="w-full flex-1 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                        isAdmin
                          ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                          : "bg-[var(--primary)]/15 text-[var(--primary)]"
                      }`}
                    >
                      {isAdmin && <ShieldCheck size={12} />}
                      {isAdmin ? t("Administrator") : t("Student")}
                    </span>
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {profile.student_id}
                    </span>
                  </div>

                  <div className="mt-3">
                    <label
                      htmlFor="profile-name-input"
                      className="block text-xs font-semibold text-[var(--muted-foreground)]"
                    >
                      {t("Display Name")}
                    </label>
                    <input
                      id="profile-name-input"
                      type="text"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      placeholder={t("e.g. Alex Morgan")}
                      maxLength={50}
                      className="mt-1 w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-sm font-medium text-[var(--foreground)] outline-none transition-all focus:border-[var(--primary)] focus:ring-2 focus:ring-[var(--primary)]/20"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* 2. Gamification & Study Metrics Card */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-4 shadow-sm">
                <div className="flex items-center gap-2 text-xs font-semibold text-[var(--muted-foreground)]">
                  <Trophy size={15} className="text-amber-500" />
                  <span>{t("Total XP")}</span>
                </div>
                <div className="mt-2 text-xl font-bold text-[var(--foreground)]">
                  {profile.xp.toLocaleString()}
                </div>
              </div>

              <div className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-4 shadow-sm">
                <div className="flex items-center gap-2 text-xs font-semibold text-[var(--muted-foreground)]">
                  <Sparkles size={15} className="text-[var(--primary)]" />
                  <span>{t("Level")}</span>
                </div>
                <div className="mt-2 text-xl font-bold text-[var(--foreground)]">
                  Lv. {profile.level} <span className="text-xs font-normal text-[var(--muted-foreground)]">({profile.level_title})</span>
                </div>
              </div>

              <div className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-4 shadow-sm">
                <div className="flex items-center gap-2 text-xs font-semibold text-[var(--muted-foreground)]">
                  <Flame size={15} className="text-rose-500" />
                  <span>{t("Streak")}</span>
                </div>
                <div className="mt-2 text-xl font-bold text-[var(--foreground)]">
                  {profile.streak} <span className="text-xs font-normal text-[var(--muted-foreground)]">{t("days")}</span>
                </div>
              </div>

              <div className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-4 shadow-sm">
                <div className="flex items-center gap-2 text-xs font-semibold text-[var(--muted-foreground)]">
                  <BookOpen size={15} className="text-emerald-500" />
                  <span>{t("Sessions")}</span>
                </div>
                <div className="mt-2 text-xl font-bold text-[var(--foreground)]">
                  {profile.total_sessions}
                </div>
              </div>
            </div>

            {/* 3. Avatar Customization Card */}
            <div className="rounded-3xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
              <h2 className="text-sm font-bold text-[var(--foreground)]">
                {t("Avatar & Visual Theme")}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                {t("Choose an icon and color marker for your profile.")}
              </p>

              {/* Upload image flow: only enabled when multi-user auth is active */}
              {authStatus?.enabled && (
                <div className="mt-4 flex flex-wrap items-center gap-2.5 pb-4 border-b border-[var(--border)]/50">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void handleUpload(file);
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={busy}
                    className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] px-3 py-1.5 text-xs font-semibold text-[var(--foreground)] transition-colors hover:bg-[var(--background)] disabled:opacity-50"
                  >
                    <ImageUp size={14} />
                    <span>{t("Upload Custom Photo")}</span>
                  </button>
                  {hasImage && (
                    <button
                      type="button"
                      onClick={() => void handleRemoveImage()}
                      disabled={busy}
                      className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] px-3 py-1.5 text-xs font-semibold text-red-500 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                    >
                      <Trash2 size={14} />
                      <span>{t("Remove Photo")}</span>
                    </button>
                  )}
                </div>
              )}

              {/* Icon grid */}
              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold text-[var(--foreground)]">
                  {t("Icons")}
                </p>
                <div className="flex flex-wrap gap-2">
                  {AVATAR_ICON_NAMES.map((name) => {
                    const active = !hasImage && name === currentIcon;
                    const color = currentColor ?? fallback.color;
                    return (
                      <button
                        key={name}
                        type="button"
                        onClick={() => void applyAvatarMarker(`icon:${name}:${color}`)}
                        disabled={busy}
                        aria-label={name}
                        className={`flex h-10 w-10 items-center justify-center rounded-2xl text-white transition-all disabled:opacity-50 ${
                          active
                            ? "ring-2 ring-[var(--foreground)] ring-offset-2 ring-offset-[var(--card)] scale-105"
                            : "opacity-75 hover:opacity-100 hover:scale-105"
                        }`}
                        style={{ backgroundColor: AVATAR_COLORS[color] }}
                        title={name}
                      >
                        {createElement(AVATAR_ICONS[name] || Sparkles, {
                          size: 18,
                          strokeWidth: 1.8,
                        })}
                      </button>
                    );
                  })}
                </div>

                <p className="mb-2 mt-4 text-xs font-semibold text-[var(--foreground)]">
                  {t("Color Accent")}
                </p>
                <div className="flex flex-wrap gap-2.5">
                  {AVATAR_COLOR_NAMES.map((name) => {
                    const active = !hasImage && name === currentColor;
                    const icon = currentIcon ?? fallback.icon;
                    return (
                      <button
                        key={name}
                        type="button"
                        onClick={() => void applyAvatarMarker(`icon:${icon}:${name}`)}
                        disabled={busy}
                        aria-label={name}
                        className={`h-7 w-7 rounded-full transition-all disabled:opacity-50 ${
                          active
                            ? "ring-2 ring-[var(--foreground)] ring-offset-2 ring-offset-[var(--card)] scale-110"
                            : "opacity-75 hover:opacity-100 hover:scale-105"
                        }`}
                        style={{ backgroundColor: AVATAR_COLORS[name] }}
                        title={name}
                      />
                    );
                  })}
                </div>
              </div>
            </div>

            {/* 4. Academic & Tutoring Personalization Card */}
            <div className="rounded-3xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm space-y-6">
              <div>
                <h2 className="text-sm font-bold text-[var(--foreground)]">
                  {t("Academic & Tutoring Personalization")}
                </h2>
                <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  {t("Configure how AI Guru approaches questions, sessions, and guidance.")}
                </p>
              </div>

              {/* Grade Level */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--foreground)]">
                  <GraduationCap size={15} className="text-[var(--primary)]" />
                  <span>{t("Grade / Academic Level")}</span>
                </label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {GRADE_LEVEL_OPTIONS.map((grade) => {
                    const active = gradeLevel === grade;
                    return (
                      <button
                        key={grade}
                        type="button"
                        onClick={() => setGradeLevel(grade)}
                        className={`rounded-xl border px-3.5 py-1.5 text-xs font-medium transition-all ${
                          active
                            ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)] shadow-sm ring-1 ring-[var(--primary)]/30"
                            : "border-[var(--border)]/70 bg-[var(--background)]/50 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        {grade}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Learning Style */}
              <div>
                <label
                  htmlFor="profile-school-input"
                  className="block text-xs font-semibold text-[var(--foreground)]"
                >
                  {t("School (optional)")}
                </label>
                <input
                  id="profile-school-input"
                  type="text"
                  value={school}
                  onChange={(e) => setSchool(e.target.value)}
                  placeholder={t("e.g. Royal College")}
                  maxLength={100}
                  className="mt-2 w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-sm font-medium text-[var(--foreground)] outline-none transition-all focus:border-[var(--primary)] focus:ring-2 focus:ring-[var(--primary)]/20"
                />
              </div>

              {/* Learning Style */}
              <div>
                <label className="block text-xs font-semibold text-[var(--foreground)]">
                  {t("Tutoring & Learning Style")}
                </label>
                <div className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  {LEARNING_STYLE_OPTIONS.map((style) => {
                    const active = learningStyle === style.id;
                    return (
                      <button
                        key={style.id}
                        type="button"
                        onClick={() => setLearningStyle(style.id)}
                        className={`flex flex-col items-start rounded-2xl border p-3.5 text-left transition-all ${
                          active
                            ? "border-[var(--primary)] bg-[var(--primary)]/10 ring-1 ring-[var(--primary)]/30 shadow-sm"
                            : "border-[var(--border)]/70 bg-[var(--background)]/50 hover:border-[var(--border)]"
                        }`}
                      >
                        <div className="flex w-full items-center justify-between">
                          <span
                            className={`text-xs font-bold ${
                              active ? "text-[var(--primary)]" : "text-[var(--foreground)]"
                            }`}
                          >
                            {style.title}
                          </span>
                          {active && (
                            <CheckCircle2 size={14} className="text-[var(--primary)]" />
                          )}
                        </div>
                        <p className="mt-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                          {style.description}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Daily Goal */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--foreground)]">
                  <Clock size={14} className="text-[var(--primary)]" />
                  <span>{t("Daily Study Target")}</span>
                </label>
                <div className="mt-2 flex gap-2">
                  {DAILY_GOAL_OPTIONS.map((mins) => {
                    const active = targetMinutes === mins;
                    return (
                      <button
                        key={mins}
                        type="button"
                        onClick={() => setTargetMinutes(mins)}
                        className={`flex-1 rounded-xl border py-2 text-center text-xs font-semibold transition-all ${
                          active
                            ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)] shadow-sm ring-1 ring-[var(--primary)]/30"
                            : "border-[var(--border)]/70 bg-[var(--background)]/50 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        {mins}m
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Focus Subjects */}
              <div>
                <label className="block text-xs font-semibold text-[var(--foreground)]">
                  {t("Primary Focus Subjects")}
                </label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {FOCUS_SUBJECT_OPTIONS.map((subj) => {
                    const active = selectedSubjects.includes(subj);
                    return (
                      <button
                        key={subj}
                        type="button"
                        onClick={() => toggleSubject(subj)}
                        className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-all ${
                          active
                            ? "border-[var(--primary)] bg-[var(--primary)]/15 text-[var(--primary)] shadow-sm"
                            : "border-[var(--border)]/70 bg-[var(--background)]/50 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        {subj}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* AI Tutor Persona */}
              <div>
                <label className="block text-xs font-semibold text-[var(--foreground)]">
                  {t("AI Guru Tone")}
                </label>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {TUTOR_TONE_OPTIONS.map((tone) => {
                    const active = tutorTone === tone.id;
                    return (
                      <button
                        key={tone.id}
                        type="button"
                        onClick={() => setTutorTone(tone.id)}
                        className={`rounded-xl border p-2.5 text-left text-xs font-semibold transition-all ${
                          active
                            ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)] ring-1 ring-[var(--primary)]/30"
                            : "border-[var(--border)]/70 bg-[var(--background)]/50 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        <div>{tone.title}</div>
                        <div className="mt-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
                          {tone.description}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Save Button inside card */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSaveChanges}
                  disabled={busy}
                  className="flex items-center justify-center gap-2 w-full rounded-2xl bg-[var(--primary)] py-3 text-xs font-bold text-[var(--primary-foreground)] shadow-md transition-transform hover:brightness-110 active:scale-95 disabled:opacity-50"
                >
                  {busy ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Check size={16} />
                  )}
                  <span>{t("Save All Personalizations")}</span>
                </button>
              </div>
            </div>

            {/* 5. Sign out card: only rendered when multi-user auth is active */}
            {authStatus?.enabled && (
              <div className="flex items-center justify-between rounded-3xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--foreground)]">
                    {t("Sign out")}
                  </h2>
                  <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                    {t("End your session on this device")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void handleSignOut()}
                  className="flex items-center gap-1.5 rounded-xl border border-red-500/40 px-3.5 py-1.5 text-xs font-semibold text-red-600 dark:text-red-400 hover:bg-red-500/10 transition-colors"
                >
                  <LogOut size={14} />
                  <span>{t("Sign out")}</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
