"use client";

import React from "react";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  label?: string;
}

interface State {
  failed: boolean;
  message: string;
}

/** Reusable crash boundary for floating chat, study-room, exam, parent widgets. */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { failed: false, message: "" };

  static getDerivedStateFromError(err: unknown): State {
    return {
      failed: true,
      message: err instanceof Error ? err.message : String(err ?? ""),
    };
  }

  componentDidCatch(err: unknown): void {
    console.error(`[boundary:${this.props.label ?? "ui"}]`, err);
  }

  render(): React.ReactNode {
    if (!this.state.failed) return this.props.children;
    if (this.props.fallback) return this.props.fallback;
    return (
      <div className="rounded-xl border p-4 text-sm" role="alert">
        <p className="font-medium">This panel crashed, the rest of the app is fine.</p>
        <p className="mt-1 opacity-70">Try reopening it. No data was deleted.</p>
        <button
          className="mt-3 rounded-lg border px-3 py-1.5"
          onClick={() => this.setState({ failed: false, message: "" })}
        >
          Retry
        </button>
      </div>
    );
  }
}
