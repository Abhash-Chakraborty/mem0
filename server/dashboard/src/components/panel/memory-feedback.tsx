"use client";

import { useCallback, useEffect, useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/**
 * Was this memory any good?
 *
 * The quick reasons exist so the common complaints are countable — free text is
 * more expressive but nothing can aggregate it, and Dream needs a signal it can
 * count. Both are offered; neither is required.
 *
 * Submitting is append-only, matching the API: someone changing their mind is a
 * second verdict, and the history of what people thought is the actual signal.
 */

const REASONS: { id: string; label: string }[] = [
  { id: "no_strong_match", label: "Not what I searched for" },
  { id: "conflicting", label: "Contradicts another memory" },
  { id: "outdated", label: "Out of date" },
  { id: "wrong_entity", label: "Attached to the wrong person" },
  { id: "could_not_save", label: "Should not have been saved" },
];

interface FeedbackItem {
  id: string;
  rating: string;
  note: string | null;
  reasons: string[];
  created_at: string;
}

export function MemoryFeedback({ memoryId }: { memoryId: string }) {
  const [history, setHistory] = useState<FeedbackItem[]>([]);
  const [rating, setRating] = useState<"good" | "bad" | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<FeedbackItem[]>(
        MEMORY_ENDPOINTS.FEEDBACK(memoryId),
      );
      setHistory(res.data);
    } catch {
      // Feedback history is context. Losing it must not blank the panel.
      setHistory([]);
    }
  }, [memoryId]);

  useEffect(() => {
    setRating(null);
    setReasons([]);
    setNote("");
    void load();
  }, [memoryId, load]);

  const submit = async () => {
    if (!rating) return;
    setSaving(true);
    try {
      await api.post(MEMORY_ENDPOINTS.FEEDBACK(memoryId), {
        rating,
        note: note.trim() || undefined,
        reasons,
      });
      setRating(null);
      setReasons([]);
      setNote("");
      await load();
      toast.success("Thanks — recorded.");
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not save that feedback."));
    } finally {
      setSaving(false);
    }
  };

  const toggleReason = (id: string) =>
    setReasons((current) =>
      current.includes(id) ? current.filter((r) => r !== id) : [...current, id],
    );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Button
          variant={rating === "good" ? "default" : "outline"}
          size="sm"
          onClick={() => setRating(rating === "good" ? null : "good")}
        >
          <ThumbsUp className="mr-1.5 size-3.5" />
          Useful
        </Button>
        <Button
          variant={rating === "bad" ? "destructive" : "outline"}
          size="sm"
          onClick={() => setRating(rating === "bad" ? null : "bad")}
        >
          <ThumbsDown className="mr-1.5 size-3.5" />
          Not useful
        </Button>
      </div>

      {rating && (
        <>
          {rating === "bad" && (
            <div className="flex flex-wrap gap-1.5">
              {REASONS.map((reason) => (
                <button
                  key={reason.id}
                  type="button"
                  onClick={() => toggleReason(reason.id)}
                  aria-pressed={reasons.includes(reason.id)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs transition-colors",
                    reasons.includes(reason.id)
                      ? "border-transparent bg-surface-default-tertiary text-onSurface-default-primary"
                      : "border-memBorder-primary text-onSurface-default-tertiary hover:text-onSurface-default-primary",
                  )}
                >
                  {reason.label}
                </button>
              ))}
            </div>
          )}
          <Textarea
            rows={2}
            value={note}
            placeholder="Anything else worth recording? (optional)"
            onChange={(e) => setNote(e.target.value)}
          />
          <div>
            <Button size="sm" onClick={submit} disabled={saving}>
              {saving ? "Saving…" : "Submit"}
            </Button>
          </div>
        </>
      )}

      {history.length > 0 && (
        <div className="flex flex-col gap-1.5 border-t border-memBorder-primary pt-2">
          {history.map((item) => (
            <div
              key={item.id}
              className="text-xs text-onSurface-default-tertiary"
            >
              <span
                className={cn(
                  "font-medium",
                  item.rating === "good"
                    ? "text-onSurface-default-secondary"
                    : "text-onSurface-danger-primary",
                )}
              >
                {item.rating === "good" ? "Useful" : "Not useful"}
              </span>
              {item.reasons.length > 0 && (
                <span>
                  {" — "}
                  {item.reasons
                    .map((r) => REASONS.find((x) => x.id === r)?.label ?? r)
                    .join(", ")}
                </span>
              )}
              {item.note && <span> — “{item.note}”</span>}
              <span className="ml-1 opacity-70">
                {new Date(item.created_at).toLocaleDateString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
