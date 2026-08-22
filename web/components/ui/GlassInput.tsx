"use client";

import { forwardRef, useState, type InputHTMLAttributes } from "react";
import { motion } from "framer-motion";

interface GlassInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

const GlassInput = forwardRef<HTMLInputElement, GlassInputProps>(
  ({ label, error, className = "", onFocus, onBlur, ...props }, ref) => {
    const [focused, setFocused] = useState(false);

    return (
      <div className="relative">
        {label && (
          <motion.label
            className="absolute left-4 text-[var(--muted-foreground)] pointer-events-none origin-left"
            animate={{
              y: focused || props.value ? -24 : 0,
              scale: focused || props.value ? 0.85 : 1,
              color: focused ? "var(--primary)" : "var(--muted-foreground)",
            }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          >
            {label}
          </motion.label>
        )}
        <input
          ref={ref}
          className={`glass-input w-full font-body text-sm ${error ? "border-[var(--destructive)]" : ""} ${className}`}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
          {...props}
        />
        {error && (
          <p className="mt-1 text-xs text-[var(--destructive)]">{error}</p>
        )}
      </div>
    );
  }
);

GlassInput.displayName = "GlassInput";
export default GlassInput;
