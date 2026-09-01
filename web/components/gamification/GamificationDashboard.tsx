"use client";

import { useCallback, useEffect, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { Award, Flame, RefreshCw, Star, Trophy } from "lucide-react";
import RewardCard from "./RewardCard";
import { BentoGrid, BentoCard, type BentoSpan } from "@/components/ui/BentoGrid";
import { useCountUp } from "@/lib/motion/useGsapReveal";
import { useScrollReveal } from "@/lib/motion/useScrollReveal";

interface Profile {
  student_id: string;
  xp: number;
  level: number;
  level_title: string;
  streak: number;
  total_sessions: number;
}

interface BadgeRow {
  id: string;
  name: string;
  description: string;
  icon_url: string;
  earned: boolean;
  earned_at: number | null;
}

interface GamificationData {
  profile: Profile | null;
  badges: BadgeRow[] | null;
}

/** Mirrors gamification_service._LEVEL_STEP (level = xp // 500 + 1). */
const LEVEL_STEP = 500;

function badgeIcon(id: string) {
  if (id.includes("streak")) return "Flame";
  if (id.includes("xp")) return "Star";
  if (id.includes("session") || id.includes("marathon") || id.includes("hour")) return "Trophy";
  return "Award";
}

function BadgeGlyph({ id, size = 24 }: { id: string; size?: number }) {
  const kind = badgeIcon(id);
  if (kind === "Flame") return <Flame size={size} />;
  if (kind === "Star") return <Star size={size} />;
  if (kind === "Trophy") return <Trophy size={size} />;
  return <Award size={size} />;
}

/* Ambient backdrop. Glass needs moving colour behind it, otherwise a blurred
   panel over a flat canvas just reads as grey plastic. Frozen by the
   prefers-reduced-motion rule in glass-surfaces.css. */
function AuroraBackdrop() {
  const blobs: CSSProperties[] = [
    {
      "--x": "14%",
      "--y": "6%",
      "--size": "460px",
      "--blob-color": "var(--glow-primary)",
      "--blob-opacity": "0.55",
      "--drift-dur": "30s",
    } as CSSProperties,
    {
      "--x": "88%",
      "--y": "32%",
      "--size": "380px",
      "--blob-color": "var(--amber-glow)",
      "--blob-opacity": "0.40",
      "--drift-dur": "38s",
      "--drift-delay": "-6s",
    } as CSSProperties,
    {
      "--x": "46%",
      "--y": "96%",
      "--size": "520px",
      "--blob-color": "var(--ember-1)",
      "--blob-opacity": "0.34",
      "--drift-dur": "44s",
      "--drift-delay": "-14s",
    } as CSSProperties,
  ];

  return (
    <div className="aurora-stage" aria-hidden="true">
      {blobs.map((style, i) => (
        <span key={i} className="aurora-blob" style={style} />
      ))}
    </div>
  );
}

function StatTile({
  label,
  value,
  icon,
  span = 4,
  tone = "ember",
  hint,
}: {
  label: string;
  value: number;
  icon: ReactNode;
  span?: BentoSpan;
  tone?: "ember" | "amber";
  hint?: string;
}) {
  const valueRef = useCountUp(value, 0);

  return (
    <BentoCard tier="liquid" span={span} tilt reveal className="flex flex-col justify-between gap-4">
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="grid place-items-center w-11 h-11 rounded-2xl shrink-0"
          style={{
            background: tone === "amber" ? "var(--amber-glow)" : "var(--ember-1)",
            color: tone === "amber" ? "var(--amber)" : "var(--primary)",
          }}
        >
          {icon}
        </span>
        <span className="text-sm font-medium text-[var(--muted-foreground)]">{label}</span>
      </div>

      <div>
        {/* The count-up hook writes textContent, so the accessible name is
            supplied separately — screen readers should not hear every tween
            frame. */}
        <span className="sr-only">{`${label}: ${value}`}</span>
        <span
          aria-hidden="true"
          ref={valueRef}
          className="font-display text-4xl font-bold tabular-nums text-[var(--foreground)]"
        >
          0
        </span>
        {hint ? (
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">{hint}</p>
        ) : null}
      </div>
    </BentoCard>
  );
}

interface GamificationDashboardProps {
  /** The route's scroll container, so scroll reveals observe the right node. */
  scrollerRef?: RefObject<HTMLElement | null>;
}

export default function GamificationDashboard({ scrollerRef }: GamificationDashboardProps) {
  const [data, setData] = useState<GamificationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setFailed(false);
      try {
        const base = "/api/v1/study-session/gamification/student-primary";
        const [pRes, bRes] = await Promise.all([
          fetch(`${base}/profile`),
          fetch(`${base}/badges`),
        ]);
        if (!pRes.ok || !bRes.ok) throw new Error("gamification api unavailable");
        const profile: Profile = await pRes.json();
        const badges: BadgeRow[] = await bRes.json();
        if (!cancelled) setData({ profile, badges: Array.isArray(badges) ? badges : [] });
      } catch (e) {
        console.error(e);
        if (!cancelled) setFailed(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  const badges = data?.badges ?? [];

  /* Re-created once the fetch resolves, so cards that mount with the data are
     the ones that get triggers. */
  const revealRoot = useScrollReveal<HTMLDivElement>(scrollerRef, [
    loading,
    failed,
    badges.length,
  ]);

  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center justify-center min-h-[50vh]"
      >
        <div
          aria-hidden="true"
          className="w-8 h-8 rounded-full border-4 border-[var(--accent)] border-t-transparent animate-spin"
        />
        <span className="sr-only">Loading your achievements…</span>
      </div>
    );
  }

  if (failed || !data) {
    return (
      <div className="max-w-md mx-auto p-8">
        <div role="alert" className="liquid-glass p-6 text-center">
          <p className="text-[var(--foreground)] font-medium mb-1">
            Couldn&apos;t load your achievements
          </p>
          <p className="text-sm text-[var(--muted-foreground)] mb-5">
            Make sure the AI Guru backend is running, then try again.
          </p>
          <button type="button" onClick={retry} className="glass-btn-secondary inline-flex items-center gap-2">
            <RefreshCw size={15} aria-hidden="true" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  const p = data.profile;
  const level = Math.max(1, p?.level ?? 1);
  const currentXp = p?.xp ?? 0;
  const nextLevelXp = level * LEVEL_STEP;

  /* Progress within the *current* level, not against lifetime XP. The old
     `currentXp / nextLevelXp` overstated the bar badly — a student 100 XP into
     level 2 rendered at 60% full. */
  const xpIntoLevel = Math.max(0, currentXp - (level - 1) * LEVEL_STEP);
  const levelPercent = Math.min(100, Math.round((xpIntoLevel / LEVEL_STEP) * 100));

  const earned = badges.filter((b) => b.earned);

  return (
    <div ref={revealRoot} className="relative min-h-full">
      <AuroraBackdrop />

      <div className="relative z-[1] max-w-6xl mx-auto p-6 md:p-8 space-y-8">
        <header data-scroll-reveal>
          <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight text-[var(--foreground)] mb-2">
            Achievements
          </h1>
          <p className="text-[var(--muted-foreground)]">
            Track your progress and rewards.
          </p>
        </header>

        <BentoGrid gap="md" minRow="7rem">
          {/* 8x2 anchor cell. RewardCard owns its own glass surface so it can
              be dropped anywhere, hence a plain span wrapper here. */}
          <div
            data-scroll-reveal
            className="md:col-span-6 lg:col-span-8 lg:row-span-2"
          >
            <RewardCard
              level={level}
              title={p?.level_title ?? "—"}
              currentXp={currentXp}
              nextLevelXp={nextLevelXp}
              percent={levelPercent}
              streak={p?.streak ?? 0}
              recentBadges={earned.slice(0, 3).map((b) => b.name)}
            />
          </div>

          <StatTile
            label="Total sessions"
            value={p?.total_sessions ?? 0}
            icon={<Trophy size={22} />}
            span={4}
          />

          <StatTile
            label="Badges earned"
            value={earned.length}
            icon={<Award size={22} />}
            span={4}
            tone="amber"
            hint={badges.length > 0 ? `of ${badges.length} available` : undefined}
          />
        </BentoGrid>

        <section aria-labelledby="badge-collection-heading" className="space-y-4">
          <h2
            id="badge-collection-heading"
            data-scroll-reveal
            className="font-display text-xl font-bold text-[var(--foreground)]"
          >
            Badge collection
          </h2>

          {badges.length === 0 ? (
            <p className="text-sm text-[var(--muted-foreground)]">
              No badges defined yet — finish study sessions to start earning.
            </p>
          ) : (
            <ul className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 list-none p-0 m-0">
              {badges.map((badge) => (
                <li
                  key={badge.id}
                  data-scroll-reveal
                  className={
                    badge.earned
                      ? "liquid-glass liquid-glass--spotlight liquid-glass--interactive p-4 flex flex-col items-center text-center"
                      : "surface-glass-base rounded-[1.25rem] border-dashed p-4 flex flex-col items-center text-center opacity-60 grayscale"
                  }
                >
                  <span
                    aria-hidden="true"
                    className="grid place-items-center w-12 h-12 rounded-full mb-3 shrink-0"
                    style={{
                      background: badge.earned ? "var(--amber-glow)" : "var(--muted)",
                      color: badge.earned ? "var(--amber)" : "var(--muted-foreground)",
                    }}
                  >
                    <BadgeGlyph id={badge.id} />
                  </span>

                  <span
                    className={`text-sm font-semibold ${
                      badge.earned ? "text-[var(--foreground)]" : "text-[var(--muted-foreground)]"
                    }`}
                  >
                    {badge.name}
                  </span>

                  {/* Earned state is carried by more than desaturation. */}
                  <span className="sr-only">{badge.earned ? "Earned" : "Locked"}</span>

                  <p className="mt-1 text-[11px] leading-snug text-[var(--muted-foreground)] line-clamp-2">
                    {badge.description}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
