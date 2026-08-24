"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  ArrowUpRight,
  ClipboardList,
  GraduationCap,
  History,
  NotebookPen,
  Plug,
  Terminal,
  UserRound,
  Wand2,
  Flame,
  Clock,
  type LucideIcon,
} from "lucide-react";

import { SPACE_MCP_SURFACE, loadMcpSurface } from "@/components/mcp/surface";
import { getCliApps } from "@/lib/cli-apps-api";
import { apiUrl } from "@/lib/api";
import { listSessions } from "@/lib/session-api";
import { listNotebooks, listNotebookEntries } from "@/lib/notebook-api";
import { listPersonas } from "@/lib/personas-api";
import { listSkills } from "@/lib/skills-api";
import { fetchAllProgress } from "@/lib/learning-api";
import { BentoGrid, BentoCard } from "@/components/ui/BentoGrid";
import ProgressRing from "@/components/ui/ProgressRing";

/** Same single-student identity the study room tracks sessions under. */
const STUDENT_ID = "student-primary";

type Lang = { zh: string; en: string };

type DashKey =
  | "chat_history"
  | "notebooks"
  | "question_bank"
  | "personas"
  | "skills"
  | "mcp"
  | "cli_apps"
  | "mastery_path";

interface DashboardItem {
  key: DashKey;
  href: string;
  icon: LucideIcon;
  title: Lang;
  blurb: Lang;
  unit: Lang;
  tile: string;
  spanClass: string;
  tier: 1 | 2;
  load: () => Promise<number>;
}

const DASHBOARD_ITEMS: DashboardItem[] = [
  {
    key: "mastery_path",
    href: "/space/learning",
    icon: GraduationCap,
    title: { zh: "精通之路", en: "Mastery Path" },
    blurb: {
      zh: "掌握式学习：硬门槛与间隔复习。",
      en: "Mastery-based learning: hard gate and spaced review.",
    },
    unit: { zh: "条路径", en: "paths" },
    tile: "bg-[var(--primary)]/10 text-[var(--primary)]",
    spanClass: "col-span-1 md:col-span-6 lg:col-span-8",
    tier: 2,
    load: async () =>
      (await fetchAllProgress()).summaries.filter((s) => s.kp_count > 0).length,
  },
  {
    key: "chat_history",
    href: "/space/chat-history",
    icon: History,
    title: { zh: "聊天历史", en: "Chat History" },
    blurb: {
      zh: "回顾并继续此前的对话。",
      en: "Review and reopen previous conversations.",
    },
    unit: { zh: "段对话", en: "conversations" },
    tile: "bg-[var(--accent)] text-[var(--primary)]",
    spanClass: "col-span-1 md:col-span-3 lg:col-span-4",
    tier: 1,
    load: async () => (await listSessions(200, 0, { force: true })).length,
  },
  {
    key: "notebooks",
    href: "/space/notebooks",
    icon: NotebookPen,
    title: { zh: "笔记本", en: "Notebooks" },
    blurb: {
      zh: "整理来自对话、研究等产出。",
      en: "Organize saved outputs from chat and research.",
    },
    unit: { zh: "个笔记本", en: "notebooks" },
    tile: "bg-amber-500/10 text-amber-500",
    spanClass: "col-span-1 md:col-span-3 lg:col-span-4",
    tier: 1,
    load: async () => (await listNotebooks()).length,
  },
  {
    key: "question_bank",
    href: "/space/questions",
    icon: ClipboardList,
    title: { zh: "题库", en: "Question Bank" },
    blurb: {
      zh: "跨会话回顾和整理测验题目。",
      en: "Review and organize quiz questions across sessions.",
    },
    unit: { zh: "道题", en: "questions" },
    tile: "bg-emerald-500/10 text-emerald-500",
    spanClass: "col-span-1 md:col-span-3 lg:col-span-4",
    tier: 1,
    load: async () => (await listNotebookEntries({ limit: 1 })).total,
  },
  {
    key: "personas",
    href: "/space/personas",
    icon: UserRound,
    title: { zh: "Personas", en: "Personas" },
    blurb: {
      zh: "行为预设。",
      en: "Behavior presets per chat turn.",
    },
    unit: { zh: "个预设", en: "personas" },
    tile: "bg-rose-500/10 text-rose-500",
    spanClass: "col-span-1 md:col-span-2 lg:col-span-4",
    tier: 1,
    load: async () => (await listPersonas()).length,
  },
  {
    key: "skills",
    href: "/space/skills",
    icon: Wand2,
    title: { zh: "技能", en: "Skills" },
    blurb: {
      zh: "能力手册。",
      en: "Capability playbooks.",
    },
    unit: { zh: "个技能", en: "skills" },
    tile: "bg-[var(--accent)] text-[var(--primary)]",
    spanClass: "col-span-1 md:col-span-2 lg:col-span-4",
    tier: 1,
    load: async () => (await listSkills()).length,
  },
  {
    key: "mcp",
    href: "/space/mcp",
    icon: Plug,
    title: { zh: "MCP 服务", en: "MCP Services" },
    blurb: {
      zh: "连接托管 MCP 服务。",
      en: "Connect hosted MCP services.",
    },
    unit: { zh: "个服务", en: "services" },
    tile: "bg-[var(--primary)]/10 text-[var(--primary)]",
    spanClass: "col-span-1 md:col-span-2 lg:col-span-4",
    tier: 1,
    load: async () =>
      Object.keys((await loadMcpSurface(SPACE_MCP_SURFACE)).servers).length,
  },
  {
    key: "cli_apps",
    href: "/space/cli-apps",
    icon: Terminal,
    title: { zh: "CLI 应用", en: "CLI Apps" },
    blurb: {
      zh: "命令行工具，对话可调用。",
      en: "CLI tools callable from chat.",
    },
    unit: { zh: "个应用", en: "apps" },
    tile: "bg-[var(--accent)] text-[var(--primary)]",
    spanClass: "col-span-1 md:col-span-2 lg:col-span-4",
    tier: 1,
    load: async () =>
      (await getCliApps()).apps.filter((app) => app.granted && app.enabled).length,
  },
];

