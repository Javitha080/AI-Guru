"use client";

import { Award, Target, Eye, AlertTriangle, ChevronRight } from "lucide-react";
import Link from "next/link";

interface SessionStats {
  durationMinutes: number;
  focusScore: number;
  engagementScore: number;
  distractionCount: number;
  warningCount: number;
  xpEarned: number;
  badgesUnlocked: string[];
}

interface SessionReportViewProps {
  stats: SessionStats;
  onHome: () => void;
}

export default function SessionReportView({ stats, onHome }: SessionReportViewProps) {
  return (
    <div className="w-full max-w-2xl mx-auto p-6 md:p-8">
      <div className="text-center mb-10 text-balance">
        <h1 className="text-3xl font-bold text-[var(--foreground)] mb-2">Session Complete!</h1>
        <p className="text-[var(--muted-foreground)]">Great job staying focused. Here is your summary.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-[var(--secondary)] p-4 rounded-xl flex flex-col items-center justify-center text-center">
          <div className="text-2xl font-bold text-[var(--foreground)] mb-1">{stats.durationMinutes}m</div>
          <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider font-semibold">Study Time</div>
        </div>
        <div className="bg-[var(--secondary)] p-4 rounded-xl flex flex-col items-center justify-center text-center">
          <div className="text-2xl font-bold text-green-500 mb-1">{stats.focusScore}%</div>
          <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider font-semibold">Focus Score</div>
        </div>
        <div className="bg-[var(--secondary)] p-4 rounded-xl flex flex-col items-center justify-center text-center">
          <div className="text-2xl font-bold text-blue-500 mb-1">{stats.engagementScore}%</div>
          <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider font-semibold">Engagement</div>
        </div>
        <div className="bg-[var(--secondary)] p-4 rounded-xl flex flex-col items-center justify-center text-center">
          <div className="text-2xl font-bold text-[var(--accent)] mb-1">+{stats.xpEarned}</div>
          <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider font-semibold">XP Earned</div>
        </div>
      </div>

      <div className="bg-[var(--secondary)] rounded-xl p-5 mb-8 flex items-start gap-4">
        <div className="p-3 bg-[var(--background)] rounded-lg shrink-0">
          <Target className="text-[var(--accent)]" size={24} />
        </div>
        <div>
          <h3 className="font-semibold text-[var(--foreground)] mb-1">AI Summary</h3>
          <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
            You maintained excellent focus during the middle part of the session. 
            There were {stats.distractionCount} minor distractions, mostly looking away from the screen. 
            Keep it up!
          </p>
        </div>
      </div>

      {stats.badgesUnlocked.length > 0 && (
        <div className="mb-8">
          <h3 className="text-sm font-semibold text-[var(--muted-foreground)] uppercase tracking-wider mb-4">Badges Unlocked</h3>
          <div className="flex gap-4 flex-wrap">
            {stats.badgesUnlocked.map((badge, idx) => (
              <div key={idx} className="flex items-center gap-2 bg-yellow-500/10 text-yellow-500 px-4 py-2 rounded-full border border-yellow-500/20">
                <Award size={18} />
                <span className="font-medium">{badge}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-4 justify-center">
        <button
          onClick={onHome}
          className="px-6 py-3 rounded-lg border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--secondary)] font-medium transition-colors"
        >
          Back to Study Room
        </button>
        <Link href="/achievements">
          <span className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-[var(--accent)] text-[var(--foreground)] font-medium hover:opacity-90 transition-opacity">
            View Achievements <ChevronRight size={18} />
          </span>
        </Link>
      </div>
    </div>
  );
}
