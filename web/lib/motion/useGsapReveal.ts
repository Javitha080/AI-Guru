"use client";

/**
 * AI Guru — Ember Glass motion primitives (GSAP).
 *
 * Small, scoped hooks built on @gsap/react's useGSAP so every tween is
 * context-reverted on unmount. All motion is disabled (instant state) when
 * the OS reports prefers-reduced-motion, and tilt effects skip touch-only
 * devices via (hover: none).
 */

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(useGSAP);

// Re-export so pages can scope their own timelines to this module's setup.
export { useGSAP };

/** True when rich motion is allowed right now (client-side only). */
export function motionOK(): boolean {
  if (typeof window === "undefined") return false;
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Staggered entrance reveal for all `[data-reveal]` descendants of the
 * returned ref's subtree. Re-runs (after reverting) whenever `deps` change,
 * which keeps tab switches and list swaps animated without leaks.
 */
export function useRevealStagger<T extends HTMLElement = HTMLDivElement>(
  deps: unknown[] = [],
  opts?: { y?: number; stagger?: number; duration?: number }
) {
  const root = useRef<T | null>(null);
  useGSAP(
    () => {
      const el = root.current;
      if (!el || !motionOK()) return;
      const targets = el.querySelectorAll<HTMLElement>("[data-reveal]");
      if (!targets.length) return;
      gsap.fromTo(
        targets,
        { autoAlpha: 0, y: opts?.y ?? 22 },
        {
          autoAlpha: 1,
          y: 0,
          duration: opts?.duration ?? 0.65,
          ease: "power3.out",
          stagger: opts?.stagger ?? 0.06,
          clearProps: "transform,opacity,visibility",
        }
      );
    },
    { scope: root, dependencies: deps }
  );
  return root;
}

/**
 * Magnetic pointer-follow tilt with glare tracking. Writes --glare-x/y CSS
 * vars consumed by `.tilt-glare::after`. Elastic settle on leave.
 */
export function useMagneticTilt<T extends HTMLElement = HTMLDivElement>(maxDeg = 3) {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !motionOK()) return;
    if (window.matchMedia("(hover: none)").matches) return;

    let raf = 0;
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        gsap.to(el, {
          rotateY: px * maxDeg * 2,
          rotateX: -py * maxDeg * 2,
          transformPerspective: 900,
          transformOrigin: "center",
          duration: 0.5,
          ease: "power2.out",
        });
        el.style.setProperty("--glare-x", `${(px + 0.5) * 100}%`);
        el.style.setProperty("--glare-y", `${(py + 0.5) * 100}%`);
      });
    };
    const onLeave = () => {
      cancelAnimationFrame(raf);
      gsap.to(el, { rotateX: 0, rotateY: 0, duration: 0.8, ease: "elastic.out(1, 0.55)" });
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      cancelAnimationFrame(raf);
      gsap.killTweensOf(el);
      el.style.removeProperty("--glare-x");
      el.style.removeProperty("--glare-y");
    };
  }, [maxDeg]);

  return ref;
}

/**
 * Animated number readout. Renders "—" for null (honest empty state), tweens
 * between consecutive values otherwise. Attach the returned ref to a span.
 */
export function useCountUp(value: number | null, decimals = 0, suffix = "") {
  const ref = useRef<HTMLSpanElement | null>(null);
  const shown = useRef<number | null>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      if (value === null || !Number.isFinite(value)) {
        el.textContent = "—";
        shown.current = null;
        return;
      }
      if (!motionOK()) {
        el.textContent = `${value.toFixed(decimals)}${suffix}`;
        shown.current = value;
        return;
      }
      const from = shown.current ?? Math.max(0, value * 0.4);
      const obj = { v: from };
      gsap.to(obj, {
        v: value,
        duration: 0.9,
        ease: "power2.out",
        onUpdate: () => {
          el.textContent = `${obj.v.toFixed(decimals)}${suffix}`;
        },
      });
      shown.current = value;
    },
    { dependencies: [value, decimals, suffix] }
  );

  return ref;
}

/** One-shot shake — wrong PIN, failed action feedback. */
export function shakeEl(el: HTMLElement | null) {
  if (!el || !motionOK()) return;
  gsap.fromTo(
    el,
    { x: 0 },
    {
      x: 0,
      keyframes: [{ x: -9 }, { x: 8 }, { x: -6 }, { x: 4 }, { x: 0 }],
      duration: 0.45,
      ease: "power1.inOut",
    }
  );
}
