"use client";

import { useRef } from "react";
import GamificationDashboard from "@/components/gamification/GamificationDashboard";
import { useSmoothScroll } from "@/lib/motion/useSmoothScroll";

export default function AchievementsPage() {
  /* The scroll container lives here rather than inside the dashboard so both
     the smooth-scroll driver and the dashboard's ScrollTrigger reveals can be
     pointed at the same element. */
  const scrollerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useSmoothScroll(scrollerRef, contentRef);

  return (
    /* `h-full` matters: <main> is not a flex container, so `flex-1` alone left
       this div with an auto height and `overflow-y-auto` never engaged — tall
       content was simply clipped by the shell. */
    <div
      ref={scrollerRef}
      className="h-full flex-1 overflow-y-auto bg-[var(--background)]"
    >
      <div ref={contentRef}>
        <GamificationDashboard scrollerRef={scrollerRef} />
      </div>
    </div>
  );
}
