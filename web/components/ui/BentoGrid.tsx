"use client";

import { type ElementType, type ReactNode } from "react";
import { useMagneticTilt } from "@/lib/motion/useGsapReveal";

/* Tailwind cannot see class names built by interpolation, so every span has
   to exist as a literal string somewhere in the source. These tables are
   that somewhere.

   The grid is 1 col on phones, 6 on tablets, 12 on desktop. Tablet spans are
   clamped to 6 so a `span={8}` card degrades to full width instead of
   overflowing its row. */
const COL_SPAN = {
  1: "md:col-span-1 lg:col-span-1",
  2: "md:col-span-2 lg:col-span-2",
  3: "md:col-span-3 lg:col-span-3",
  4: "md:col-span-3 lg:col-span-4",
  5: "md:col-span-4 lg:col-span-5",
  6: "md:col-span-6 lg:col-span-6",
  7: "md:col-span-6 lg:col-span-7",
  8: "md:col-span-6 lg:col-span-8",
  9: "md:col-span-6 lg:col-span-9",
  10: "md:col-span-6 lg:col-span-10",
  11: "md:col-span-6 lg:col-span-11",
  12: "md:col-span-6 lg:col-span-12",
} as const;

const ROW_SPAN = {
  1: "",
  2: "lg:row-span-2",
  3: "lg:row-span-3",
} as const;

const GAP = {
  sm: "gap-3",
  md: "gap-4",
  lg: "gap-6",
} as const;

export type BentoSpan = keyof typeof COL_SPAN;
export type BentoRowSpan = keyof typeof ROW_SPAN;

interface BentoGridProps {
  children: ReactNode;
  className?: string;
  /** Gutter between cells. Defaults to `md` (1rem), matching the old grid. */
  gap?: keyof typeof GAP;
  /**
   * Minimum row height on desktop. Row spans only read as a bento if rows
   * have a floor — otherwise a tall cell just stretches its neighbours.
   */
  minRow?: string;
  /** Semantic element. Use `"ul"` when the cells are a list of like items. */
  as?: ElementType;
}

export function BentoGrid({
  children,
  className = "",
  gap = "md",
  minRow = "8rem",
  as: Tag = "div",
}: BentoGridProps) {
  return (
    <Tag
      className={`grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 ${GAP[gap]} ${className}`}
      style={{ gridAutoRows: `minmax(${minRow}, auto)` }}
    >
      {children}
    </Tag>
  );
}

interface BentoCardProps extends React.HTMLAttributes<HTMLElement> {
  children: ReactNode;
  className?: string;
  /**
   * Surface tier:
   *   1        → base glass (unchanged default)
   *   2        → elevated glass with liquid sheen (unchanged)
   *   "liquid" → refractive liquid glass: gradient rim, thickness, and
   *              backdrop displacement on desktop
   */
  tier?: 1 | 2 | "liquid";
  /** Desktop column span out of 12. */
  span?: BentoSpan;
  /** Desktop row span. Pair with a `span` to build a 2x2 anchor cell. */
  rowSpan?: BentoRowSpan;
  /** Pointer-follow 3D tilt (skipped on touch and under reduced motion). */
  tilt?: boolean;
  /** Cursor-tracked specular highlight. Implied by `tilt`. */
  spotlight?: boolean;
  /** Hover elevation + keyboard focus ring. Use for cards that do something. */
  interactive?: boolean;
  /** Tag this cell for the scroll-reveal batch in useScrollReveal. */
  reveal?: boolean;
  /** Drop the default padding (for cards that own their own layout). */
  bare?: boolean;
  as?: ElementType;
  disabled?: boolean;
}

export function BentoCard({
  children,
  className = "",
  tier = 1,
  span,
  rowSpan,
  tilt = false,
  spotlight,
  interactive = false,
  reveal = false,
  bare = false,
  as: Tag = "div",
  ...rest
}: BentoCardProps) {
  /* Called unconditionally to keep hook order stable; the hook no-ops when
     its ref is never attached, on touch devices, and under reduced motion. */
  const tiltRef = useMagneticTilt<HTMLElement>(3);

  const showSpotlight = spotlight ?? tilt;

  const surface =
    tier === "liquid"
      ? [
          "liquid-glass",
          "liquid-glass--refract",
          showSpotlight && "liquid-glass--spotlight",
          interactive && "liquid-glass--interactive",
        ]
      : tier === 2
        ? ["surface-glass-elevated", "liquid-sheen", showSpotlight && "tilt-glare"]
        : ["surface-glass-base", showSpotlight && "tilt-glare"];

  const classes = [
    ...surface,
    span && COL_SPAN[span],
    rowSpan && ROW_SPAN[rowSpan],
    !bare && "p-5",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Tag
      ref={tilt ? tiltRef : undefined}
      className={classes}
      {...(reveal ? { "data-scroll-reveal": "" } : {})}
      {...rest}
    >
      {children}
    </Tag>
  );
}
