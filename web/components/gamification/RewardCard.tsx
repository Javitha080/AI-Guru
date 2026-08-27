"use client";

import { Flame, Star, Trophy, Award } from "lucide-react";

interface RewardCardProps {
  level: number;
  title: string;
  currentXp: number;
  nextLevelXp: number;
  streak: number;
  recentBadges: string[];
}

export default function RewardCard({ level, title, currentXp, nextLevelXp, streak, recentBadges }: RewardCardProps) {
  const progressPercent = Math.min(100, Math.max(0, (currentXp / nextLevelXp) * 100));

  return (
    <div className="bg-[var(--secondary)] rounded-xl p-5 border border-[var(--border)] w-full transition-all duration-[var(--duration-fast,250ms)] ease-[var(--ease-smooth-out)] hover:-translate-y-1 hover:shadow-lg">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-[var(--accent)] flex items-center justify-center transition-transform duration-200 hover:scale-110">
            <Star className="text-[var(--foreground)]" size={24} />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--foreground)]">Level {level}</h3>
            <p className="text-sm text-[var(--muted-foreground)] font-medium">{title}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-orange-500/10 text-orange-500 font-bold border border-orange-500/20 transition-transform duration-200 hover:scale-105">
          <Flame size={16} fill="currentColor" />
          {streak}
        </div>
      </div>

      <div className="mb-5">
        <div className="flex justify-between text-xs mb-1.5">
          <span className="text-[var(--muted-foreground)] font-medium">{currentXp} XP</span>
          <span className="text-[var(--muted-foreground)] font-medium">{nextLevelXp} XP</span>
        </div>
        <div className="h-2.5 w-full bg-[var(--background)] rounded-full overflow-hidden">
          <div 
            className="h-full bg-[var(--accent)] rounded-full transition-all duration-500 ease-[var(--ease-smooth-out)]"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {recentBadges.length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-[var(--muted-foreground)] font-semibold mb-2">Recent Badges</h4>
          <div className="flex gap-2">
            {recentBadges.map((badge, idx) => (
              <div 
                key={idx} 
                className="w-8 h-8 rounded-full bg-[var(--background)] border border-[var(--border)] flex items-center justify-center text-[var(--foreground)] tooltip transition-transform duration-150 hover:scale-115 active:scale-95 cursor-pointer" 
                title={badge}
              >
                <Award size={16} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
