"use client";

import React, { useState } from "react";
import GuruThinkingOrb, { type GuruOrbState, type GuruOrbSize } from "./GuruThinkingOrb";
import { Sparkles, Play, Pause, RefreshCw, Gauge } from "lucide-react";

const ALL_STATES: { state: GuruOrbState; name: string; desc: string }[] = [
  { state: "solving", name: "Solving", desc: "Bands scramble in quarter turns, then click back solved" },
  { state: "breathing", name: "Thinking / Breathing", desc: "A face-on ring slowly morphing and pulsating" },
  { state: "listening", name: "Listening", desc: "A waveform rolling through latitude rings" },
  { state: "working", name: "Working", desc: "Particles on tilted orbits" },
  { state: "searching", name: "Searching", desc: "A scan meridian sweeps a dotted globe" },
  { state: "connecting", name: "Connecting", desc: "A constellation wires itself, packets running edges" },
  { state: "weaving", name: "Weaving", desc: "Three strands plait around the sphere" },
  { state: "composing", name: "Composing", desc: "An undulating multi-band sash" },
  { state: "shaping", name: "Shaping", desc: "Dotted outline morphs circle → triangle → square" },
];

/**
 * Showcase component demonstrating all 9 Thinking Orb animations,
 * speed/size adjustments, and the 2x2 cards from the reference design.
 */
export default function ThinkingOrbsShowcase() {
  const [selectedState, setSelectedState] = useState<GuruOrbState>("solving");
  const [speed, setSpeed] = useState(1);
  const [size, setSize] = useState<GuruOrbSize>(64);
  const [isPaused, setIsPaused] = useState(false);
  const [shimmer, setShimmer] = useState(true);

  return (
    <div className="space-y-8 p-6">
      {/* Header */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-bold tracking-tight text-zinc-100">
            <Sparkles className="h-5 w-5 text-[#E06D44]" />
            AI Guru Thinking Orbs & Animation Suite
          </h2>
          <p className="text-xs text-zinc-400">
            Hand-tuned 2D canvas thought-orbs with Transitions.dev text shimmer & smooth streaming transitions.
          </p>
        </div>

        {/* Global Controls */}
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-zinc-800/80 bg-zinc-900/90 p-2 text-xs">
          <div className="flex items-center gap-2 px-2">
            <Gauge className="h-3.5 w-3.5 text-[#E06D44]" />
            <span className="text-zinc-400">Speed:</span>
            <input
              type="range"
              min="0.2"
              max="2.5"
              step="0.1"
              value={speed}
              onChange={(e) => setSpeed(parseFloat(e.target.value))}
              className="h-1.5 w-20 accent-[#E06D44]"
            />
            <span className="w-8 font-mono text-zinc-200">{speed.toFixed(1)}x</span>
          </div>

          <div className="h-4 w-px bg-zinc-700/60" />

          {/* Size switch */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setSize(64)}
              className={`rounded-lg px-2 py-1 font-mono text-xs transition ${
                size === 64
                  ? "bg-[#E06D44] font-bold text-white shadow-md shadow-[#E06D44]/30"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              64px
            </button>
            <button
              onClick={() => setSize(20)}
              className={`rounded-lg px-2 py-1 font-mono text-xs transition ${
                size === 20
                  ? "bg-[#E06D44] font-bold text-white shadow-md shadow-[#E06D44]/30"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              20px
            </button>
          </div>

          <div className="h-4 w-px bg-zinc-700/60" />

          {/* Play/Pause */}
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="flex items-center gap-1 rounded-lg bg-zinc-800 px-2.5 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            {isPaused ? <Play className="h-3 w-3 text-emerald-400" /> : <Pause className="h-3 w-3 text-amber-400" />}
            <span>{isPaused ? "Resume" : "Pause"}</span>
          </button>

          {/* Shimmer Toggle */}
          <button
            onClick={() => setShimmer(!shimmer)}
            className={`rounded-lg px-2.5 py-1 text-xs transition ${
              shimmer ? "bg-amber-500/20 text-amber-300 border border-amber-500/40" : "bg-zinc-800 text-zinc-400"
            }`}
          >
            Shimmer {shimmer ? "ON" : "OFF"}
          </button>
        </div>
      </div>

      {/* 2x2 Showcase Grid (Matching User's Reference Image Exactly) */}
      <div>
        <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Reference 2×2 Dashboard Cards
        </h3>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {/* Card 1: Solving */}
          <GuruThinkingOrb
            state="solving"
            label="Solving...."
            size={size}
            speed={speed}
            paused={isPaused}
            shimmer={shimmer}
            variant="card"
          />

          {/* Card 2: Thinking */}
          <GuruThinkingOrb
            state="breathing"
            label="Thinking...."
            size={size}
            speed={speed}
            paused={isPaused}
            shimmer={shimmer}
            variant="card"
          />

          {/* Card 3: Agent listening */}
          <GuruThinkingOrb
            state="listening"
            label="Agent listening..."
            size={size}
            speed={speed}
            paused={isPaused}
            shimmer={shimmer}
            variant="card"
          />

          {/* Card 4: Working */}
          <GuruThinkingOrb
            state="working"
            label="Working...."
            size={size}
            speed={speed}
            paused={isPaused}
            shimmer={shimmer}
            variant="card"
          />
        </div>
      </div>

      {/* All 9 States Gallery */}
      <div>
        <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          All 9 Hand-Tuned Agent States
        </h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ALL_STATES.map((item) => {
            const isSelected = selectedState === item.state;
            return (
              <div
                key={item.state}
                onClick={() => setSelectedState(item.state)}
                className={`group cursor-pointer rounded-2xl border p-4 transition-all duration-300 ${
                  isSelected
                    ? "border-[#E06D44]/60 bg-zinc-900 shadow-xl shadow-[#E06D44]/10"
                    : "border-zinc-800/80 bg-[#121316]/70 hover:border-zinc-700 hover:bg-[#15161a]"
                }`}
              >
                <div className="flex items-center justify-between pb-3">
                  <span className="font-semibold text-zinc-200 text-sm">{item.name}</span>
                  <span className="rounded bg-zinc-800/80 px-2 py-0.5 font-mono text-[10px] text-zinc-400">
                    {item.state}
                  </span>
                </div>
                <div className="flex items-center justify-center py-4">
                  <GuruThinkingOrb
                    state={item.state}
                    size={size}
                    speed={speed}
                    paused={isPaused}
                    shimmer={shimmer}
                    variant="pill"
                  />
                </div>
                <p className="pt-2 text-[11px] leading-relaxed text-zinc-400">
                  {item.desc}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
