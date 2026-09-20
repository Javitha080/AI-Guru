"use client";

import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  GraduationCap,
  Loader2,
  Sparkles,
  User,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { UserAvatar, AVATAR_ICONS } from "@/components/UserAvatar";
import { AVATAR_COLORS, AVATAR_ICON_NAMES } from "@/lib/avatar";
import {
  DAILY_GOAL_OPTIONS,
  FOCUS_SUBJECT_OPTIONS,
  GRADE_LEVEL_OPTIONS,
  LEARNING_STYLE_OPTIONS,
  TUTOR_TONE_OPTIONS,
  updateUserProfile,
} from "@/lib/user-profile-api";

interface ProfileSetupModalProps {
  isOpen: boolean;
  onClose: () => void;
  onComplete: () => void;
}

export function ProfileSetupModal({
  isOpen,
  onClose,
  onComplete,
}: ProfileSetupModalProps) {
  const { t } = useTranslation();
  const [step, setStep] = useState<1 | 2>(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Profile form state
  const [displayName, setDisplayName] = useState("");
  const [selectedIcon, setSelectedIcon] = useState("sparkles");
  const [selectedColor, setSelectedColor] = useState("amber");

  // Personalization form state
  const [gradeLevel, setGradeLevel] = useState<string>("Grade 12 (A/L)");
  const [learningStyle, setLearningStyle] = useState<string>("visual");
  const [targetMinutes, setTargetMinutes] = useState<number>(60);
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([
    "Mathematics",
    "Physics",
    "ICT / Computer Science",
  ]);
  const [tutorTone, setTutorTone] = useState<string>("encouraging");

  if (!isOpen) return null;

  const currentMarker = `icon:${selectedIcon}:${selectedColor}`;

  const toggleSubject = (subj: string) => {
    setSelectedSubjects((prev) =>
      prev.includes(subj) ? prev.filter((s) => s !== subj) : [...prev, subj],
    );
  };

  const handleStep1Next = (e: React.FormEvent) => {
    e.preventDefault();
    if (!displayName.trim()) {
      setError(t("Please enter your name"));
      return;
    }
    setError(null);
    setStep(2);
  };

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateUserProfile({
        display_name: displayName.trim(),
        avatar: currentMarker,
        grade_level: gradeLevel,
        learning_style: learningStyle,
        target_daily_minutes: targetMinutes,
        preferred_subjects: selectedSubjects,
        tutor_tone: tutorTone,
      });

      try {
        window.localStorage.setItem("aiguru.profile.configured", "1");
        window.sessionStorage.removeItem("aiguru.profile.suppressed-session");
      } catch {
        /* storage may be disabled */
      }

      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to save profile"));
    } finally {
      setBusy(false);
    }
  };

  const handleSkip = () => {
    try {
      window.sessionStorage.setItem("aiguru.profile.suppressed-session", "1");
    } catch {
      /* ignore */
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center overflow-y-auto bg-black/75 p-4 backdrop-blur-md">
      <div className="relative w-full max-w-2xl overflow-hidden rounded-3xl border border-[var(--glass-border-highlight)] bg-[var(--card)] p-6 shadow-2xl md:p-8">
        {/* Ambient background glow */}
        <div className="pointer-events-none absolute -top-24 left-1/2 h-72 w-96 -translate-x-1/2 rounded-full bg-[var(--glow-primary)]/15 blur-3xl" />

        {/* Header */}
        <div className="relative flex items-center justify-between border-b border-[var(--border)]/50 pb-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--primary)]/10 text-[var(--primary)] shadow-inner">
              {step === 1 ? <User size={20} /> : <Sparkles size={20} />}
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight text-[var(--foreground)] md:text-xl">
                {step === 1
                  ? t("Welcome to AI Guru — Setup Your Profile")
                  : t("Personalize Your AI Guru")}
              </h2>
              <p className="text-xs text-[var(--muted-foreground)] md:text-sm">
                {step === 1
                  ? t("Step 1 of 2: Tell us your name and customize your avatar")
                  : t("Step 2 of 2: Configure your grade, subjects & tutoring style")}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleSkip}
            className="rounded-full p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            title={t("Skip for now")}
          >
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-xs text-red-500">
            {error}
          </div>
        )}

        {/* Step 1: Identity & Avatar */}
        {step === 1 && (
          <form onSubmit={handleStep1Next} className="mt-6 space-y-6">
            {/* Live Preview & Name */}
            <div className="flex flex-col items-center gap-4 rounded-2xl border border-[var(--border)]/60 bg-[var(--background)]/50 p-5 sm:flex-row sm:items-start">
              <div className="relative flex flex-col items-center">
                <UserAvatar
                  username={displayName || "Student"}
                  avatar={currentMarker}
                  size={64}
                />
                <span className="mt-2 text-[11px] font-semibold text-[var(--muted-foreground)]">
                  {t("Preview")}
                </span>
              </div>
              <div className="w-full flex-1">
                <label
                  htmlFor="display-name-input"
                  className="block text-xs font-semibold text-[var(--foreground)]"
                >
                  {t("Your Full Name or Nickname")} *
                </label>
                <input
                  id="display-name-input"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder={t("e.g. Alex Morgan")}
                  maxLength={50}
                  autoFocus
                  required
                  className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2.5 text-sm text-[var(--foreground)] shadow-sm outline-none transition-all placeholder:text-[var(--muted-foreground)]/60 focus:border-[var(--primary)] focus:ring-2 focus:ring-[var(--primary)]/20"
                />
                <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
                  {t(
                    "AI Guru will greet you and record your study reports under this name.",
                  )}
                </p>
              </div>
            </div>

            {/* Avatar Icon Picker */}
            <div>
              <label className="block text-xs font-semibold text-[var(--foreground)]">
                {t("Choose Avatar Icon")}
              </label>
              <div className="mt-2 grid grid-cols-8 gap-2">
                {AVATAR_ICON_NAMES.map((name) => {
                  const Icon = AVATAR_ICONS[name] || Sparkles;
                  const selected = selectedIcon === name;
                  return (
                    <button
                      key={name}
                      type="button"
                      onClick={() => setSelectedIcon(name)}
                      className={`flex h-11 w-full items-center justify-center rounded-xl border transition-all ${
                        selected
                          ? "border-[var(--primary)] bg-[var(--primary)]/15 text-[var(--primary)] shadow-sm ring-2 ring-[var(--primary)]/30"
                          : "border-[var(--border)]/70 bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)]"
                      }`}
                      title={name}
                    >
                      <Icon size={18} />
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Avatar Color Picker */}
            <div>
              <label className="block text-xs font-semibold text-[var(--foreground)]">
                {t("Choose Avatar Color")}
              </label>
              <div className="mt-2 flex flex-wrap gap-3">
                {Object.entries(AVATAR_COLORS).map(([colorKey, hex]) => {
                  const selected = selectedColor === colorKey;
                  return (
                    <button
                      key={colorKey}
                      type="button"
                      onClick={() => setSelectedColor(colorKey)}
                      className={`relative h-8 w-8 rounded-full border-2 transition-transform hover:scale-105 ${
                        selected
                          ? "border-[var(--foreground)] ring-2 ring-[var(--foreground)]/40 scale-110"
                          : "border-transparent"
                      }`}
                      style={{ backgroundColor: hex }}
                      title={colorKey}
                    >
                      {selected && (
                        <Check
                          size={14}
                          className="absolute inset-0 m-auto text-white drop-shadow"
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Step 1 Actions */}
            <div className="flex items-center justify-between border-t border-[var(--border)]/50 pt-5">
              <button
                type="button"
                onClick={handleSkip}
                className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline"
              >
                {t("Skip for now")}
              </button>
              <button
                type="submit"
                className="flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-xs font-bold text-[var(--primary-foreground)] shadow-md transition-transform hover:brightness-110 active:scale-95"
              >
                <span>{t("Next: Personalization")}</span>
                <ArrowRight size={14} />
              </button>
            </div>
          </form>
        )}

        {/* Step 2: Learning Personalization */}
        {step === 2 && (
          <div className="mt-6 max-h-[60vh] space-y-6 overflow-y-auto pr-1">
            {/* Grade Level */}
            <div>
              <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--foreground)]">
                <GraduationCap size={15} className="text-[var(--primary)]" />
                <span>{t("Academic Grade / Level")}</span>
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
                          : "border-[var(--border)]/70 bg-[var(--card)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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
              <label className="block text-xs font-semibold text-[var(--foreground)]">
                {t("Preferred Learning Style")}
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
                          : "border-[var(--border)]/70 bg-[var(--card)] hover:border-[var(--border)]"
                      }`}
                    >
                      <div className="flex w-full items-center justify-between">
                        <span
                          className={`text-xs font-bold ${
                            active
                              ? "text-[var(--primary)]"
                              : "text-[var(--foreground)]"
                          }`}
                        >
                          {style.title}
                        </span>
                        {active && (
                          <CheckCircle2
                            size={14}
                            className="text-[var(--primary)]"
                          />
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
                <span>{t("Daily Study Target (Minutes)")}</span>
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
                          : "border-[var(--border)]/70 bg-[var(--card)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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
                          : "border-[var(--border)]/70 bg-[var(--card)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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
                          : "border-[var(--border)]/70 bg-[var(--card)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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

            {/* Step 2 Actions */}
            <div className="flex items-center justify-between border-t border-[var(--border)]/50 pt-5">
              <button
                type="button"
                onClick={() => setStep(1)}
                disabled={busy}
                className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] px-4 py-2 text-xs font-semibold text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
              >
                <ArrowLeft size={14} />
                <span>{t("Back")}</span>
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={busy}
                className="flex items-center gap-2 rounded-xl bg-[var(--primary)] px-6 py-2.5 text-xs font-bold text-[var(--primary-foreground)] shadow-md transition-transform hover:brightness-110 active:scale-95 disabled:opacity-50"
              >
                {busy ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>{t("Saving Profile…")}</span>
                  </>
                ) : (
                  <>
                    <span>{t("Save & Get Started")}</span>
                    <Check size={14} />
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
