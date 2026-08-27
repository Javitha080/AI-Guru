import React, { useMemo } from "react";

export interface StreamingTextProps {
  /** The full or streaming text to display. */
  text: string;
  className?: string;
  wordClassName?: string;
  /** Whether the text is currently actively streaming. */
  isStreaming?: boolean;
}

/**
 * Streaming text with smooth word-by-word reveal (Transitions.dev)
 */
export default function StreamingText({
  text,
  className = "",
  wordClassName = "",
  isStreaming = false,
}: StreamingTextProps) {
  const words = useMemo(() => {
    if (!text) return [];
    return text.split(/(\s+)/);
  }, [text]);

  if (!text) return null;

  return (
    <span className={`inline ${className}`}>
      {words.map((chunk, index) => {
        const isWhitespace = /^\s+$/.test(chunk);
        if (isWhitespace) {
          return chunk;
        }
        return (
          <span
            key={index}
            className={`t-stream-w is-in ${wordClassName}`}
          >
            {chunk}
          </span>
        );
      })}
    </span>
  );
}
