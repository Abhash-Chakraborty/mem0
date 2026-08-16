"use client";

import { useState } from "react";
import { History, Search, SlidersHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { api } from "@/utils/api";
import { RECALL_ENDPOINTS } from "@/utils/api-endpoints";
import {
  MemoryHistoryEntry,
  RecallResponse,
  RecallResult,
  ScoreDetails,
} from "@/types/api";
import { cn } from "@/lib/utils";

/** Each contribution to the final score, in the order the scorer applies them. */
const SCORE_PARTS: {
  key: keyof Pick<ScoreDetails, "semantic_score" | "bm25_score" | "entity_boost">;
  label: string;
  className: string;
}[] = [
  { key: "semantic_score", label: "Semantic", className: "bg-violet-500" },
  { key: "bm25_score", label: "Keyword", className: "bg-sky-500" },
  { key: "entity_boost", label: "Entity", className: "bg-emerald-500" },
];

function ScoreBar({ details }: { details: ScoreDetails }) {
  const max = details.max_possible_score || 1;
  return (
    <div className="mt-3">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-default-secondary">
        {SCORE_PARTS.map((part) => {
          const value = details[part.key] ?? 0;
          if (value <= 0) return null;
          return (
            <div
              key={part.key}
              className={part.className}
              style={{ width: `${Math.min((value / max) * 100, 100)}%` }}
              title={`${part.label}: ${value.toFixed(4)}`}
            />
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-onSurface-default-tertiary">
        {SCORE_PARTS.map((part) => (
          <span key={part.key} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", part.className)} aria-hidden />
            {part.label} {(details[part.key] ?? 0).toFixed(4)}
          </span>
        ))}
        <span className="tabular-nums">
          Raw {details.raw_score.toFixed(4)} / {max.toFixed(2)}
        </span>
        <span className="tabular-nums">
          Threshold {details.threshold.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

export default function RecallPage() {
  const [query, setQuery] = useState("");
  const [userId, setUserId] = useState("");
  const [topK, setTopK] = useState("10");
  const [threshold, setThreshold] = useState("");
  const [explain, setExplain] = useState(true);

  const [results, setResults] = useState<RecallResult[] | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [searching, setSearching] = useState(false);

  const [historyFor, setHistoryFor] = useState<RecallResult | null>(null);
  const [history, setHistory] = useState<MemoryHistoryEntry[] | null>(null);

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    const started = performance.now();
    try {
      const filters = userId.trim() ? { user_id: userId.trim() } : undefined;
      const body: Record<string, unknown> = { query: query.trim(), explain };
      if (filters) body.filters = filters;
      const parsedTopK = Number.parseInt(topK, 10);
      if (Number.isFinite(parsedTopK) && parsedTopK > 0) body.top_k = parsedTopK;
      const parsedThreshold = Number.parseFloat(threshold);
      if (Number.isFinite(parsedThreshold)) body.threshold = parsedThreshold;

      const res = await api.post<RecallResponse>(RECALL_ENDPOINTS.SEARCH, body);
      setElapsedMs(Math.round(performance.now() - started));
      // The API returns {results: [...]} but older builds returned a bare list.
      const payload = res.data as RecallResponse | RecallResult[];
      setResults(Array.isArray(payload) ? payload : (payload.results ?? []));
    } catch (error) {
      toast({
        title: "Search failed",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setSearching(false);
    }
  };

  const openHistory = async (result: RecallResult) => {
    setHistoryFor(result);
    setHistory(null);
    try {
      const res = await api.get<MemoryHistoryEntry[]>(
        RECALL_ENDPOINTS.HISTORY(result.id),
      );
      setHistory(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      toast({
        title: "Could not load history",
        description: getErrorMessage(error),
        variant: "destructive",
      });
      setHistory([]);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat">Recall playground</h1>
        <p className="text-sm text-onSurface-default-secondary mt-1">
          Run a query the way an agent would, and see exactly why each memory
          came back.
        </p>
      </div>

      <Card className="border-memBorder-primary">
        <CardContent className="grid gap-4 p-5 md:grid-cols-2">
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="recall-query">Query</Label>
            <div className="flex gap-2">
              <Input
                id="recall-query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }}
                placeholder="What does this agent remember about tennis?"
              />
              <Button onClick={runSearch} disabled={searching || !query.trim()}>
                <Search className="size-4 mr-2" />
                {searching ? "Searching…" : "Search"}
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="recall-user">Scope to user ID</Label>
            <Input
              id="recall-user"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="recall-topk">Top K</Label>
              <Input
                id="recall-topk"
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                inputMode="numeric"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="recall-threshold">Threshold</Label>
              <Input
                id="recall-threshold"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                placeholder="Default"
                inputMode="decimal"
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm md:col-span-2">
            <Switch checked={explain} onCheckedChange={setExplain} />
            <SlidersHorizontal className="size-4 text-onSurface-default-tertiary" />
            Show the score breakdown for every result
          </label>
        </CardContent>
      </Card>

      {results !== null && (
        <div className="flex items-center gap-3 text-sm text-onSurface-default-secondary">
          <span>
            {results.length} result{results.length === 1 ? "" : "s"}
          </span>
          {elapsedMs !== null && (
            <span className="tabular-nums">· {elapsedMs} ms round trip</span>
          )}
        </div>
      )}

      {results === null ? (
        <EmptyState
          title="No search run yet"
          description="Enter a query above to see what this instance would return."
        />
      ) : results.length === 0 ? (
        <EmptyState
          title="Nothing matched"
          description="No memory scored above the threshold for this query."
        />
      ) : (
        <div className="space-y-3">
          {results.map((result, index) => (
            <Card key={result.id} className="border-memBorder-primary">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 shrink-0 text-xs tabular-nums text-onSurface-default-tertiary">
                    #{index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-onSurface-default-primary break-words">
                      {result.memory ?? "(no text)"}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {result.score !== undefined && (
                        <Badge variant="secondary" className="tabular-nums">
                          score {result.score.toFixed(4)}
                        </Badge>
                      )}
                      {result.user_id && (
                        <Badge variant="outline">user: {result.user_id}</Badge>
                      )}
                      {result.agent_id && (
                        <Badge variant="outline">agent: {result.agent_id}</Badge>
                      )}
                      {result.run_id && (
                        <Badge variant="outline">run: {result.run_id}</Badge>
                      )}
                    </div>
                    {result.score_details && (
                      <ScoreBar details={result.score_details} />
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openHistory(result)}
                    title="Show how this memory changed"
                  >
                    <History className="size-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={historyFor !== null}
        onOpenChange={(open) => {
          if (!open) {
            setHistoryFor(null);
            setHistory(null);
          }
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Memory history</DialogTitle>
            <DialogDescription className="break-words">
              {historyFor?.memory}
            </DialogDescription>
          </DialogHeader>

          {history === null ? (
            <p className="text-sm text-onSurface-default-tertiary">Loading…</p>
          ) : history.length === 0 ? (
            <p className="text-sm text-onSurface-default-tertiary">
              This memory has not been revised since it was created.
            </p>
          ) : (
            <div className="max-h-[60vh] space-y-3 overflow-auto">
              {history.map((entry, index) => (
                <div
                  key={entry.id ?? index}
                  className="rounded-md border border-memBorder-primary p-3 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <Badge variant="outline">{entry.event ?? "UPDATE"}</Badge>
                    <span className="text-xs text-onSurface-default-tertiary">
                      {entry.created_at
                        ? new Date(entry.created_at).toLocaleString()
                        : ""}
                    </span>
                  </div>
                  {entry.old_memory && (
                    <p className="mt-2 break-words text-red-600 line-through dark:text-red-400">
                      {entry.old_memory}
                    </p>
                  )}
                  {entry.new_memory && (
                    <p className="mt-1 break-words text-emerald-700 dark:text-emerald-400">
                      {entry.new_memory}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
