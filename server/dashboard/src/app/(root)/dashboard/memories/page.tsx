"use client";

import { Suspense, useMemo, useState } from "react";
import { FlaskConical, Trash2 } from "lucide-react";
import { format, formatDistanceToNow } from "date-fns";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/shared/data-table";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { DetailPanel } from "@/components/panel/detail-panel";
import { PanelSection } from "@/components/panel/panel-section";
import { JsonBlock, keyCount } from "@/components/panel/json-block";
import { EntityChip } from "@/components/shared/entity-chip";
import { ExpandableCell } from "@/components/shared/expandable-cell";
import { FilterBar } from "@/components/shared/filter-bar";
import {
  LifecycleBadge,
  LIFECYCLE_DESCRIPTION,
  type LifecycleState,
} from "@/components/shared/status-badges";
import { MemoryFeedback } from "@/components/panel/memory-feedback";
import { entityHref, FIELD_TO_ENTITY } from "@/constants/entities";
import { usePanelRecord } from "@/hooks/use-panel-record";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { api } from "@/utils/api";
import { CATEGORY_ENDPOINTS, MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Memory } from "@/types/api";

const PAGE_SIZE = 20;
// Keep in sync with ALL_MEMORIES_LIMIT in server/main.py.
const MEMORY_FETCH_LIMIT = 1000;

const QUICK_FILTERS = [
  { id: "hide_playground", label: "Hide playground", icon: FlaskConical },
];

/** Which entity a memory belongs to, preferring the most specific one set. */
function primaryEntity(
  memory: Memory,
): { type: "user" | "agent" | "run"; id: string } | null {
  for (const field of ["user_id", "agent_id", "run_id"] as const) {
    const value = memory[field];
    if (value) {
      return {
        type: FIELD_TO_ENTITY[field] as "user" | "agent" | "run",
        id: value,
      };
    }
  }
  return null;
}

function isPlayground(memory: Memory): boolean {
  const metadata = memory.metadata as Record<string, unknown> | undefined;
  if (metadata?.playground_demo) return true;
  return Boolean(primaryEntity(memory)?.id.startsWith("playground-"));
}

