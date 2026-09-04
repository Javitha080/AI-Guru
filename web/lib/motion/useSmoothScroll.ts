"use client";

/**
 * Inertial smooth scrolling for a single scroll container.
 *
 * Why Lenis and not GSAP ScrollSmoother: the app shell is `h-dvh
 * overflow-hidden` and each route scrolls its own inner element, whereas
 * ScrollSmoother assumes it owns the page and wraps the whole document.
 * Lenis accepts an arbitrary `wrapper`, and because it animates real
 * `scrollTop` (rather than transforming a content wrapper), ScrollTrigger
 * stays in sync with nothing more than an `update` on its scroll event — no
 * `scrollerProxy` needed.
 *
 * Deliberately skipped in three cases:
 *   • prefers-reduced-motion — hijacked scroll is a vestibular trigger
 *   • coarse pointers — native touch momentum beats anything emulated
 *   • the hook being disabled by the caller (e.g. a virtualised list)
 *
 * Lenis loads via dynamic import so it never lands in the initial bundle.
 */

import { useEffect, type RefObject } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { motionOK } from "./useGsapReveal";

gsap.registerPlugin(ScrollTrigger);

interface LenisInstance {
  raf: (time: number) => void;
  on: (event: string, callback: () => void) => void;
  off: (event: string, callback: () => void) => void;
  destroy: () => void;
}

interface SmoothScrollOptions {
  /**
   * Interpolation factor per frame, 0–1. Lower is heavier. 0.1 lands around
   * the "premium but still responsive" mark; past ~0.05 the page feels
   * detached from the wheel.
   */
  lerp?: number;
  /** Set false to bail out (conditional routes, virtualised lists). */
  enabled?: boolean;
  /** Keep ScrollTrigger in step. Leave on unless nothing scroll-triggers. */
  syncScrollTrigger?: boolean;
}

/**
 * @param wrapperRef the element with `overflow-y: auto`
 * @param contentRef its single child wrapping all content (falls back to the
 *                   wrapper's first element child)
 */
export function useSmoothScroll(
  wrapperRef: RefObject<HTMLElement | null>,
  contentRef?: RefObject<HTMLElement | null>,
  options: SmoothScrollOptions = {}
) {
  const { lerp = 0.1, enabled = true, syncScrollTrigger = true } = options;

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!enabled || !wrapper) return;
    if (!motionOK()) return;
    if (window.matchMedia("(pointer: coarse)").matches) return;

    let disposed = false;
    let instance: LenisInstance | null = null;
    let tick: ((time: number) => void) | null = null;
    const onScroll = () => ScrollTrigger.update();

    void (async () => {
      // @ts-expect-error Lenis is loaded dynamically
      const lenisModule = await import("lenis").catch(() => null);
      if (!lenisModule || disposed || !wrapperRef.current) return;
      const LenisCtor = lenisModule.default || lenisModule;

      const content =
        contentRef?.current ??
        (wrapper.firstElementChild as HTMLElement | null) ??
        wrapper;

      instance = new LenisCtor({
        wrapper,
        content,
        lerp,
        smoothWheel: true,
        // Touch is excluded above, but be explicit: never emulate touch scroll.
        syncTouch: false,
        // The GSAP ticker drives the loop instead, so scroll and tweens share
        // one clock and cannot tear against each other.
        autoRaf: false,
      });


      if (syncScrollTrigger) instance!.on("scroll", onScroll);

      tick = (time: number) => {
        // GSAP ticker time is seconds; Lenis expects milliseconds.
        instance?.raf(time * 1000);
      };
      gsap.ticker.add(tick);

      // Default lag smoothing pauses the ticker after a long frame gap (tab
      // backgrounded, heavy render), which reads as scroll freezing on return.
      gsap.ticker.lagSmoothing(0);

      if (syncScrollTrigger) ScrollTrigger.refresh();
    })();

    return () => {
      disposed = true;
      if (tick) gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33); // restore GSAP's default
      if (instance) {
        instance.off("scroll", onScroll);
        instance.destroy();
        instance = null;
      }
    };
  }, [wrapperRef, contentRef, lerp, enabled, syncScrollTrigger]);
}
