"use client";

import { useEffect, useState } from "react";
import RewardCard from "./RewardCard";
import { Award, Flame, Calendar, Trophy, Star } from "lucide-react";

interface GamificationData {
  level: number;
  title: string;
  currentXp: number;
  nextLevelXp: number;
  streak: number;
  totalSessions: number;
  badges: { id: string; name: string; earned: boolean; icon: string }[];
}

export default function GamificationDashboard() {
  const [data, setData] = useState<GamificationData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Mock fetch
    const fetchGamification = async () => {
      setLoading(true);
      try {
        // const res = await fetch(`/api/v1/study-session/gamification/me`);
        // if (res.ok) {
        //   setData(await res.json());
        // }
        setTimeout(() => {
          setData({
            level: 5,
            title: "Focused Scholar",
            currentXp: 1250,
            nextLevelXp: 2000,
            streak: 3,
            totalSessions: 14,
            badges: [
              { id: "1", name: "First Steps", earned: true, icon: "Award" },
              { id: "2", name: "3-Day Streak", earned: true, icon: "Flame" },
              { id: "3", name: "Perfect Focus", earned: true, icon: "Star" },
              { id: "4", name: "Marathon Learner", earned: false, icon: "Trophy" },
              { id: "5", name: "Early Bird", earned: false, icon: "Award" },
              { id: "6", name: "Night Owl", earned: false, icon: "Award" },
            ]
          });
          setLoading(false);
        }, 500);
      } catch (e) {
        console.error(e);
        setLoading(false);
      }
    };
    fetchGamification();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="w-8 h-8 rounded-full border-4 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!data) return <div className="p-8 text-center text-[var(--muted-foreground)]">Failed to load gamification data.</div>;

  return (
    <div className="max-w-5xl mx-auto p-6 md:p-8 space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-[var(--foreground)] mb-2">Achievements</h1>
        <p className="text-[var(--muted-foreground)]">Track your progress and rewards.</p>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-2">
          <RewardCard 
            level={data.level}
            title={data.title}
            currentXp={data.currentXp}
            nextLevelXp={data.nextLevelXp}
            streak={data.streak}
            recentBadges={data.badges.filter(b => b.earned).slice(0, 3).map(b => b.name)}
          />
        </div>
        
        <div className="bg-[var(--secondary)] rounded-xl p-5 border border-[var(--border)] flex flex-col justify-center items-center text-center">
          <div className="w-16 h-16 rounded-full bg-blue-500/10 text-blue-500 flex items-center justify-center mb-4">
            <Trophy size={32} />
          </div>
          <div className="text-3xl font-bold text-[var(--foreground)]">{data.totalSessions}</div>
          <div className="text-sm font-medium text-[var(--muted-foreground)]">Total Sessions</div>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-bold text-[var(--foreground)] mb-4">Badge Collection</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {data.badges.map((badge) => (
            <div 
              key={badge.id} 
              className={`p-4 rounded-xl border flex flex-col items-center text-center transition-all ${
                badge.earned 
                  ? "bg-[var(--secondary)] border-[var(--border)] hover:border-[var(--accent)]" 
                  : "bg-[var(--background)] border-dashed border-[var(--border)] opacity-60 grayscale"
              }`}
            >
              <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-3 ${
                badge.earned ? "bg-[var(--background)] text-yellow-500" : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
              }`}>
                {badge.icon === "Flame" ? <Flame size={24} /> : badge.icon === "Star" ? <Star size={24} /> : badge.icon === "Trophy" ? <Trophy size={24} /> : <Award size={24} />}
              </div>
              <span className={`text-sm font-semibold ${badge.earned ? "text-[var(--foreground)]" : "text-[var(--muted-foreground)]"}`}>
                {badge.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
