import {
  House,
  HeartHandshake,
  Bot,
  PenLine,
  Library,
  LayoutGrid,
  Brain,
  BookOpen,
  Timer,
  Trophy,
  Shield,
  Settings,
  type LucideIcon,
} from "lucide-react";
import type { Capability } from "@/lib/capability-routes";

export interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
  tooltipKey?: string;
  requires?: Capability;
}

/** Single source of truth for primary navigation (dock + command palette). */
export const DOCK_NAV: NavEntry[] = [
  { href: "/home", label: "Home", icon: House, tooltipKey: "Home tooltip", requires: "llm" },
  { href: "/study-room", label: "Study Room", icon: Timer, tooltipKey: "Study Room" },
  { href: "/achievements", label: "Achievements", icon: Trophy, tooltipKey: "Achievements" },
  { href: "/partners", label: "Partners", icon: HeartHandshake, tooltipKey: "Partners tooltip", requires: "llm" },
  { href: "/agents", label: "My Agents", icon: Bot, tooltipKey: "Agents tooltip" },
  { href: "/co-writer", label: "Co-Writer", icon: PenLine, tooltipKey: "Co-Writer tooltip", requires: "llm" },
  { href: "/book", label: "Book", icon: Library, tooltipKey: "Book tooltip", requires: "llm" },
  { href: "/space", label: "Learning Space", icon: LayoutGrid, tooltipKey: "Space tooltip" },
  { href: "/parent", label: "Parent Portal", icon: Shield, tooltipKey: "Parent Portal" },
  { href: "/memory", label: "Memory", icon: Brain, tooltipKey: "Memory tooltip" },
  { href: "/knowledge", label: "Knowledge Center", icon: BookOpen, tooltipKey: "Knowledge tooltip" },
  { href: "/settings", label: "Settings", icon: Settings },
];

/** How many destinations fit directly in the mobile tab bar before "More". */
export const MOBILE_PRIMARY_COUNT = 5;
