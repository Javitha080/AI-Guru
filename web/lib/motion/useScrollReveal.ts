"use client";

/**
 * AI Guru — scroll-driven motion primitives (GSAP ScrollTrigger).
 *
 * Companion to useGsapReveal.ts, which handles mount-time motion. Use these
 * when the animation should be tied to the user's scroll position instead.
 *
 * Two things make this app different from the usual ScrollTrigger setup:
 *
 *   1. The document never scrolls. The shell is `h-dvh overflow-hidden` and
 *      each route scrolls its own inner container, so every trigger has to be
 *      told which element is the scroller.
 *   2. Content is usually fetched, so reveals must be re-created after data
 *      lands — hence the `deps` array on every hook.
 */

import { useEffect, useRef, type RefObject } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { motionOK } from "./useGsapReveal";

gsap.registerPlugin(useGSAP, ScrollTrigger);

export { ScrollTrigger };

/** Marker attribute picked up by useScrollReveal. */
export const REVEAL_ATTR = "data-scroll-reveal";

interface ScrollRevealOptions {
  /** Override the target selector. Defaults to `[data-scroll-reveal]`. */
  selector?: string;
  /** Travel distance in px. */
  y?: number;
  /** Seconds between items inside one batch. */
  stagger?: number;
  duration?: number;
  /** ScrollTrigger `start`. Default fires just before the card is fully in. */
  start?: string;
  /** Reveal once and forget (default) or re-hide on scroll back out. */
  once?: boolean;
}

/**
 * Staggered scroll reveal for every `[data-scroll-reveal]` element inside the
 * returned ref's subtree.
 *
 * ```tsx
 * const scroller = useRef<HTMLDivElement>(null);
 * const root = useScrollReveal<HTMLDivElement>(scroller, [loading]);
 *
 * <div ref={scroller} className="overflow-y-auto">
 *   <div ref={root}>
 *     <BentoCard reveal>…</BentoCard>
 *   </div>
 * </div>
 * ```
 *
 * `ScrollTrigger.batch` is used rather than one trigger per card: it groups
 * elements that enter within the same window into a single tween, which keeps
 * the stagger looking intentional and avoids dozens of separate observers.
 */
export function useScrollReveal<T extends HTMLElement = HTMLDivElement>(
  scrollerRef?: RefObject<HTMLElement | null>,
  deps: unknown[] = [],
  opts: ScrollRevealOptions = {}
) {
  const {
    selector = `[${REVEAL_ATTR}]`,
    y = 26,
    stagger = 0.07,
    duration = 0.7,
    start = "top 92%",
    once = true,
  } = opts;

  const root = useRef<T | null>(null);

  useGSAP(
    () => {
      const el = root.current;
      if (!el) return;

      const targets = gsap.utils.toArray<HTMLElement>(el.querySelectorAll(selector));
      if (!targets.length) return;

      // Reduced motion resolves to the *visible* state, never the hidden one.
      if (!motionOK()) {
        gsap.set(targets, { autoAlpha: 1, y: 0, clearProps: "all" });
        return;
      }

      const scroller = scrollerRef?.current ?? undefined;

      // Nothing to scroll (short page, or the ref pointed at the wrong node):
      // fall back to a plain entrance so the content is never stuck hidden.
      const scrollable = scroller
        ? scroller.scrollHeight > scroller.clientHeight + 8
        : true;

      if (!scrollable) {
        gsap.fromTo(
          targets,
          { autoAlpha: 0, y },
          {
            autoAlpha: 1,
            y: 0,
            duration,
            stagger,
            ease: "power3.out",
            clearProps: "transform,opacity,visibility",
          }
        );
        return;
      }

      gsap.set(targets, { autoAlpha: 0, y });

      ScrollTrigger.batch(targets, {
        scroller,
        start,
        once,
        // Bigger batches read as one wave; smaller ones as popcorn.
        batchMax: 6,
        interval: 0.1,
        onEnter: (batch) =>
          gsap.to(batch, {
            autoAlpha: 1,
            y: 0,
            duration,
            stagger,
            ease: "power3.out",
            overwrite: true,
            clearProps: "transform",
          }),
      });

      // Measurements taken before fonts/images settle are wrong; one refresh
      // after creation re-reads them.
      ScrollTrigger.refresh();
    },
    { scope: root, dependencies: deps }
  );

  /* Failsafe. If a trigger never fires — wrong scroller, a container that
     only becomes scrollable later, an unexpected transform ancestor — the
     worst outcome is permanently invisible content. Anything still fully
     transparent shortly after setup gets shown unconditionally. */
  useEffect(() => {
    const id = window.setTimeout(() => {
      const el = root.current;
      if (!el) return;
      el.querySelectorAll<HTMLElement>(selector).forEach((node) => {
        if (window.getComputedStyle(node).opacity === "0") {
          gsap.set(node, { autoAlpha: 1, y: 0, clearProps: "all" });
        }
      });
    }, 1800);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selector, ...deps]);

  return root;
}

/**
 * Depth parallax for `[data-parallax]` descendants. Each element may carry
 * `data-parallax="<px>"` to override the shared distance; positive values
 * drift up as the user scrolls down.
 *
 * Transform-only and scrubbed, so it costs no layout and stays glued to the
 * scroll position instead of easing behind it.
 */
export function useScrollParallax<T extends HTMLElement = HTMLDivElement>(
  scrollerRef?: RefObject<HTMLElement | null>,
  deps: unknown[] = [],
  distance = 40
) {
  const root = useRef<T | null>(null);

  useGSAP(
    () => {
      const el = root.current;
      if (!el || !motionOK()) return;

      const targets = gsap.utils.toArray<HTMLElement>(el.querySelectorAll("[data-parallax]"));
      if (!targets.length) return;

      const scroller = scrollerRef?.current ?? undefined;

      targets.forEach((node) => {
        const own = Number.parseFloat(node.dataset.parallax ?? "");
        const travel = Number.isFinite(own) && own !== 0 ? own : distance;

        gsap.to(node, {
          y: -travel,
          ease: "none",
          scrollTrigger: {
            trigger: node,
            scroller,
            start: "top bottom",
            end: "bottom top",
            scrub: true,
          },
        });
      });
    },
    { scope: root, dependencies: deps }
  );

  return root;
}
