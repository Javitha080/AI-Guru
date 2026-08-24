"use client";

import { useEffect, useState } from "react";
import RewardCard from "./RewardCard";
import { Award, Flame, Trophy, Star } from "lucide-react";

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

export default function GamificationDashboard() {
  const [data, setData] = useState<GamificationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

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
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="w-8 h-8 rounded-full border-4 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (failed || !data) {
    return (
      <div className="p-8 text-center text-[var(--muted-foreground)]">
        Couldn&apos;t load your achievements. Make sure the AI Guru backend is running, then refresh.
      </div>
    );
  }

  const p = data.profile;
  const badges = data.badges ?? [];
  // Real totals only — every number below comes from the local DB via the API.
  const currentXp = p?.xp ?? 0;
  const nextLevelXp = (p?.level ?? 1) * LEVEL_STEP;

  return (
    <div className="max-w-5xl mx-auto p-6 md:p-8 space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-[var(--foreground)] mb-2">Achievements</h1>
        <p className="text-[var(--muted-foreground)]">Track your progress and rewards.</p>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-2">
          <RewardCard
            level={p?.level ?? 0}
            title={p?.level_title ?? "—"}
            currentXp={currentXp}
            nextLevelXp={nextLevelXp}
            streak={p?.streak ?? 0}
            recentBadges={badges.filter((b) => b.earned).slice(0, 3).map((b) => b.name)}
          />
        </div>

        <div className="bg-[var(--secondary)] rounded-xl p-5 border border-[var(--border)] flex flex-col justify-center items-center text-center">
          <div className="w-16 h-16 rounded-full bg-blue-500/10 text-blue-500 flex items-center justify-center mb-4">
            <Trophy size={32} />
          </div>
          <div className="text-3xl font-bold text-[var(--foreground)]">{p?.total_sessions ?? 0}</div>
          <div className="text-sm font-medium text-[var(--muted-foreground)]">Total Sessions</div>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-bold text-[var(--foreground)] mb-4">Badge Collection</h2>
        {badges.length === 0 ? (
          <p className="text-sm text-[var(--muted-foreground)]">
            No badges defined yet — finish study sessions to start earning.
          </p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {badges.map((badge) => (
              <div
                key={badge.id}
                title={badge.description}
                className={`p-4 rounded-xl border flex flex-col items-center text-center transition-all ${
                  badge.earned
                    ? "bg-[var(--secondary)] border-[var(--border)] hover:border-[var(--accent)]"
                    : "bg-[var(--background)] border-dashed border-[var(--border)] opacity-60 grayscale"
                }`}
              >
                <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-3 ${
                  badge.earned ? "bg-[var(--background)] text-yellow-500" : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                }`}>
                  {badgeIcon(badge.id) === "Flame" ? <Flame size={24} /> : badgeIcon(badge.id) === "Star" ? <Star size={24} /> : badgeIcon(badge.id) === "Trophy" ? <Trophy size={24} /> : <Award size={24} />}
                </div>
                <span className={`text-sm font-semibold ${badge.earned ? "text-[var(--foreground)]" : "text-[var(--muted-foreground)]"}`}>
                  {badge.name}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
