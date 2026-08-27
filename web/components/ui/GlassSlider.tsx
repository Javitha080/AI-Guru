"use client";

import { useRef, useCallback, useState, useEffect } from "react";

interface GlassSliderProps {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
  label?: string;
  showValue?: boolean;
  disabled?: boolean;
}

export default function GlassSlider({
  value,
  min = 0,
  max = 100,
  step = 1,
  onChange,
  label,
  showValue = true,
  disabled = false,
}: GlassSliderProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const pct = ((value - min) / (max - min)) * 100;

  const updateValue = useCallback(
    (clientX: number) => {
      if (!trackRef.current || disabled) return;
      const rect = trackRef.current.getBoundingClientRect();
      const raw = (clientX - rect.left) / rect.width;
      const clamped = Math.max(0, Math.min(1, raw));
      const stepped = Math.round((clamped * (max - min)) / step) * step + min;
      onChange(stepped);
    },
    [min, max, step, onChange, disabled]
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => updateValue(e.clientX);
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, updateValue]);

  return (
    <div className={`flex flex-col gap-1.5 ${disabled ? "opacity-40" : ""}`}>
      {(label || showValue) && (
        <div className="flex items-center justify-between text-xs">
          {label && <span className="text-[var(--muted-foreground)] font-body font-medium">{label}</span>}
          {showValue && <span className="text-[var(--foreground)] font-body tabular-nums">{value}</span>}
        </div>
      )}
      <div
        ref={trackRef}
        className="relative h-2 rounded-full cursor-pointer"
        style={{
          background: "var(--glass-0)",
          backdropFilter: "blur(4px)",
          WebkitBackdropFilter: "blur(4px)",
          border: "1px solid var(--glass-border)",
          boxShadow: "inset 0 1px 3px rgba(0,0,0,0.08)",
        }}
        onMouseDown={(e) => {
          setDragging(true);
          updateValue(e.clientX);
        }}
      >
        {/* Illuminated track fill */}
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, var(--primary), color-mix(in srgb, var(--primary) 70%, #DF8D6F))",
            boxShadow: "0 0 8px var(--glow-primary)",
          }}
        />
        {/* Glass sphere thumb */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-5 h-5 rounded-full cursor-grab active:cursor-grabbing ${
            dragging ? "scale-125" : "hover:scale-110"
          }`}
          style={{
            left: `${pct}%`,
            background: "radial-gradient(circle at 40% 35%, rgba(255,255,255,0.9), var(--primary))",
            border: "2px solid rgba(255,255,255,0.6)",
            boxShadow: dragging
              ? "0 0 20px var(--glow-primary), 0 4px 12px rgba(0,0,0,0.25)"
              : "0 0 10px var(--glow-primary), 0 2px 6px rgba(0,0,0,0.15)",
            transition: dragging ? "none" : "transform var(--duration-fast, 250ms) var(--ease-smooth-out, cubic-bezier(0.22, 1, 0.36, 1)), box-shadow var(--duration-fast, 250ms) var(--ease-smooth-out, cubic-bezier(0.22, 1, 0.36, 1))",
          }}
        />
      </div>
    </div>
  );
}
