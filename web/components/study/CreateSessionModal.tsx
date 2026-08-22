"use client";

import { useState } from "react";
import { X } from "lucide-react";

interface CreateSessionModalProps {
  onClose: () => void;
  onStart: (title: string, subject: string, duration: number) => void;
}

const SUBJECTS = ["Math", "Science", "Language", "History", "Programming", "General"];
const DURATIONS = [15, 25, 30, 45, 60, 90];

export default function CreateSessionModal({ onClose, onStart }: CreateSessionModalProps) {
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("General");
  const [duration, setDuration] = useState(25);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    const finalTitle = title.trim() || `${subject} Study Session`;
    // Session creation happens once, in the page's pre-flight completion
    // handler (single source of truth — no double-create).
    onStart(finalTitle, subject, duration);
    setIsLoading(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl bg-[var(--background)] p-6 shadow-xl border border-[var(--border)]">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-[var(--foreground)]">New Study Session</h2>
          <button onClick={onClose} className="p-1 hover:bg-[var(--secondary)] rounded-md text-[var(--muted-foreground)]">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="E.g., Calculus Midterm Prep"
              required
              className="w-full rounded-md border border-[var(--border)] bg-[var(--secondary)] px-3 py-2 text-[var(--foreground)] outline-none focus:border-[var(--accent)]"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">Subject</label>
            <select
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--secondary)] px-3 py-2 text-[var(--foreground)] outline-none focus:border-[var(--accent)]"
            >
              {SUBJECTS.map((sub) => (
                <option key={sub} value={sub}>{sub}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-2">Duration (minutes)</label>
            <div className="grid grid-cols-3 gap-2">
              {DURATIONS.map((dur) => (
                <button
                  key={dur}
                  type="button"
                  onClick={() => setDuration(dur)}
                  className={`py-2 px-4 rounded-md border text-sm transition-colors ${
                    duration === dur
                      ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--foreground)] font-medium"
                      : "border-[var(--border)] bg-transparent text-[var(--muted-foreground)] hover:bg-[var(--secondary)]"
                  }`}
                >
                  {dur}
                </button>
              ))}
            </div>
          </div>

          <div className="pt-4 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-md text-[var(--muted-foreground)] hover:bg-[var(--secondary)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading || !title.trim()}
              className="px-4 py-2 rounded-md bg-[var(--accent)] text-[var(--foreground)] font-medium disabled:opacity-50"
            >
              {isLoading ? "Starting..." : "Start Session"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
