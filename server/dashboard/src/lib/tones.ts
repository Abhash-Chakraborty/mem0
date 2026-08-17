/**
 * Semantic tones for badges, chips and status dots.
 *
 * One map, because the alternative is what the codebase had: every page
 * re-declaring its own `getStatusClassName` with slightly different greens.
 * Requests, memories, entities and webhooks all encode state visually, and
 * "succeeded" must look identical everywhere or the colour stops meaning
 * anything.
 *
 * Tones are named for what they mean, not what they look like. `violet` is the
 * exception: it is the accent, used for the neutral-but-notable case (a GET
 * ALL, a pattern memory) where none of good/warn/bad applies.
 */
export type Tone =
  | "neutral"
  | "violet"
  | "good"
  | "warn"
  | "bad"
  | "info"
  | "muted";

/** Filled chip / badge surface. */
export const TONE_BADGE: Record<Tone, string> = {
  neutral:
    "border-memBorder-primary bg-surface-default-secondary text-onSurface-default-secondary",
  violet:
    "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900/40 dark:bg-violet-950/40 dark:text-violet-300",
  good: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/40 dark:text-emerald-300",
  warn: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/40 dark:text-amber-300",
  bad: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-300",
  info: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/40 dark:bg-sky-950/40 dark:text-sky-300",
  muted:
    "border-memBorder-primary bg-transparent text-onSurface-default-tertiary",
};

/** Solid dot, for status indicators next to a label. */
export const TONE_DOT: Record<Tone, string> = {
  neutral: "bg-onSurface-default-tertiary",
  violet: "bg-violet-500",
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
  info: "bg-sky-500",
  muted: "bg-onSurface-default-tertiary/50",
};

/** Text-only, for inline emphasis where a chip would be too heavy. */
export const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-onSurface-default-secondary",
  violet: "text-violet-600 dark:text-violet-400",
  good: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-rose-600 dark:text-rose-400",
  info: "text-sky-600 dark:text-sky-400",
  muted: "text-onSurface-default-tertiary",
};

/** Map an HTTP status code to a tone. */
export function toneForStatus(status: number): Tone {
  if (status >= 500) return "bad";
  if (status >= 400) return "warn";
  return "good";
}
