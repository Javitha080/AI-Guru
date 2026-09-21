import { apiFetch, apiUrl } from "@/lib/api";

export interface UserProfile {
  student_id: string;
  user_id: string;
  display_name: string;
  username: string;
  avatar: string;
  role: string;
  grade_level: string;
  learning_style: string;
  target_daily_minutes: number;
  school: string;
  preferred_subjects: string[];
  tutor_tone: string;
  is_configured: boolean;
  xp: number;
  level: number;
  level_title: string;
  streak: number;
  total_sessions: number;
}

export interface UserProfileUpdate {
  display_name?: string;
  avatar?: string;
  grade_level?: string;
  learning_style?: string;
  target_daily_minutes?: number;
  school?: string;
  preferred_subjects?: string[];
  tutor_tone?: string;
}

export interface UserProfileStatus {
  is_configured: boolean;
  display_name: string;
  avatar: string;
}

export const PROFILE_UPDATED_EVENT = "aiguru:profile-updated";

export function notifyProfileUpdated(profile?: UserProfile): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent(PROFILE_UPDATED_EVENT, { detail: profile }),
    );
  }
}

export async function getUserProfile(): Promise<UserProfile> {
  const res = await apiFetch(apiUrl("/api/v1/user/profile"));
  if (!res.ok) {
    throw new Error("Failed to fetch user profile");
  }
  return res.json();
}

export async function updateUserProfile(
  data: UserProfileUpdate,
): Promise<UserProfile> {
  const res = await apiFetch(apiUrl("/api/v1/user/profile"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(extractProfileDetail(errorData));
  }
  const updated: UserProfile = await res.json();
  notifyProfileUpdated(updated);
  return updated;
}

function extractProfileDetail(data: unknown): string {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
    // FastAPI 422 validation errors arrive as an array of {msg,...} objects.
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (typeof first === "object" && first !== null && "msg" in first) {
        return String((first as { msg: unknown }).msg);
      }
    }
  }
  return "Failed to update profile";
}

export async function getUserProfileStatus(): Promise<UserProfileStatus> {
  try {
    const res = await apiFetch(apiUrl("/api/v1/user/profile/status"));
    if (!res.ok) {
      return { is_configured: false, display_name: "", avatar: "" };
    }
    return res.json();
  } catch {
    return { is_configured: false, display_name: "", avatar: "" };
  }
}

export const GRADE_LEVEL_OPTIONS = [
  "Grade 10 (O/L)",
  "Grade 11 (O/L)",
  "Grade 12 (A/L)",
  "Grade 13 (A/L)",
  "Undergraduate",
  "Self-Learner",
] as const;

export const LEARNING_STYLE_OPTIONS = [
  {
    id: "visual",
    title: "Visual & Intuitive",
    description:
      "Learn through mental models, interactive diagrams, and visual metaphors.",
  },
  {
    id: "step_by_step",
    title: "Step-by-Step & Structured",
    description:
      "Clear formulas, methodical proofs, and structured numbered breakdowns.",
  },
  {
    id: "socratic",
    title: "Socratic & Inquisitive",
    description:
      "Guided inquiry with thought-provoking hints that lead you to discover answers.",
  },
  {
    id: "practical",
    title: "Exam & Practical Focus",
    description:
      "Marking scheme tactics, concise syllabus facts, and high-yield scoring tips.",
  },
] as const;

export const DAILY_GOAL_OPTIONS = [30, 45, 60, 90, 120] as const;

export const FOCUS_SUBJECT_OPTIONS = [
  "Mathematics",
  "Physics",
  "Chemistry",
  "Biology",
  "ICT / Computer Science",
  "Economics",
  "English",
  "Accounting",
  "Combined Maths",
] as const;

export const TUTOR_TONE_OPTIONS = [
  {
    id: "encouraging",
    title: "Encouraging & Patient",
    description: "Warm, inspiring, and builds deep learning confidence.",
  },
  {
    id: "rigorous",
    title: "Rigorous Exam Coach",
    description: "High standard, precise grading, and pushes for academic mastery.",
  },
  {
    id: "friendly",
    title: "Friendly Study Buddy",
    description: "Casual, relatable, and keeps studying engaging and fun.",
  },
  {
    id: "socratic",
    title: "Socratic Scholar",
    description: "Asks reflective questions to stimulate critical analytical thinking.",
  },
] as const;
