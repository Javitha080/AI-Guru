"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[global-error]", error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <div style={{ maxWidth: 480, textAlign: "center" }}>
            <h1 style={{ fontSize: 20, fontWeight: 700 }}>Something went wrong</h1>
            <p style={{ opacity: 0.7, margin: "12px 0 20px" }}>
              AI Guru hit an unexpected error. Your work is safe — try again.
              {error?.digest ? ` (ref ${error.digest})` : ""}
            </p>
            <button
              onClick={reset}
              style={{
                padding: "10px 18px",
                borderRadius: 10,
                border: "1px solid #ccc",
                cursor: "pointer",
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
