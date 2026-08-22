"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, HelpCircle, X } from "lucide-react";

/**
 * Maps raw technical error patterns to user-friendly messages.
 */
const ERROR_TRANSLATIONS: {
  pattern: RegExp;
  title: string;
  message: string;
  suggestion: string;
}[] = [
  {
    pattern: /ECONNREFUSED|ERR_CONNECTION_REFUSED|fetch failed/i,
    title: "Cannot Connect to Server",
    message:
      "The AI Guru backend service isn't responding. This usually means the server hasn't started yet.",
    suggestion: "Try running 'deeptutor start' in your terminal, then refresh.",
  },
  {
    pattern: /500|Internal Server Error/i,
    title: "Something Went Wrong",
    message:
      "The server encountered an unexpected error while processing your request.",
    suggestion: "This is usually temporary. Wait a moment and try again.",
  },
  {
    pattern: /404|Not Found/i,
    title: "Page Not Found",
    message: "The resource you're looking for doesn't exist or has moved.",
    suggestion: "Check the URL or navigate back to the home page.",
  },
  {
    pattern: /401|Unauthorized|403|Forbidden/i,
    title: "Access Denied",
    message: "You don't have permission to access this resource.",
    suggestion: "Try signing in again or contact your administrator.",
  },
  {
    pattern: /ENOENT|no such file/i,
    title: "File Not Found",
    message: "A required file or resource is missing from the system.",
    suggestion: "This may need a reinstallation. Check the setup guide.",
  },
  {
    pattern: /timeout|ETIMEDOUT|AbortError/i,
    title: "Request Timed Out",
    message:
      "The operation took too long to complete. The server might be busy.",
    suggestion: "Check your connection and try again.",
  },
  {
    pattern: /ERR_NETWORK|NetworkError|Failed to fetch/i,
    title: "Network Error",
    message: "Unable to reach the server. Check your network connection.",
    suggestion:
      "Make sure you're connected to the internet and the AI Guru server is running.",
  },
  {
    pattern: /CORS|cross-origin/i,
    title: "Configuration Error",
    message: "There's a cross-origin configuration issue.",
    suggestion:
      "This usually resolves after restarting the server. Run 'deeptutor start'.",
  },
];

interface FriendlyError {
  title: string;
  message: string;
  suggestion: string;
  originalError: string;
}

function translateError(error: string | Error): FriendlyError {
  const errorStr = typeof error === "string" ? error : error.message || String(error);

  for (const { pattern, title, message, suggestion } of ERROR_TRANSLATIONS) {
    if (pattern.test(errorStr)) {
      return { title, message, suggestion, originalError: errorStr };
    }
  }

  return {
    title: "Unexpected Error",
    message: "Something unexpected happened. Don't worry — your data is safe.",
    suggestion: "Try refreshing the page. If the problem persists, check the troubleshooting guide.",
    originalError: errorStr,
  };
}

interface FriendlyErrorModalProps {
  /** The raw error to display in a friendly way */
  error: string | Error | null;
  /** Called when the user dismisses the modal */
  onDismiss: () => void;
  /** Called when the user clicks Retry */
  onRetry?: () => void;
  /** Whether to show the modal */
  open?: boolean;
}

/**
 * Intercepts raw technical errors and displays a user-friendly modal
 * with clear messaging, retry options, and help links.
 *
 * Never shows raw error codes (ECONNREFUSED, 500, etc.) to users.
 *
 * @example
 * ```tsx
 * const [error, setError] = useState<Error | null>(null);
 *
 * <FriendlyErrorModal
 *   error={error}
 *   onDismiss={() => setError(null)}
 *   onRetry={() => { setError(null); retryAction(); }}
 * />
 * ```
 */
export function FriendlyErrorModal({
  error,
  onDismiss,
  onRetry,
  open,
}: FriendlyErrorModalProps) {
  const [showDetails, setShowDetails] = useState(false);
  const isOpen = open ?? error !== null;

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, onDismiss]);

  if (!isOpen || !error) return null;

  const friendly = translateError(error);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onDismiss}
      />

      {/* Modal */}
      <div className="relative mx-4 w-full max-w-md rounded-2xl bg-[var(--background)] p-6 shadow-2xl ring-1 ring-[var(--border)]/50">
        {/* Close button */}
        <button
          onClick={onDismiss}
          className="absolute right-4 top-4 rounded-lg p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          aria-label="Close"
        >
          <X size={16} />
        </button>

        {/* Icon */}
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/10">
          <AlertTriangle size={24} className="text-amber-500" />
        </div>

        {/* Title */}
        <h2 className="mb-2 text-lg font-semibold text-[var(--foreground)]">
          {friendly.title}
        </h2>

        {/* Message */}
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          {friendly.message}
        </p>

        {/* Suggestion */}
        <div className="mb-5 rounded-lg bg-[var(--accent)]/50 px-3 py-2.5">
          <div className="flex items-start gap-2">
            <HelpCircle
              size={14}
              className="mt-0.5 shrink-0 text-[var(--muted-foreground)]"
            />
            <p className="text-xs text-[var(--muted-foreground)]">
              {friendly.suggestion}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          {onRetry && (
            <button
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] transition-opacity hover:opacity-90"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          )}
          <button
            onClick={onDismiss}
            className="rounded-lg px-4 py-2 text-sm text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          >
            Dismiss
          </button>
          <button
            onClick={() => setShowDetails((v) => !v)}
            className="ml-auto text-xs text-[var(--muted-foreground)]/60 transition-colors hover:text-[var(--muted-foreground)]"
          >
            {showDetails ? "Hide details" : "Show details"}
          </button>
        </div>

        {/* Technical details (collapsed by default) */}
        {showDetails && (
          <pre className="mt-3 max-h-24 overflow-auto rounded-md bg-[var(--accent)]/30 p-2 text-[10px] text-[var(--muted-foreground)]/70">
            {friendly.originalError}
          </pre>
        )}
      </div>
    </div>
  );
}

/**
 * Hook to create a friendly error handler.
 *
 * @example
 * ```tsx
 * const { error, handleError, clearError, retry } = useFriendlyError();
 *
 * try { await fetchData(); }
 * catch (e) { handleError(e, () => fetchData()); }
 *
 * <FriendlyErrorModal error={error} onDismiss={clearError} onRetry={retry} />
 * ```
 */
export function useFriendlyError() {
  const [error, setError] = useState<Error | string | null>(null);
  const [retryFn, setRetryFn] = useState<(() => void) | null>(null);

  const handleError = useCallback(
    (err: unknown, retryAction?: () => void) => {
      const errorValue =
        err instanceof Error
          ? err
          : typeof err === "string"
            ? err
            : String(err);
      setError(errorValue);
      if (retryAction) {
        setRetryFn(() => retryAction);
      }
    },
    [],
  );

  const clearError = useCallback(() => {
    setError(null);
    setRetryFn(null);
  }, []);

  const retry = useCallback(() => {
    clearError();
    retryFn?.();
  }, [clearError, retryFn]);

  return { error, handleError, clearError, retry: retryFn ? retry : undefined };
}
