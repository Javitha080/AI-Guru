'use client';

import React, { useEffect, useState } from 'react';
import { BarChart, Activity, BookOpen, Calendar } from 'lucide-react';

interface AnalyticsProps {
  studentId: string;
}

export default function ParentAnalytics({ studentId }: AnalyticsProps) {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const res = await fetch(`/api/v1/parent/sessions/${studentId}`);
        if (res.ok) {
          const json = await res.json();
          setData(json);
        }
      } catch (error) {
        console.error('Failed to fetch analytics', error);
      }
    };
    fetchAnalytics();
  }, [studentId]);

  if (!data) {
    return <div className="p-4 flex justify-center"><div className="animate-pulse flex space-x-4">Loading analytics...</div></div>;
  }

  const weekly: number[] = Array.isArray(data.weekly_study_time) ? data.weekly_study_time : [];
  const focusTrend: number[] = Array.isArray(data.focus_trend) ? data.focus_trend : [];
  // Derive top subjects from the per-session list (backend doesn't precompute).
  const subjectCounts = new Map<string, number>();
  for (const s of Array.isArray(data.sessions) ? data.sessions : []) {
    const subj = String(s?.subject || "").trim();
    if (subj) subjectCounts.set(subj, (subjectCounts.get(subj) ?? 0) + 1);
  }
  const topSubjects = [...subjectCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([s]) => s);

  const maxStudyTime = Math.max(...weekly, 1);
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-200 dark:border-gray-700">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6 flex items-center gap-2">
        <Activity className="text-blue-500" size={20} />
        Weekly Analytics
      </h3>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
        <div>
          <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-4">Study Time (Minutes)</h4>
          <div className="flex items-end gap-2 h-40">
            {weekly.map((time: number, idx: number) => {
              const heightPercentage = (time / maxStudyTime) * 100;
              return (
                <div key={idx} className="flex-1 flex flex-col items-center gap-2">
                  <div className="w-full bg-blue-100 dark:bg-blue-900/30 rounded-t-sm relative h-full flex items-end">
                    <div 
                      className="w-full bg-blue-500 rounded-t-sm transition-all duration-500" 
                      style={{ height: `${heightPercentage}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500">{days[idx]}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-4">Focus Trend (%)</h4>
          <div className="flex items-end gap-2 h-40">
            {focusTrend.map((score: number, idx: number) => {
              const heightPercentage = score; // 0 to 100
              return (
                <div key={idx} className="flex-1 flex flex-col items-center gap-2">
                  <div className="w-full bg-green-100 dark:bg-green-900/30 rounded-t-sm relative h-full flex items-end">
                    <div
                      className="w-full bg-green-500 rounded-t-sm transition-all duration-500"
                      style={{ height: `${heightPercentage}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500">#{idx + 1}</span>
                </div>
              );
            })}
            {focusTrend.length === 0 && (
              <div className="col-span-full text-xs text-gray-400 self-center">No sessions yet this week.</div>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-gray-50 dark:bg-gray-700/50 p-4 rounded-lg flex items-start gap-3">
          <Calendar className="text-purple-500 mt-1" size={18} />
          <div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">{data.session_count_week}</div>
            <div className="text-xs text-gray-500">Sessions this week</div>
          </div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-700/50 p-4 rounded-lg flex items-start gap-3">
          <BarChart className="text-orange-500 mt-1" size={18} />
          <div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">{data.session_count_month}</div>
            <div className="text-xs text-gray-500">Sessions this month</div>
          </div>
        </div>
        <div className="col-span-2 bg-gray-50 dark:bg-gray-700/50 p-4 rounded-lg flex items-start gap-3">
          <BookOpen className="text-indigo-500 mt-1" size={18} />
          <div>
            <div className="text-sm font-semibold text-gray-900 dark:text-white">Top Subjects</div>
            <div className="text-xs text-gray-500 flex gap-2 mt-1 flex-wrap">
              {topSubjects.length === 0 ? (
                <span className="text-gray-400">Complete a session to see subjects here.</span>
              ) : (
                topSubjects.map((sub, i) => (
                  <span key={i} className="px-2 py-1 bg-white dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-600">{sub}</span>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
