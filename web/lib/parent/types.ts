/** Shared light-weight types for the Parent Portal UI. */

export interface StudentRow {
  student_id: string;
  name: string;
  status: "studying" | "offline";
  current_subject: string;
  /** Concrete open study-session id (in_progress or paused), if any. */
  session_id?: string | null;
  /** Raw open-session status: in_progress | paused | null. */
  session_status?: string | null;
  /** True when the monitoring WebSocket is currently streaming. */
  monitoring_live?: boolean;
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

export interface OutboxSnapshot {
  pending: number;
  sending: number;
  dead: number;
  sent: number;
  total: number;
  overall_pending?: number;
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
  has_report?: boolean;
  report_reason?: string;
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
