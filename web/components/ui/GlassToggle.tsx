"use client";

import { motion } from "framer-motion";

interface GlassToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  size?: "sm" | "md";
  label?: string;
}

export default function GlassToggle({
  checked,
  onChange,
  disabled = false,
  size = "md",
  label,
}: GlassToggleProps) {
  const dims = size === "sm" ? { w: 40, h: 22, thumb: 16, travel: 18 } : { w: 48, h: 26, thumb: 20, travel: 22 };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className="relative inline-flex items-center rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 active:scale-[0.96]"
      style={{
        width: dims.w,
        height: dims.h,
        background: checked
          ? "color-mix(in srgb, var(--primary) 40%, transparent)"
          : "var(--glass-0)",
        border: `1px solid ${checked ? "var(--primary)" : "var(--glass-border)"}`,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        opacity: disabled ? 0.4 : 1,
        cursor: disabled ? "default" : "pointer",
        transition: "all var(--duration-fast, 250ms) var(--ease-smooth-out, cubic-bezier(0.22, 1, 0.36, 1))",
      }}
    >
      <motion.span
        className="absolute rounded-full shadow-md"
        style={{
          width: dims.thumb,
          height: dims.thumb,
          top: (dims.h - dims.thumb) / 2 - 1,
          background: checked
            ? "var(--primary)"
            : "var(--glass-border-highlight)",
          boxShadow: checked
            ? "0 0 12px var(--glow-primary), inset 0 1px 0 rgba(255,255,255,0.3)"
            : "inset 0 1px 0 rgba(255,255,255,0.5)",
        }}
        animate={{ x: checked ? dims.travel : 3 }}
        transition={{ type: "spring", stiffness: 550, damping: 26 }}
      />
    </button>
  );
}
