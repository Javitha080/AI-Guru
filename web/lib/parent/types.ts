/** Shared light-weight types for the Parent Portal UI. */

export interface StudentRow {
  student_id: string;
  name: string;
  status: "studying" | "offline";
  current_subject: string;
  today_study_time: number; // minutes
  focus_score: number | null; // null = never measured (renders as —)
  streak: number;
  xp: number;
  level: number;
  permissions?: Record<string, boolean>;
}

export interface IncidentItem {
  time: string;
  timestamp: number;
  session_id: string;
  event: string;
  message: string;
  severity: "info" | "warning" | "alert" | string;
  confidence: number;
  duration_seconds: number;
}

export interface TunnelSnapshot {
  status: string;
  url: string | null;
  provider?: string;
  url_is_public?: boolean;
  message?: string | null;
  restart_attempts?: number;
  local_port?: number;
  portal_hint?: string | null;
}

export interface VaultItem {
  clip_id: string;
  timestamp: number;
  event_type: string;
  session_id?: string;
}

export interface SessionSummaryRow {
  id: string;
  subject?: string;
  title?: string;
  status: string;
  start_time?: number;
  created_at?: number;
  actual_duration_seconds?: number;
  focus_score?: number | null;
}

export interface AuditEvent {
  id: string;
  timestamp: number;
  actor_id?: string;
  action: string;
  resource_type?: string;
  resource_id?: string;
  details?: Record<string, unknown>;
  ip_address?: string;
}
