"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, Search, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { api, getAccessToken } from "@/utils/api";
import { SYSTEM_ENDPOINTS } from "@/utils/api-endpoints";
import { LogEntry, LogListResponse } from "@/types/api";
import { cn } from "@/lib/utils";

const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
const MAX_RENDERED = 1000;

const LEVEL_CLASS: Record<LogEntry["level"], string> = {
  DEBUG: "text-onSurface-default-tertiary",
  INFO: "text-sky-600 dark:text-sky-400",
  WARNING: "text-amber-600 dark:text-amber-400",
  ERROR: "text-red-600 dark:text-red-400",
  CRITICAL: "text-red-700 dark:text-red-300 font-semibold",
};

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("ALL");
  const [filter, setFilter] = useState("");
  const [live, setLive] = useState(true);
  const [connected, setConnected] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  // Only pin to the bottom while the reader is already there, so scrolling up
  // to read something does not get yanked away by the next arriving line.
  const pinnedToBottom = useRef(true);

  const append = useCallback((entry: LogEntry) => {
    setLogs((current) => {
      const next = [...current, entry];
      return next.length > MAX_RENDERED
        ? next.slice(next.length - MAX_RENDERED)
        : next;
    });
  }, []);

  // Initial snapshot.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.get<LogListResponse>(SYSTEM_ENDPOINTS.LOGS, {
          params: { limit: 300 },
        });
        if (!cancelled) setLogs(res.data.logs ?? []);
      } catch (error) {
        if (!cancelled) {
          toast({
            title: "Failed to load logs",
            description: getErrorMessage(error),
            variant: "destructive",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Live stream over fetch rather than EventSource. EventSource cannot set
  // request headers, which would force the access token into the query string -
  // and a token in a URL ends up in access logs and Referer headers, which on a
  // log-viewing page is precisely the wrong place to put a credential.
  useEffect(() => {
    if (!live) {
      setConnected(false);
      return;
    }

    const controller = new AbortController();

    void (async () => {
      try {
        const token = getAccessToken();
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? ""}${SYSTEM_ENDPOINTS.LOG_STREAM}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          },
        );
        if (!response.ok || !response.body) {
          setConnected(false);
          return;
        }
        setConnected(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line; anything after the last
          // separator is a partial frame and stays buffered.
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            for (const line of frame.split("\n")) {
              if (!line.startsWith("data:")) continue; // skip ':' keepalives
              try {
                append(JSON.parse(line.slice(5).trim()) as LogEntry);
              } catch {
                // A malformed frame must not tear down the stream.
              }
            }
          }
        }
      } catch {
        // Abort on unmount lands here; nothing to report.
      } finally {
        setConnected(false);
      }
    })();

    return () => controller.abort();
  }, [live, append]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return logs.filter((entry) => {
      if (level !== "ALL" && entry.level !== level) return false;
      if (!needle) return true;
      return (
        entry.message.toLowerCase().includes(needle) ||
        entry.logger.toLowerCase().includes(needle) ||
        (entry.request_id ?? "").toLowerCase().includes(needle)
      );
    });
  }, [logs, level, filter]);

  useEffect(() => {
    if (pinnedToBottom.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [visible]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-onSurface-default-primary">
            Logs
          </h1>
          <p className="text-sm text-onSurface-default-tertiary mt-1">
            Live output from the API. Filter by request ID to follow one call
            end to end.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="secondary"
            className={cn(
              "gap-1.5",
              connected
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-onSurface-default-tertiary",
            )}
          >
            <span
              className={cn(
                "size-2 rounded-full",
                connected ? "bg-emerald-500 animate-pulse" : "bg-zinc-400",
              )}
              aria-hidden
            />
            {connected ? "Live" : "Paused"}
          </Badge>
          <Button variant="outline" onClick={() => setLive((v) => !v)}>
            {live ? (
              <Pause className="size-4 mr-2" />
            ) : (
              <Play className="size-4 mr-2" />
            )}
            {live ? "Pause" : "Resume"}
          </Button>
          <Button variant="outline" onClick={() => setLogs([])}>
            <Trash2 className="size-4 mr-2" />
            Clear
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-onSurface-default-tertiary" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by message, logger or request ID"
            className="pl-9"
          />
        </div>
        <Select
          value={level}
          onValueChange={(v) => setLevel(v as (typeof LEVELS)[number])}
        >
          <SelectTrigger className="w-[150px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LEVELS.map((item) => (
              <SelectItem key={item} value={item}>
                {item === "ALL" ? "All levels" : item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="h-[calc(100vh-320px)] min-h-[300px] overflow-auto font-mono text-xs"
          >
            {visible.length === 0 ? (
              <p className="p-6 text-onSurface-default-tertiary">
                {logs.length === 0
                  ? "No log output captured yet."
                  : "No lines match this filter."}
              </p>
            ) : (
              <table className="w-full border-collapse">
                <tbody>
                  {visible.map((entry, index) => (
                    <tr
                      key={`${entry.timestamp}-${index}`}
                      className="border-b border-memBorder-primary/40 align-top hover:bg-surface-default-secondary"
                    >
                      <td className="whitespace-nowrap px-3 py-1.5 text-onSurface-default-tertiary tabular-nums">
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </td>
                      <td
                        className={cn(
                          "whitespace-nowrap px-2 py-1.5",
                          LEVEL_CLASS[entry.level],
                        )}
                      >
                        {entry.level}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-onSurface-default-tertiary max-w-[180px] truncate">
                        {entry.logger}
                      </td>
                      <td className="px-2 py-1.5 text-onSurface-default-primary break-words">
                        {entry.message}
                        {entry.error && (
                          <span className="block text-red-600 dark:text-red-400">
                            {entry.error}
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-1.5 text-onSurface-default-tertiary">
                        {entry.request_id ? entry.request_id.slice(0, 8) : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
