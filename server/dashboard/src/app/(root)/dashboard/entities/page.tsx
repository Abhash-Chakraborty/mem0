"use client";

import { useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { format } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable } from "@/components/shared/data-table";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity, EntityType } from "@/types/api";

const TABS: { value: EntityType; label: string }[] = [
  { value: "user", label: "User" },
  { value: "run", label: "Run" },
  { value: "agent", label: "Agent" },
  { value: "app", label: "Application" },
];

export default function EntitiesPage() {
  const [entityToDelete, setEntityToDelete] = useState<Entity | null>(null);
  const [activeTab, setActiveTab] = useState<EntityType>("user");

  const {
    data: entities = [],
    isLoading,
    refetch,
  } = useApiQuery<Entity[]>(
    async () => {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      return res.data ?? [];
    },
    { errorToast: "Failed to load entities", initialData: [] },
  );

  const counts = useMemo(() => {
    const map: Record<EntityType, number> = {
      user: 0,
      run: 0,
      agent: 0,
      app: 0,
    };
    for (const e of entities) map[e.type] = (map[e.type] ?? 0) + 1;
    return map;
  }, [entities]);

  const handleDelete = async () => {
    if (!entityToDelete) return;
    try {
      await api.delete(
        ENTITY_ENDPOINTS.BY_ID(entityToDelete.type, entityToDelete.id),
      );
      toast({ title: "Entity deleted", variant: "success" });
      setEntityToDelete(null);
      void refetch();
    } catch (error) {
      toast({
        title: "Failed to delete entity",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    }
  };

  const buildColumns = (type: EntityType) => [
    {
      key: "id" as keyof Entity,
      label: "Entity",
      width: 320,
      render: (value: string) => (
        <span className="font-mono text-sm truncate">{value}</span>
      ),
    },
    {
      key: "total_memories" as keyof Entity,
      label: "Memories",
      width: 110,
      align: "right" as const,
    },
    {
      key: "updated_at" as keyof Entity,
      label: "Last Active",
      width: 160,
      render: (value: string | null) =>
        value ? format(new Date(value), "MMM d, yyyy h:mm a") : "--",
    },
    // Application entities have no bulk-delete support in the SDK.
    ...(type !== "app"
      ? [
          {
            key: "id" as keyof Entity,
            label: "",
            width: 40,
            render: (_: string, row: Entity) => (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setEntityToDelete(row)}
                className="size-7"
              >
                <Trash2 className="size-3.5 text-onSurface-danger-primary" />
              </Button>
            ),
          },
        ]
      : []),
  ];

  const renderTab = (type: EntityType) => {
    const rows = entities.filter((e) => e.type === type);
    if (rows.length === 0) {
      return (
        <EmptyState
          title={`No ${type === "app" ? "application" : type} entities`}
          description={
            type === "app"
              ? "Application entities appear when memories are stored with an app_id. This dimension is read-only."
              : `Entities appear once memories are stored with a ${type}_id.`
          }
        />
      );
    }
    return (
      <Card className="border-memBorder-primary overflow-hidden">
        <DataTable
          data={rows}
          columns={buildColumns(type)}
          getRowKey={(row) => `${row.type}:${row.id}`}
        />
      </Card>
    );
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold font-fustat">Entities</h1>

      {isLoading ? (
        <TableSkeleton rows={5} columns={4} />
      ) : (
        <Tabs
          value={activeTab}
          onValueChange={(v) => setActiveTab(v as EntityType)}
        >
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="gap-1.5">
                {t.label}
                <Badge
                  variant="outline"
                  className="ml-0.5 px-1.5 py-0 text-[10px]"
                >
                  {counts[t.value]}
                </Badge>
              </TabsTrigger>
            ))}
          </TabsList>
          {TABS.map((t) => (
            <TabsContent key={t.value} value={t.value}>
              {renderTab(t.value)}
            </TabsContent>
          ))}
        </Tabs>
      )}

      <DeleteConfirmationModal
        isOpen={!!entityToDelete}
        onClose={() => setEntityToDelete(null)}
        onConfirm={handleDelete}
        title="Delete entity"
        description="All memories associated with this entity will be permanently removed. This cannot be undone."
        itemName={entityToDelete?.id ?? ""}
        confirmButtonText="Delete"
      />
    </div>
  );
}
