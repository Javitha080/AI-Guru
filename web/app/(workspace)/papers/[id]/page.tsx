"use client";

/**
 * AI Guru Paper Study page — one paper, full content, marking keys + AI tutor.
 * Reached from the Paper Bank hub ("Study Paper"); the Timed Exam CTA here
 * routes into the Study Room so timed sittings always run under supervision.
 */

import React from "react";
import { useParams, useRouter } from "next/navigation";
import PaperStudyModal from "@/components/papers/PaperStudyModal";

export default function PaperStudyPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const raw = params?.id;
  const bankPaperId = decodeURIComponent(Array.isArray(raw) ? raw[0] : raw ?? "");

  const goBack = React.useCallback(() => {
    router.push("/papers");
  }, [router]);

  const goTimed = React.useCallback(
    (paperId: string) => {
      router.push(`/study-room?bankPaperId=${encodeURIComponent(paperId)}&mode=timed`);
    },
    [router]
  );

  if (!bankPaperId) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center space-y-3">
          <p className="text-sm font-bold">Paper not found</p>
          <button
            onClick={goBack}
            className="px-4 py-2 rounded-xl surface-glass-base text-xs font-bold hover:text-[var(--primary)]"
          >
            Back to Paper Bank
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 h-full min-h-0 flex flex-col text-[var(--foreground)] bg-[var(--background)]">
      <PaperStudyModal bankPaperId={bankPaperId} onClose={goBack} onStartExam={goTimed} />
    </div>
  );
}
