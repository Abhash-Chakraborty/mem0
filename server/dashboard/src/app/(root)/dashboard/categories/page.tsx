"use client";

import { useState } from "react";
import { RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { CATEGORY_ENDPOINTS } from "@/utils/api-endpoints";
import { Category, Memory } from "@/types/api";

export default function CategoriesPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#7c3aed");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [manualCategoryByMemory, setManualCategoryByMemory] = useState<
    Record<string, string>
  >({});
  const [busy, setBusy] = useState(false);

  const categoriesQuery = useApiQuery<Category[]>(
    async () => (await api.get(CATEGORY_ENDPOINTS.BASE)).data ?? [],
    { errorToast: "Failed to load categories", initialData: [] },
  );

  const memoriesQuery = useApiQuery<Memory[]>(
    async () => {
      const res = await api.get(CATEGORY_ENDPOINTS.MEMORIES, {
        params: selectedCategory
          ? { category_id: selectedCategory }
          : undefined,
      });
      return res.data?.results ?? [];
    },
    { errorToast: "Failed to load categorized memories", initialData: [] },
  );

  const categories = categoriesQuery.data ?? [];
  const memories = memoriesQuery.data ?? [];

  const refreshAll = async () => {
    await Promise.all([categoriesQuery.refetch(), memoriesQuery.refetch()]);
  };

  const createCategory = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.post(CATEGORY_ENDPOINTS.BASE, {
        name,
        description,
        color,
      });
      setName("");
      setDescription("");
      setColor("#7c3aed");
      toast({ title: "Category created", variant: "success" });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to create category",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const deleteCategory = async (categoryId: string) => {
    setBusy(true);
    try {
      await api.delete(CATEGORY_ENDPOINTS.BY_ID(categoryId));
      if (selectedCategory === categoryId) setSelectedCategory("");
      toast({ title: "Category deleted", variant: "success" });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to delete category",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const reclassifyAll = async () => {
    setBusy(true);
    try {
      const res = await api.post(CATEGORY_ENDPOINTS.RECLASSIFY);
      toast({
        title: "Reclassification complete",
        description: `${res.data.processed} of ${res.data.total} memories processed.`,
        variant: "success",
      });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to reclassify memories",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const classifyMemory = async (memoryId: string) => {
    setBusy(true);
    try {
      await api.post(CATEGORY_ENDPOINTS.CLASSIFY_MEMORY(memoryId));
      toast({ title: "Memory classified", variant: "success" });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to classify memory",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const assignMemory = async (memoryId: string) => {
    const categoryId = manualCategoryByMemory[memoryId];
    if (!categoryId) return;
    setBusy(true);
    try {
      await api.post(CATEGORY_ENDPOINTS.ASSIGN_MEMORY(memoryId), {
        category_id: categoryId,
        reason: "Assigned from dashboard",
      });
      toast({ title: "Category assigned", variant: "success" });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to assign category",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold font-fustat">Categories</h1>
          <p className="text-sm text-onSurface-default-secondary mt-1">
            Self-hosted AI categories for organizing memories.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refreshAll} disabled={busy}>
            <RefreshCw className="size-4 mr-2" />
            Refresh
          </Button>
          <Button
            onClick={reclassifyAll}
            disabled={busy || categories.length === 0}
          >
            <Sparkles className="size-4 mr-2" />
            Reclassify all
          </Button>
        </div>
      </div>

      <Card className="border-memBorder-primary">
        <CardContent className="grid gap-4 p-5 md:grid-cols-[1fr_1.5fr_120px_auto] md:items-end">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Work"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Career goals, projects, and work preferences"
              className="min-h-10"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Color</Label>
            <Input
              value={color}
              onChange={(event) => setColor(event.target.value)}
            />
          </div>
          <Button onClick={createCategory} disabled={busy || !name.trim()}>
            Create
          </Button>
        </CardContent>
      </Card>

      {categoriesQuery.isLoading ? (
        <TableSkeleton rows={3} columns={3} />
      ) : categories.length === 0 ? (
        <EmptyState
          title="No categories yet"
          description="Create categories such as Work, Preferences, Health, or People. New memories will be AI-classified into them."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {categories.map((category) => (
            <Card
              key={category.id}
              className={`border-memBorder-primary ${selectedCategory === category.id ? "ring-2 ring-memPurple-400" : ""}`}
            >
              <CardContent className="p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <button
                    type="button"
                    className="text-left"
                    onClick={() =>
                      setSelectedCategory(
                        selectedCategory === category.id ? "" : category.id,
                      )
                    }
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="size-3 rounded-full"
                        style={{ backgroundColor: category.color }}
                      />
                      <p className="font-medium">{category.name}</p>
                    </div>
                    <p className="text-xs text-onSurface-default-secondary mt-1 line-clamp-2">
                      {category.description || "No description"}
                    </p>
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteCategory(category.id)}
                    disabled={busy}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
                <Badge variant="outline">
                  {category.memory_count} memories
                </Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-medium">
            {selectedCategory
              ? `Memories in ${categories.find((category) => category.id === selectedCategory)?.name ?? "category"}`
              : "Recent memories"}
          </h2>
          {selectedCategory && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelectedCategory("")}
            >
              Clear filter
            </Button>
          )}
        </div>

        {memoriesQuery.isLoading ? (
          <TableSkeleton rows={5} columns={3} />
        ) : memories.length === 0 ? (
          <EmptyState
            title="No memories found"
            description="Add memories, then run classification."
          />
        ) : (
          <div className="space-y-3">
            {memories.slice(0, 50).map((memory) => (
              <Card key={memory.id} className="border-memBorder-primary">
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-sm">{memory.memory}</p>
                    <div className="flex shrink-0 gap-2">
                      <select
                        className="h-9 rounded-md border border-memBorder-primary bg-surface-default-primary px-2 text-sm"
                        value={manualCategoryByMemory[memory.id] ?? ""}
                        onChange={(event) =>
                          setManualCategoryByMemory((current) => ({
                            ...current,
                            [memory.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">Assign...</option>
                        {categories.map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => assignMemory(memory.id)}
                        disabled={busy || !manualCategoryByMemory[memory.id]}
                      >
                        Assign
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => classifyMemory(memory.id)}
                        disabled={busy}
                      >
                        <Sparkles className="size-3.5 mr-1" />
                        Classify
                      </Button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(memory.categories ?? []).length === 0 ? (
                      <Badge variant="outline">Uncategorized</Badge>
                    ) : (
                      memory.categories?.map((category) => (
                        <Badge key={category.id} variant="outline">
                          {category.name}
                          {category.confidence !== null &&
                            ` ${Math.round(category.confidence * 100)}%`}
                        </Badge>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
