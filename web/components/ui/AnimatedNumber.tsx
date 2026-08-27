"use client";

import React from "react";

export interface AnimatedNumberProps {
  /** The value (string or number) to display, e.g. "123", "04:59", "98%". */
  value: string | number;
  className?: string;
  digitClassName?: string;
  /** Re-animate changed digits whenever value changes. Default true. */
  animateOnChange?: boolean;
}

/**
 * Animated number pop-in (Transitions.dev)
 * Animates only the specific characters that changed by keying on index+character,
 * keeping colons, periods, and stable digits rock-solid without tearing down the DOM container.
 */
export default function AnimatedNumber({
  value,
  className = "",
  digitClassName = "",
  animateOnChange = true,
}: AnimatedNumberProps) {
  const stringVal = String(value);

  return (
    <span className={`t-digit-group ${className}`}>
      {stringVal.split("").map((ch, i) => {
        const isSymbol = ch === ":" || ch === "." || ch === "%";
        const key = animateOnChange && !isSymbol ? `${i}-${ch}` : `${i}`;
        const isAnim = animateOnChange && !isSymbol;
        return (
          <span
            key={key}
            className={`t-digit ${isAnim ? "is-changed" : ""} ${digitClassName}`}
            data-stagger={i > 0 && i <= 5 ? i : undefined}
          >
            {ch}
          </span>
        );
      })}
    </span>
  );
}