export default function SpaceDashboard() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const [counts, setCounts] = useState<Partial<Record<DashKey, number>>>({});
  const [failedKeys, setFailedKeys] = useState<Partial<Record<DashKey, boolean>>>({});
  const [masteryProgress, setMasteryProgress] = useState<number | null>(null);
  const [masteryFailed, setMasteryFailed] = useState(false);
  // Real study stats (streak from the gamification profile, hours from the
  // session history). null = still loading; undefined sentinel via `statsFailed`.
  const [studyStreak, setStudyStreak] = useState<number | null>(null);
  const [studyHours, setStudyHours] = useState<number | null>(null);
  const [statsFailed, setStatsFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    for (const item of DASHBOARD_ITEMS) {
      item
        .load()
        .then((n) => {
          if (!cancelled) setCounts((prev) => ({ ...prev, [item.key]: n }));
        })
        .catch(() => {
          if (!cancelled) {
            // Honest failure: render "—" instead of an eternal skeleton.
            setFailedKeys((prev) => ({ ...prev, [item.key]: true }));
          }
        });
    }

    // Fetch mastery progress score specifically for the mastery_path tile
    fetchAllProgress().then((data) => {
      if (cancelled) return;
      const valid = data.summaries.filter((s) => s.kp_count > 0);
      const avg =
        valid.length > 0
          ? valid.reduce((acc, s) => acc + s.avg_mastery_pct, 0) / valid.length
          : 0;
      setMasteryProgress(avg);
    }).catch(() => {
      if (!cancelled) setMasteryFailed(true);
    });

    // Real streak + total study time (was previously hardcoded demo numbers).
    (async () => {
      try {
        const profileRes = await fetch(
          apiUrl(`/api/v1/study-session/gamification/${STUDENT_ID}/profile`)
        );
        if (!profileRes.ok) throw new Error(String(profileRes.status));
        const profile = await profileRes.json();
        if (cancelled) return;
        setStudyStreak(typeof profile.streak === "number" ? profile.streak : 0);

        const historyRes = await fetch(
          apiUrl(`/api/v1/study-session/history/${STUDENT_ID}?limit=200&offset=0`)
        );
        if (!historyRes.ok) throw new Error(String(historyRes.status));
        const history = await historyRes.json();
        if (cancelled) return;
        const items: Array<{ actual_duration_seconds?: number }> = Array.isArray(history?.items)
          ? history.items
          : [];
        const totalSeconds = items.reduce(
          (acc, row) => acc + (typeof row.actual_duration_seconds === "number" ? row.actual_duration_seconds : 0),
          0
        );
        setStudyHours(Math.round((totalSeconds / 3600) * 10) / 10);
      } catch {
        if (!cancelled) setStatsFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="max-w-7xl mx-auto w-full">
      <header className="mb-10 px-2">
        <h1 className="font-display text-4xl font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "学习空间", en: "Learning Space" })}
        </h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-[var(--muted-foreground)]">
          {tr({
            zh: "你的对话、智能体、笔记与练习，集中在一处 —— 从这里进入。",
            en: "Your conversations, agents, notebooks, and practice in one place — enter from here.",
          })}
        </p>
      </header>

      <BentoGrid>
        {DASHBOARD_ITEMS.map((item) => (
          <BentoCard
            key={item.key}
            className={`group relative flex flex-col transition-all duration-300 hover:-translate-y-1 hover:shadow-lg ${item.spanClass}`}
            tier={item.tier}
          >
            <Link href={item.href} className="absolute inset-0 z-10 rounded-xl" />
            <div className="flex flex-col h-full z-20 pointer-events-none">
              <div className="flex items-start justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <span
                    aria-hidden
                    className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110 ${item.tile}`}
                  >
                    <item.icon size={22} strokeWidth={1.5} />
                  </span>
                  <div>
                    <h3 className="text-lg font-display font-medium leading-tight tracking-tight text-[var(--foreground)]">
                      {tr(item.title)}
                    </h3>
                    <div className="mt-1 flex items-baseline gap-1.5">
                      {counts[item.key] !== undefined ? (
                        <>
                          <span className="text-xl font-semibold leading-none tabular-nums text-[var(--foreground)]">
                            {counts[item.key]?.toLocaleString()}
                          </span>
                          <span className="text-sm text-[var(--muted-foreground)]">
                            {tr(item.unit)}
                          </span>
                        </>
                      ) : failedKeys[item.key] ? (
                        <span
                          className="text-xl font-semibold leading-none text-[var(--muted-foreground)]"
                          title={tr({ zh: "加载失败", en: "Couldn't load" })}
                        >
                          —
                        </span>
                      ) : (
                        <span className="my-[3px] h-4 w-12 animate-pulse rounded bg-[var(--glass-border)]" />
                      )}
                    </div>
                  </div>
                </div>
                <ArrowUpRight
                  size={20}
                  className="shrink-0 text-[var(--muted-foreground)]/40 transition-colors group-hover:text-[var(--primary)]"
                />
              </div>
              
              <p className="text-sm leading-relaxed text-[var(--muted-foreground)] mt-auto pr-8">
                {tr(item.blurb)}
              </p>

              {item.key === "mastery_path" && (
                <div className="mt-6 flex flex-col sm:flex-row items-center gap-6 p-4 rounded-xl bg-black/5 dark:bg-white/5 border border-[var(--glass-border)]">
                  <div className="shrink-0">
                    {masteryFailed ? (
                      <div
                        className="w-[100px] h-[100px] rounded-full border-8 border-[var(--glass-border)] flex items-center justify-center text-xl text-[var(--muted-foreground)]"
                        title={tr({ zh: "加载失败", en: "Couldn't load" })}
                      >
                        —
                      </div>
                    ) : masteryProgress !== null ? (
                      <ProgressRing
                        value={masteryProgress}
                        size={100}
                        strokeWidth={8}
                        label={tr({ zh: "掌握度", en: "Mastery" })}
                      />
                    ) : (
                      <div className="w-[100px] h-[100px] rounded-full border-8 border-[var(--glass-border)] animate-pulse" />
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-4 w-full">
                    <div className="flex flex-col gap-1 p-3 rounded-lg bg-[var(--canvas)]/50 backdrop-blur-sm">
                      <div className="flex items-center gap-1.5 text-orange-500">
                        <Flame size={16} />
                        <span className="text-xs font-semibold uppercase tracking-wider">{tr({ zh: "连续学习", en: "Streak" })}</span>
                      </div>
                      <span className="text-2xl font-bold font-display text-[var(--foreground)]">
                        {statsFailed || studyStreak === null ? "—" : studyStreak}
                        {!statsFailed && studyStreak !== null && (
                          <span className="text-sm font-body text-[var(--muted-foreground)] font-normal"> {tr({ zh: "天", en: "days" })}</span>
                        )}
                      </span>
                    </div>
                    <div className="flex flex-col gap-1 p-3 rounded-lg bg-[var(--canvas)]/50 backdrop-blur-sm">
                      <div className="flex items-center gap-1.5 text-[var(--primary)]">
                        <Clock size={16} />
                        <span className="text-xs font-semibold uppercase tracking-wider">{tr({ zh: "学习时长", en: "Time" })}</span>
                      </div>
                      <span className="text-2xl font-bold font-display text-[var(--foreground)]">
                        {statsFailed || studyHours === null ? "—" : studyHours}
                        {!statsFailed && studyHours !== null && (
                          <span className="text-sm font-body text-[var(--muted-foreground)] font-normal"> {tr({ zh: "小时", en: "hrs" })}</span>
                        )}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </BentoCard>
        ))}
      </BentoGrid>
    </div>
  );
}

