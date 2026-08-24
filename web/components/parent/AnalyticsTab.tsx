"use client";

/**
 * Analytics tab — per-student charts/sessions plus the session report drawer.
 */

import React, { useState } from "react";
import ParentAnalytics from "./ParentAnalytics";
import SessionReportDrawer from "./SessionReportDrawer";

interface AnalyticsTabProps {
  studentId: string | null;
}

export default function AnalyticsTab({ studentId }: AnalyticsTabProps) {
  const [reportSessionId, setReportSessionId] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      <ParentAnalytics studentId={studentId} onViewReport={(sid) => setReportSessionId(sid)} />
      <SessionReportDrawer sessionId={reportSessionId} onClose={() => setReportSessionId(null)} />
    </div>
  );
}
