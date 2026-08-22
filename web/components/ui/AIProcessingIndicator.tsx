"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Search, Cog } from "lucide-react";

type ProcessingPhase = "idle" | "investigating" | "solving" | "streaming";

interface AIProcessingIndicatorProps {
  phase: ProcessingPhase;
  toolName?: string;
  className?: string;
}

/* ─── Phase 1: Ambient Readiness ─── */
function IdleOrb() {
  return (
    <div className="inline-flex items-center gap-2 glass-capsule px-3 py-1.5">
      <motion.div
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: "var(--primary)" }}
        animate={{
          scale: [1, 1.4, 1],
          opacity: [0.6, 1, 0.6],
          boxShadow: [
            "0 0 4px var(--glow-primary)",
            "0 0 12px var(--glow-primary)",
            "0 0 4px var(--glow-primary)",
          ],
        }}
        transition={{
          duration: 4,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      />
      <span className="text-xs font-body text-[var(--muted-foreground)]">Ready</span>
    </div>
  );
}

/* ─── Phase 2: Investigation & Reasoning Loop ─── */
function InvestigatingOrbs() {
  return (
    <div className="inline-flex items-center gap-2 glass-capsule px-3 py-1.5">
      <div className="relative w-5 h-5">
        {/* Glass ring container */}
        <div
          className="absolute inset-0 rounded-full"
          style={{
            border: "1.5px solid var(--glass-border)",
            background: "var(--glass-0)",
          }}
        />
        {/* Orbiting droplet 1 */}
        <motion.div
          className="absolute w-2 h-2 rounded-full"
          style={{
            background: "var(--primary)",
            boxShadow: "0 0 8px var(--glow-primary)",
            top: "50%",
            left: "50%",
          }}
          animate={{
            x: [0, 6, 0, -6, 0],
            y: [-6, 0, 6, 0, -6],
          }}
          transition={{
            duration: 1.8,
            repeat: Infinity,
            ease: "linear",
          }}
        />
        {/* Orbiting droplet 2 */}
        <motion.div
          className="absolute w-1.5 h-1.5 rounded-full"
          style={{
            background: "color-mix(in srgb, var(--primary) 60%, #DF8D6F)",
            boxShadow: "0 0 6px var(--glow-primary)",
            top: "50%",
            left: "50%",
          }}
          animate={{
            x: [0, -5, 0, 5, 0],
            y: [5, 0, -5, 0, 5],
          }}
          transition={{
            duration: 1.8,
            repeat: Infinity,
            ease: "linear",
          }}
        />
      </div>
      <motion.span
        className="text-xs font-body text-[var(--primary)]"
        animate={{ opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 1.5, repeat: Infinity }}
      >
        Investigating…
      </motion.span>
    </div>
  );
}

/* ─── Phase 3: Deep Solve & Logic Execution ─── */
function SolvingWaves({ toolName }: { toolName?: string }) {
  const bars = 5;
  return (
    <div className="inline-flex items-center gap-2">
      <div className="inline-flex items-center gap-2 glass-capsule px-3 py-1.5">
        {/* Wave visualizer bars */}
        <div className="flex items-center gap-0.5 h-4">
          {Array.from({ length: bars }).map((_, i) => (
            <motion.div
              key={i}
              className="w-[3px] rounded-full"
              style={{ background: "var(--primary)" }}
              animate={{
                height: [6, 14, 6],
                opacity: [0.5, 1, 0.5],
              }}
              transition={{
                duration: 1.2,
                repeat: Infinity,
                ease: "easeInOut",
                delay: i * 0.15,
              }}
            />
          ))}
        </div>
        <motion.span
          className="text-xs font-body text-[var(--primary)]"
          animate={{ opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        >
          Solving…
        </motion.span>
      </div>
      {/* Active tool pill */}
      <AnimatePresence>
        {toolName && (
          <motion.div
            initial={{ opacity: 0, x: -8, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 8, scale: 0.9 }}
            className="inline-flex items-center gap-1.5 glass-capsule px-2.5 py-1"
            style={{ boxShadow: "0 0 12px var(--glow-primary)" }}
          >
            {toolName.includes("search") || toolName.includes("rag") ? (
              <motion.div animate={{ rotate: 360 }} transition={{ duration: 2, repeat: Infinity, ease: "linear" }}>
                <Search size={11} className="text-[var(--primary)]" />
              </motion.div>
            ) : (
              <motion.div animate={{ rotate: 360 }} transition={{ duration: 3, repeat: Infinity, ease: "linear" }}>
                <Cog size={11} className="text-[var(--primary)]" />
              </motion.div>
            )}
            <span className="text-[10px] font-body text-[var(--muted-foreground)] max-w-[120px] truncate">
              {toolName}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ─── Phase 4: Synthesis & Output Streaming ─── */
function StreamingCursor() {
  return (
    <div className="inline-flex items-center gap-1.5">
      <motion.div
        className="w-[3px] h-4 rounded-full"
        style={{
          background: "var(--primary)",
          boxShadow: "0 0 8px var(--glow-primary)",
        }}
        animate={{
          opacity: [0.3, 1, 0.3],
          scaleY: [0.8, 1.1, 0.8],
        }}
        transition={{
          duration: 0.8,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      />
    </div>
  );
}

/* ─── Main Component ─── */
export default function AIProcessingIndicator({
  phase,
  toolName,
  className = "",
}: AIProcessingIndicatorProps) {
  return (
    <div className={`inline-flex ${className}`}>
      <AnimatePresence mode="wait">
        <motion.div
          key={phase}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.9 }}
          transition={{ duration: 0.2 }}
        >
          {phase === "idle" && <IdleOrb />}
          {phase === "investigating" && <InvestigatingOrbs />}
          {phase === "solving" && <SolvingWaves toolName={toolName} />}
          {phase === "streaming" && <StreamingCursor />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export type { ProcessingPhase, AIProcessingIndicatorProps };
