"use client";

import { useEffect } from "react";

/**
 * Last-resort boundary. Replaces the root layout, so it must render its own
 * <html> and <body>.
 *
 * Because it stands in for the root layout, the app's stylesheet and theme
 * provider are not guaranteed to have loaded — everything here is inline and
 * self-contained, and the colours come from prefers-color-scheme directly
 * rather than from the theme tokens. If this screen ever renders, styling is
 * the least of the problems; it just must not be unreadable.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[root] fatal render failure", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: "24px",
          background: "#ffffff",
          color: "#18181b",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
        }}
      >
        <style>{`
          @media (prefers-color-scheme: dark) {
            body { background: #0b0b0e !important; color: #ededf2 !important; }
            .ge-card { background: #16161c !important; border-color: #2a2a33 !important; }
            .ge-pre { background: #101015 !important; color: #a8a8b8 !important; }
            .ge-muted { color: #8b8b9c !important; }
            .ge-btn { background: #16161c !important; color: #ededf2 !important; border-color: #34343f !important; }
          }
        `}</style>

        <main
          className="ge-card"
          style={{
            maxWidth: "560px",
            width: "100%",
            border: "1px solid #e4e4e7",
            borderRadius: "12px",
            padding: "28px",
            background: "#ffffff",
          }}
        >
          <h1
            style={{
              margin: "0 0 8px",
              fontSize: "17px",
              fontWeight: 600,
              letterSpacing: "-0.01em",
            }}
          >
            The dashboard failed to start
          </h1>
          <p
            className="ge-muted"
            style={{
              margin: "0 0 18px",
              fontSize: "13.5px",
              lineHeight: 1.55,
              color: "#71717a",
            }}
          >
            This is a failure in the application shell rather than in one page.
            Reloading usually clears it. If it persists, the API may be
            unreachable from the browser.
          </p>

          <pre
            className="ge-pre"
            style={{
              margin: "0 0 18px",
              padding: "12px",
              borderRadius: "8px",
              background: "#f4f4f5",
              color: "#52525b",
              fontFamily: "ui-monospace, Menlo, Consolas, monospace",
              fontSize: "11.5px",
              lineHeight: 1.6,
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {error.message || "Unknown error"}
            {error.digest ? `\n\ndigest: ${error.digest}` : ""}
          </pre>

          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button
              className="ge-btn"
              onClick={reset}
              style={{
                padding: "7px 14px",
                fontSize: "13px",
                fontWeight: 500,
                borderRadius: "7px",
                border: "1px solid #d4d4d8",
                background: "#ffffff",
                color: "#18181b",
                cursor: "pointer",
              }}
            >
              Try again
            </button>
            <button
              className="ge-btn"
              onClick={() => window.location.reload()}
              style={{
                padding: "7px 14px",
                fontSize: "13px",
                fontWeight: 500,
                borderRadius: "7px",
                border: "1px solid #d4d4d8",
                background: "#ffffff",
                color: "#18181b",
                cursor: "pointer",
              }}
            >
              Reload page
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
