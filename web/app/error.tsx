"use client";

import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[route-error]", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center p-6">
      <div className="max-w-md text-center">
        <h2 className="text-lg font-semibold">This section failed to load</h2>
        <p className="mt-2 text-sm opacity-70">
          Nothing was lost. Try again, or go back and continue studying.
          {error?.digest ? ` (ref ${error.digest})` : ""}
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <button
            onClick={reset}
            className="rounded-lg border px-4 py-2 text-sm"
          >
            Try again
          </button>
          <button
            onClick={() => window.history.back()}
            className="rounded-lg border px-4 py-2 text-sm opacity-70"
          >
            Go back
          </button>
        </div>
      </div>
    </div>
  );
}
