"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { Link2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import {
  ENTITY_LABEL,
  ENTITY_LABEL_PLURAL,
  ENTITY_TYPES,
  entityHref,
  type EntityType,
} from "@/constants/entities";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { CopyInline } from "@/components/shared/copy-inline";

interface Entity {
  id: string;
  type: EntityType;
  total_memories: number;
  aliases: string[];
  display_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export default function EntitiesPage() {
  const { can } = useScope();
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<EntityType | "all">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

  const [linking, setLinking] = useState(false);
  const [canonical, setCanonical] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      setEntities(res.data);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load entities."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: entities.length };
    for (const type of ENTITY_TYPES) {
      out[type] = entities.filter((e) => e.type === type).length;
    }
    return out;
  }, [entities]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entities.filter((e) => {
      if (tab !== "all" && e.type !== tab) return false;
      if (!needle) return true;
      return (
        e.id.toLowerCase().includes(needle) ||
        (e.display_name ?? "").toLowerCase().includes(needle) ||
        e.aliases.some((a) => a.toLowerCase().includes(needle))
      );
    });
  }, [entities, tab, query]);

  // Only entities of one type can be linked together — a user and an agent are
  // not the same thing however similar their ids look.
  const selectedEntities = useMemo(
    () => visible.filter((e) => selected.includes(`${e.type}:${e.id}`)),
    [visible, selected],
  );
  const linkableType = useMemo(() => {
    const types = new Set(selectedEntities.map((e) => e.type));
    return types.size === 1 ? [...types][0] : null;
  }, [selectedEntities]);

  const toggle = (key: string) =>
    setSelected((current) =>
      current.includes(key)
        ? current.filter((k) => k !== key)
        : [...current, key],
    );

  const openLink = () => {
    // The entity with the most memories is offered as the survivor: it is the
    // one whose identifier is most likely already meaningful elsewhere.
    const biggest = [...selectedEntities].sort(
      (a, b) => b.total_memories - a.total_memories,
    )[0];
    setCanonical(biggest?.id ?? "");
    setLinking(true);
  };

  const submitLink = async () => {
    if (!linkableType || !canonical) return;
    setSaving(true);
    try {
      await api.post(ENTITY_ENDPOINTS.LINKS, {
        entity_type: linkableType,
        canonical_id: canonical,
        alias_ids: selectedEntities
          .map((e) => e.id)
          .filter((id) => id !== canonical),
      });
      toast.success("Entities linked");
      setLinking(false);
      setSelected([]);
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not link those entities."));
    } finally {
      setSaving(false);
    }
  };

  const totalMemories = selectedEntities.reduce(
    (n, e) => n + e.total_memories,
    0,
  );

  return (
    <div className="space-y-4 p-6">
      <header>
        <h1 className="typo-heading-md text-onSurface-default-primary">
          Entities
        </h1>
        <p className="typo-body-sm text-onSurface-default-tertiary">
          Who and what this project has memories about. Link the identifiers
          that are the same person so their memories stop fragmenting.
        </p>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-memBorder-primary">
        {(["all", ...ENTITY_TYPES] as const).map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 typo-body-sm transition-colors",
              tab === key
                ? "border-onSurface-default-primary text-onSurface-default-primary"
                : "border-transparent text-onSurface-default-tertiary hover:text-onSurface-default-secondary",
            )}
          >
            {key === "all" ? "All" : ENTITY_LABEL_PLURAL[key]}
            <span className="ml-1.5 tabular-nums opacity-60">
              {counts[key] ?? 0}
            </span>
          </button>
        ))}
      </div>

      <FilterBar
        placeholder="Search identifiers, names, and aliases…"
        query={query}
        onQueryChange={setQuery}
        onRefresh={load}
        isRefreshing={loading}
        onClearAll={() => {
          setQuery("");
          setSelected([]);
        }}
      />

      {selected.length > 1 && can("admin") && (
        <Card>
          <CardContent className="flex items-center justify-between gap-4 py-3">
            <p className="typo-body-sm text-onSurface-default-secondary">
              {selected.length} selected
              {linkableType
                ? ` · ${totalMemories} memories would be combined`
                : " · select entities of one type to link them"}
            </p>
            <Button size="sm" onClick={openLink} disabled={!linkableType}>
              <Link2 className="mr-1.5 size-3.5" />
              Link entities
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              title="No entities yet"
              description="An entity appears here as soon as a memory mentions it."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10" />
                    <TableHead>Identifier</TableHead>
                    <TableHead className="w-24">Type</TableHead>
                    <TableHead className="w-28 text-right">Memories</TableHead>
                    <TableHead className="w-40">Last seen</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visible.map((entity) => {
                    const key = `${entity.type}:${entity.id}`;
                    return (
                      <TableRow key={key}>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={selected.includes(key)}
                            onCheckedChange={() => toggle(key)}
                            aria-label={`Select ${entity.id}`}
                          />
                        </TableCell>
                        <TableCell>
                          <Link
                            href={entityHref(entity.type, entity.id)}
                            className="font-mono text-xs text-onSurface-default-primary hover:underline"
                          >
                            {entity.display_name ?? entity.id}
                          </Link>
                          {entity.aliases.length > 0 && (
                            <div className="mt-0.5 flex flex-wrap gap-1">
                              {entity.aliases.map((alias) => (
                                <span
                                  key={alias}
                                  className="rounded bg-surface-default-secondary px-1.5 py-0.5 font-mono text-[10px] text-onSurface-default-tertiary"
                                  title="Resolves to this entity"
                                >
                                  {alias}
                                </span>
                              ))}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-onSurface-default-secondary">
                          {ENTITY_LABEL[entity.type]}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                          {entity.total_memories}
                        </TableCell>
                        <TableCell className="text-onSurface-default-tertiary">
                          {entity.updated_at
                            ? formatDistanceToNow(new Date(entity.updated_at), {
                                addSuffix: true,
                              })
                            : "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={linking} onOpenChange={setLinking}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>Link these entities</DialogTitle>
            <DialogDescription>
              They become one entity. Nothing is deleted and nothing is
              rewritten — this is reversible, and each memory still records
              which identifier it arrived under.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <label className="typo-body-sm text-onSurface-default-primary">
                Which identifier survives?
              </label>
              <Select value={canonical} onValueChange={setCanonical}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {selectedEntities.map((entity) => (
                    <SelectItem key={entity.id} value={entity.id}>
                      {entity.id} · {entity.total_memories} memories
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="rounded-md border border-memBorder-primary bg-surface-default-secondary p-3">
              <p className="typo-caption-sm text-onSurface-default-tertiary">
                After linking
              </p>
              <p className="mt-1 typo-body-sm text-onSurface-default-primary">
                <span className="font-mono">{canonical || "—"}</span> will hold{" "}
                <span className="tabular-nums">{totalMemories}</span> memories.
              </p>
              <p className="mt-1 typo-caption-sm text-onSurface-default-tertiary">
                New memories arriving under{" "}
                {selectedEntities
                  .filter((e) => e.id !== canonical)
                  .map((e) => e.id)
                  .join(", ") || "the other identifiers"}{" "}
                will be stored under {canonical || "the survivor"}, with the
                original identifier kept in metadata.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setLinking(false)}>
              Cancel
            </Button>
            <Button onClick={submitLink} disabled={saving || !canonical}>
              {saving ? "Linking…" : "Link"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
