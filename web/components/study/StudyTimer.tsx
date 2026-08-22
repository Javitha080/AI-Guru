"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";

interface StudyTimerProps {
  durationMinutes: number;
  isActive: boolean;
  onComplete: () => void;
  onPauseToggle: (isPaused: boolean) => void;
}

export default function StudyTimer({ durationMinutes, isActive, onComplete, onPauseToggle }: StudyTimerProps) {
  const [timeLeft, setTimeLeft] = useState(durationMinutes * 60);
  const [isPaused, setIsPaused] = useState(false);
  
  const totalSeconds = durationMinutes * 60;
  const progress = timeLeft / totalSeconds;
  
  const requestRef = useRef<number>(undefined);
  const previousTimeRef = useRef<number>(undefined);

  useEffect(() => {
    if (!isActive || isPaused) {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      return;
    }

    const animate = (time: number) => {
      if (previousTimeRef.current != undefined) {
        const deltaTime = (time - previousTimeRef.current) / 1000;
        setTimeLeft((prev) => {
          const next = prev - deltaTime;
          if (next <= 0) {
            onComplete();
            return 0;
          }
          return next;
        });
      }
      previousTimeRef.current = time;
      requestRef.current = requestAnimationFrame(animate);
    };

    requestRef.current = requestAnimationFrame(animate);
    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [isActive, isPaused, onComplete]);

  const togglePause = () => {
    const newPausedState = !isPaused;
    setIsPaused(newPausedState);
    if (!newPausedState) {
      previousTimeRef.current = undefined; // Reset timing ref on unpause
    }
    onPauseToggle(newPausedState);
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  let color = "text-green-500 stroke-green-500";
  if (progress < 0.1) color = "text-red-500 stroke-red-500";
  else if (progress < 0.25) color = "text-yellow-500 stroke-yellow-500";

  return (
    <div className="flex flex-col items-center justify-center">
      <div className="relative w-64 h-64 flex items-center justify-center">
        <svg className="absolute inset-0 w-full h-full -rotate-90">
          <circle
            cx="128"
            cy="128"
            r="120"
            fill="none"
            stroke="var(--secondary)"
            strokeWidth="12"
          />
          <circle
            cx="128"
            cy="128"
            r="120"
            fill="none"
            className={color.split(" ")[1]}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={2 * Math.PI * 120}
            strokeDashoffset={2 * Math.PI * 120 * (1 - progress)}
            style={{ transition: "stroke-dashoffset 0.1s linear" }}
          />
        </svg>
        <div className={`text-5xl font-bold ${color.split(" ")[0]} tabular-nums z-10`}>
          {formatTime(timeLeft)}
        </div>
      </div>
      
      <button
        onClick={togglePause}
        className="mt-8 flex items-center gap-2 px-6 py-3 rounded-full bg-[var(--secondary)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] text-[var(--muted-foreground)] transition-colors"
      >
        {isPaused ? <Play size={20} fill="currentColor" /> : <Pause size={20} fill="currentColor" />}
        <span className="font-medium text-lg">{isPaused ? "Resume" : "Pause"}</span>
      </button>
    </div>
  );
}
