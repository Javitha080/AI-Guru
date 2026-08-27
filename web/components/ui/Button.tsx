"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { motion } from "framer-motion";

import type { HTMLMotionProps } from "framer-motion";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: React.ReactNode;
  children: React.ReactNode;
}

const variantStyles = {
  primary: "glass-btn-primary text-white",
  secondary: "glass-btn-secondary text-[var(--foreground)]",
  danger: "bg-[var(--destructive)] text-[var(--destructive-foreground)] hover:opacity-90 shadow-md shadow-[var(--destructive)]/15",
  ghost: "glass-btn-ghost text-[var(--foreground)]",
};

const sizeStyles = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
  lg: "px-6 py-3 text-base",
};

export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  children,
  className = "",
  disabled,
  ...props
}: ButtonProps) {
  return (
    <motion.button
      whileHover={disabled || loading ? {} : { scale: 1.02, y: -1 }}
      whileTap={disabled || loading ? {} : { scale: 0.96, y: 0 }}
      transition={{ type: "spring", stiffness: 450, damping: 28 }}
      className={`
        inline-flex items-center justify-center gap-2 font-medium rounded-full transition-all
        disabled:opacity-50 disabled:cursor-not-allowed
        ${variantStyles[variant]}
        ${sizeStyles[size]}
        ${className}
      `}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : icon ? (
        icon
      ) : null}
      {children}
    </motion.button>
  );
}