function MemoriesPageInner() {
  const [query, setQuery] = useState("");
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [memoryToDelete, setMemoryToDelete] = useState<Memory | null>(null);
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState("details");
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";

  const {
    data: memories = [],
    isLoading,
    refetch,
  } = useApiQuery<Memory[]>(
    async () => {
      // /categories/memories is the only listing that returns memories with
      // their category assignments attached, which the Categories column needs.
      // It requires admin, so fall back to the plain listing rather than
      // showing an empty page to a non-admin.
      try {
        const res = await api.get(CATEGORY_ENDPOINTS.MEMORIES);
        const raw = res.data?.results ?? [];
        if (Array.isArray(raw)) return raw;
      } catch {
        // fall through
      }
      const res = await api.get(MEMORY_ENDPOINTS.BASE, {
        params: { top_k: MEMORY_FETCH_LIMIT },
      });
      const raw = res.data?.results ?? res.data ?? [];
      return Array.isArray(raw) ? raw : [];
    },
    { errorToast: "Failed to load memories", initialData: [] },
  );

  // Filtering is client-side until phase 04 gives the API a real query surface.
  // Doing it here keeps the page honest about what it can actually do today.
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return memories.filter((memory) => {
      if (activeFilters.includes("hide_playground") && isPlayground(memory)) {
        return false;
      }
      if (!needle) return true;
      const entity = primaryEntity(memory);
      return (
        memory.memory?.toLowerCase().includes(needle) ||
        entity?.id.toLowerCase().includes(needle)
      );
    });
  }, [memories, query, activeFilters]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = useMemo(
    () => filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filtered, page],
  );

  // Stepping is scoped to the visible page, so ↑/↓ never jumps to a record the
  // user cannot see in the list behind the panel.
  const panel = usePanelRecord<Memory>({
    records: paginated,
    getId: (m) => m.id,
    param: "memoryId",
  });
  const selected = panel.selected;

  const toggleFilter = (id: string) => {
    setPage(0);
    setActiveFilters((current) =>
      current.includes(id) ? current.filter((f) => f !== id) : [...current, id],
    );
  };

  const handleDelete = async () => {
    if (!memoryToDelete) return;
    try {
      await api.delete(MEMORY_ENDPOINTS.BY_ID(memoryToDelete.id));
      toast({ title: "Memory deleted", variant: "success" });
      if (selected?.id === memoryToDelete.id) panel.close();
      setMemoryToDelete(null);
      void refetch();
    } catch (error) {
      toast({
        title: "Failed to delete memory",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    }
  };

  const columns = [
    {
      key: "created_at" as keyof Memory,
      label: "Time",
      width: 90,
      render: (value: string) =>
        value ? (
          <span
            className="text-sm text-onSurface-default-secondary"
            title={format(new Date(value), "PPpp")}
          >
            {formatDistanceToNow(new Date(value), { addSuffix: false })} ago
          </span>
        ) : (
          "--"
        ),
    },
    {
      key: "id" as keyof Memory,
      label: "Entities",
      width: 150,
      render: (_: string, row: Memory) => {
        const entity = primaryEntity(row);
        if (!entity) return <span className="text-sm">--</span>;
        return (
          <EntityChip
            type={entity.type}
            id={entity.id}
            href={entityHref(entity.type, entity.id)}
            isPlayground={isPlayground(row)}
          />
        );
      },
    },
    {
      key: "memory" as keyof Memory,
      label: "Memory Content",
      width: 340,
      render: (value: string) => <ExpandableCell text={value ?? ""} />,
    },
    {
      key: "categories" as keyof Memory,
      label: "Categories",
      width: 140,
      render: (_: unknown, row: Memory) => {
        const categories = row.categories ?? [];
        if (categories.length === 0) {
          return (
            <span className="text-xs text-onSurface-default-tertiary">--</span>
          );
        }
        return (
          <span className="flex min-w-0 items-center gap-1">
            <span className="truncate font-mono text-[12px] text-onSurface-default-secondary">
              {categories[0].name}
            </span>
            {categories.length > 1 && (
              <span className="shrink-0 rounded bg-surface-default-secondary px-1 font-mono text-[10px] text-onSurface-default-tertiary">
                +{categories.length - 1}
              </span>
            )}
          </span>
        );
      },
    },
    {
      key: "id" as keyof Memory,
      label: "Lifecycle",
      width: 100,
      render: (_: string, row: Memory) => (
        <LifecycleBadge
          state={(row.lifecycle?.state ?? "active") as LifecycleState}
        />
      ),
    },
    {
      key: "id" as keyof Memory,
      label: "Action",
      width: 70,
      render: (_: string, row: Memory) => (
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label="Delete memory"
          onClick={(e) => {
            e.stopPropagation();
            setMemoryToDelete(row);
          }}
        >
          <Trash2 className="size-3.5 text-onSurface-danger-primary" />
        </Button>
      ),
    },
  ];

  const selectedEntity = selected ? primaryEntity(selected) : null;

  return (
    <div className="space-y-4">
      <h1 className="font-fustat text-xl font-semibold">Memories</h1>

      <FilterBar
        placeholder="Search memory text, or type user:alice…"
        query={query}
        onQueryChange={(value) => {
          setQuery(value);
          setPage(0);
        }}
        quickFilters={QUICK_FILTERS}
        activeFilters={activeFilters}
        onToggleFilter={toggleFilter}
        onRefresh={() => void refetch()}
        isRefreshing={isLoading}
        onClearAll={() => {
          setQuery("");
          setActiveFilters([]);
          setPage(0);
        }}
      />

      {isLoading ? (
        <TableSkeleton rows={6} columns={6} />
      ) : memories.length === 0 ? (
        <EmptyState
          title="No memories yet"
          description="Create your first memory by sending a POST /memories request."
        >
          <pre className="mt-3 max-w-lg overflow-x-auto rounded bg-surface-default-secondary p-3 text-left font-mono text-xs">
            {`curl -X POST ${apiUrl}/memories \\
  -H "X-API-Key: <your-key>" \\
  -H "Content-Type: application/json" \\
  -d '{"messages": [{"role": "user", "content": "I like hiking"}], "user_id": "alice"}'`}
          </pre>
        </EmptyState>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No memories match"
          description="Try a different search, or clear the active filters."
        />
      ) : (
        <>
          <Card className="overflow-hidden border-memBorder-primary">
            <DataTable
              data={paginated}
              columns={columns}
              getRowKey={(row) => row.id}
              onRowClick={(row) => panel.select(row)}
              getRowClassName={(row) =>
                selected?.id === row.id
                  ? "bg-surface-default-tertiary"
                  : undefined
              }
            />
          </Card>
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-onSurface-default-tertiary">
              <span className="tabular-nums">
                {page * PAGE_SIZE + 1}–
                {Math.min((page + 1) * PAGE_SIZE, filtered.length)} of{" "}
                {filtered.length}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      <DetailPanel
        open={panel.open}
        onOpenChange={(next) => {
          if (!next) panel.close();
        }}
        title={selected ? `“${selected.memory}”` : ""}
        meta={
          selected
            ? [
                selected.created_at
                  ? `Created ${format(new Date(selected.created_at), "d MMM yyyy, HH:mm:ss")}`
                  : null,
                selected.updated_at
                  ? `Updated ${format(new Date(selected.updated_at), "d MMM yyyy, HH:mm:ss")}`
                  : null,
              ].filter(Boolean)
            : []
        }
        copyId={selected?.id}
        rows={
          selectedEntity
            ? [
                {
                  label:
                    selectedEntity.type === "run"
                      ? "Session"
                      : selectedEntity.type === "agent"
                        ? "Agent"
                        : "User",
                  node: (
                    <EntityChip
                      type={selectedEntity.type}
                      id={selectedEntity.id}
                      href={entityHref(selectedEntity.type, selectedEntity.id)}
                    />
                  ),
                },
              ]
            : []
        }
        tabs={[
          { id: "details", label: "Details" },
          { id: "feedback", label: "Feedback" },
          { id: "changelog", label: "Changelog" },
        ]}
        activeTab={tab}
        onTabChange={setTab}
        onPrev={panel.prev}
        onNext={panel.next}
        hasPrev={panel.hasPrev}
        hasNext={panel.hasNext}
      >
        {selected && tab === "details" && (
          <>
            <PanelSection label="Memory">
              <p className="text-sm leading-relaxed text-onSurface-default-primary">
                {selected.memory}
              </p>
            </PanelSection>

            <PanelSection label="Categories">
              {selected.categories?.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {selected.categories.map((category) => (
                    <span
                      key={category.id}
                      className="inline-flex items-center gap-1.5 rounded border border-memBorder-primary bg-surface-default-secondary px-2 py-0.5 text-xs"
                    >
                      <span
                        aria-hidden
                        className="size-1.5 rounded-full"
                        style={{ backgroundColor: category.color }}
                      />
                      {category.name}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-onSurface-default-tertiary">
                  Not categorized yet.
                </p>
              )}
            </PanelSection>

            <PanelSection
              label="Metadata"
              note={
                keyCount(selected.metadata) > 0
                  ? `${keyCount(selected.metadata)} key${keyCount(selected.metadata) === 1 ? "" : "s"}`
                  : undefined
              }
            >
              <JsonBlock value={selected.metadata} emptyLabel="No metadata." />
            </PanelSection>

            {selected.lifecycle && selected.lifecycle.state !== "active" && (
              <PanelSection
                label="Lifecycle"
                note={
                  LIFECYCLE_DESCRIPTION[
                    selected.lifecycle.state as LifecycleState
                  ]
                }
              >
                <div className="flex flex-col gap-1.5 text-sm">
                  <div className="flex items-center gap-2">
                    <LifecycleBadge
                      state={selected.lifecycle.state as LifecycleState}
                    />
                    {selected.lifecycle.actor && (
                      <span className="text-xs text-onSurface-default-tertiary">
                        by {selected.lifecycle.actor}
                        {selected.lifecycle.changed_at &&
                          ` · ${new Date(selected.lifecycle.changed_at).toLocaleString()}`}
                      </span>
                    )}
                  </div>
                  {selected.lifecycle.reason && (
                    <p className="text-onSurface-default-secondary">
                      {selected.lifecycle.reason}
                    </p>
                  )}
                  {selected.lifecycle.superseded_by && (
                    <p className="text-xs text-onSurface-default-tertiary">
                      Replaced by{" "}
                      <span className="font-mono">
                        {selected.lifecycle.superseded_by}
                      </span>
                    </p>
                  )}
                  {selected.lifecycle.merged_into && (
                    <p className="text-xs text-onSurface-default-tertiary">
                      Merged into{" "}
                      <span className="font-mono">
                        {selected.lifecycle.merged_into}
                      </span>
                    </p>
                  )}
                </div>
              </PanelSection>
            )}

            <Button
              variant="outline"
              size="sm"
              className="text-onSurface-danger-primary"
              onClick={() => setMemoryToDelete(selected)}
            >
              <Trash2 className="mr-1.5 size-3.5" />
              Delete memory
            </Button>
          </>
        )}

        {selected && tab === "feedback" && (
          <PanelSection
            label="Feedback"
            note="Recorded per verdict, not overwritten — the history is the signal."
          >
            <MemoryFeedback memoryId={selected.id} />
          </PanelSection>
        )}

        {selected && tab === "changelog" && (
          <MemoryChangelog memoryId={selected.id} />
        )}
      </DetailPanel>

      <DeleteConfirmationModal
        isOpen={!!memoryToDelete}
        onClose={() => setMemoryToDelete(null)}
        onConfirm={handleDelete}
        title="Delete memory"
        description="This memory will be permanently removed. This cannot be undone."
        itemName={memoryToDelete?.id ?? ""}
        confirmButtonText="Delete"
      />
    </div>
  );
}

/** Version history for one memory, read from the SDK's history table. */
function MemoryChangelog({ memoryId }: { memoryId: string }) {
  const { data: history = [], isLoading } = useApiQuery<
    Array<Record<string, unknown>>
  >(
    async () => {
      const res = await api.get(MEMORY_ENDPOINTS.HISTORY(memoryId));
      const raw = res.data?.results ?? res.data ?? [];
      return Array.isArray(raw) ? raw : [];
    },
    { initialData: [], deps: [memoryId] },
  );

  if (isLoading) {
    return (
      <p className="text-sm text-onSurface-default-tertiary">
        Loading history…
      </p>
    );
  }
  if (history.length === 0) {
    return (
      <p className="text-sm text-onSurface-default-tertiary">
        No changes recorded since this memory was created.
      </p>
    );
  }

  return (
    <ol className="space-y-4">
      {history.map((entry, index) => {
        const text =
          (entry.new_memory as string) ?? (entry.old_memory as string) ?? "";
        const at = entry.created_at ?? entry.updated_at;
        return (
          <li key={String(entry.id ?? index)} className="flex gap-3">
            <span className="mt-0.5 shrink-0 rounded bg-surface-default-secondary px-1.5 py-0.5 font-mono text-[10px] text-onSurface-default-tertiary">
              v{history.length - index}
            </span>
            <div className="min-w-0">
              <p className="text-sm leading-relaxed text-onSurface-default-primary">
                {text}
              </p>
              {typeof at === "string" && (
                <p className="mt-1 font-mono text-[11px] text-onSurface-default-tertiary">
                  {format(new Date(at), "d MMM yyyy, HH:mm:ss")}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function MemoriesPage() {
  // usePanelRecord reads useSearchParams, which Next requires be wrapped so the
  // route can still be statically prerendered.
  return (
    <Suspense fallback={<TableSkeleton rows={6} columns={6} />}>
      <MemoriesPageInner />
    </Suspense>
  );
}
