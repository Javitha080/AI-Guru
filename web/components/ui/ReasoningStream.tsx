"use client";

import React, { useEffect, useRef, useState } from "react";

export interface ReasoningStreamProps {
  /** The streaming lines/paragraphs of reasoning. */
  text: string;
  className?: string;
  maxHeight?: number;
}

/**
 * Reasoning Stream Ticker (Transitions.dev)
 * Displays rolling thought transcripts with top/bottom fade masks and smooth scrolling.
 */
export default function ReasoningStream({
  text,
  className = "",
  maxHeight = 120,
}: ReasoningStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const scrollHeight = el.scrollHeight;
    const clientHeight = maxHeight;
    if (scrollHeight > clientHeight) {
      setOffset(scrollHeight - clientHeight);
    } else {
      setOffset(0);
    }
  }, [text, maxHeight]);

  return (
    <div
      className={`t-reason relative w-full ${className}`}
      style={{ height: `${maxHeight}px` }}
    >
      <div className="t-reason-viewport">
        <div
          ref={scrollRef}
          className="t-reason-scroll text-xs leading-relaxed text-[var(--muted-foreground)] transition-transform duration-500 ease-out"
          style={{ transform: `translateY(-${offset}px)` }}
        >
          <div className="t-reason-text whitespace-pre-wrap py-2 font-mono text-[11px] opacity-90">
            {text || "AI Guru reasoning stream..."}
          </div>
        </div>
      </div>
    </div>
  );
}
