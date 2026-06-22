"use client";

import { useState } from "react";
import { Plus, RefreshCw, Sparkles, Trash2, Wand2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  const [autoAdd, setAutoAdd] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
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
    {
      errorToast: "Failed to load categorized memories",
      initialData: [],
      deps: [selectedCategory],
    },
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
        auto_add: autoAdd,
      });
      setName("");
      setDescription("");
      setColor("#7c3aed");
      setAutoAdd(false);
      setCreateOpen(false);
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

  const toggleAutoAdd = async (categoryId: string, autoAdd: boolean) => {
    setBusy(true);
    try {
      await api.patch(CATEGORY_ENDPOINTS.BY_ID(categoryId), { auto_add: autoAdd });
      toast({
        title: autoAdd ? "Auto-add enabled" : "Auto-add disabled",
        description: autoAdd
          ? "This category will be attached to every new memory."
          : "New memories will no longer be auto-tagged with this category.",
        variant: "success",
      });
      await categoriesQuery.refetch();
    } catch (error) {
      toast({
        title: "Failed to update category",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const autoGenerate = async () => {
    if (
      !window.confirm(
        "Let the AI read your memories and propose new categories? It will create categories it suggests (skipping any that already exist).",
      )
    )
      return;
    setBusy(true);
    try {
      const res = await api.post(CATEGORY_ENDPOINTS.AUTO_GENERATE);
      const count = res.data?.count ?? 0;
      toast({
        title:
          count > 0
            ? `Generated ${count} ${count === 1 ? "category" : "categories"}`
            : "No new categories",
        description:
          count > 0
            ? res.data.created.map((c: { name: string }) => c.name).join(", ")
            : "The AI didn't find new categories to add.",
        variant: "success",
      });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to generate categories",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const reclassifyAll = async () => {
    if (
      !window.confirm(
        "Re-run AI classification across all memories? This calls the model for each memory and may take a while.",
      )
    )
      return;
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
            Organize memories with AI-assigned categories. New memories are
            auto-classified; you can correct any assignment by hand.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refreshAll} disabled={busy}>
            <RefreshCw className="size-4 mr-2" />
            Refresh
          </Button>
          <Button variant="outline" onClick={autoGenerate} disabled={busy}>
            <Sparkles className="size-4 mr-2" />
            Auto-generate
          </Button>
          <Button
            variant="outline"
            onClick={reclassifyAll}
            disabled={busy || categories.length === 0}
          >
            <Wand2 className="size-4 mr-2" />
            Reclassify all
          </Button>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="size-4 mr-2" />
                New category
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>New category</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 py-2">
                <div className="space-y-1.5">
                  <Label>Name</Label>
                  <Input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Work"
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Description</Label>
                  <Textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="What belongs here — e.g. projects and work preferences"
                    className="min-h-16"
                  />
                  <p className="text-xs text-onSurface-default-tertiary">
                    The description guides the AI when classifying memories.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label>Color</Label>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={color}
                      onChange={(event) => setColor(event.target.value)}
                      className="h-9 w-12 cursor-pointer rounded-md border border-memBorder-primary bg-transparent p-1"
                      aria-label="Category color"
                    />
                    <Input
                      value={color}
                      onChange={(event) => setColor(event.target.value)}
                      className="w-32 font-mono"
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between gap-2 rounded-md border border-memBorder-primary p-3">
                  <div className="min-w-0">
                    <Label htmlFor="new-auto-add" className="cursor-pointer">
                      Auto-add to new memories
                    </Label>
                    <p className="text-xs text-onSurface-default-tertiary">
                      Always tag every new memory with this category (no AI
                      decision). Off by default.
                    </p>
                  </div>
                  <Switch
                    id="new-auto-add"
                    checked={autoAdd}
                    onCheckedChange={setAutoAdd}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setCreateOpen(false)}
                  disabled={busy}
                >
                  Cancel
                </Button>
                <Button onClick={createCategory} disabled={busy || !name.trim()}>
                  Create
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

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
                    className="text-left min-w-0"
                    onClick={() =>
                      setSelectedCategory(
                        selectedCategory === category.id ? "" : category.id,
                      )
                    }
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="size-3 rounded-full shrink-0"
                        style={{ backgroundColor: category.color }}
                      />
                      <p className="font-medium truncate">{category.name}</p>
                    </div>
                    <p
                      className="text-xs text-onSurface-default-secondary mt-1 line-clamp-2"
                      title={category.description || undefined}
                    >
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
                <div className="flex items-center justify-between gap-2 pt-1">
                  <div className="min-w-0">
                    <Label
                      htmlFor={`auto-add-${category.id}`}
                      className="text-xs font-medium cursor-pointer"
                    >
                      Auto-add to new memories
                    </Label>
                    <p className="text-[11px] text-onSurface-default-tertiary">
                      Always tag new memories with this category
                    </p>
                  </div>
                  <Switch
                    id={`auto-add-${category.id}`}
                    checked={category.auto_add}
                    onCheckedChange={(checked) =>
                      toggleAutoAdd(category.id, checked)
                    }
                    disabled={busy}
                  />
                </div>
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
          <TooltipProvider>
            <div className="space-y-3">
              {memories.slice(0, 50).map((memory) => (
                <Card key={memory.id} className="border-memBorder-primary">
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-start justify-between gap-4">
                      <p className="text-sm min-w-0">{memory.memory}</p>
                      <div className="flex shrink-0 items-center gap-2">
                        <Select
                          value={manualCategoryByMemory[memory.id] ?? ""}
                          onValueChange={(value) =>
                            setManualCategoryByMemory((current) => ({
                              ...current,
                              [memory.id]: value,
                            }))
                          }
                        >
                          <SelectTrigger className="h-9 w-36">
                            <SelectValue placeholder="Assign…" />
                          </SelectTrigger>
                          <SelectContent>
                            {categories.map((category) => (
                              <SelectItem key={category.id} value={category.id}>
                                {category.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
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
                          <Wand2 className="size-3.5 mr-1" />
                          Classify
                        </Button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(memory.categories ?? []).length === 0 ? (
                        <Badge variant="outline" className="text-onSurface-default-tertiary">
                          Uncategorized
                        </Badge>
                      ) : (
                        memory.categories?.map((category) => (
                          <Tooltip key={category.id}>
                            <TooltipTrigger asChild>
                              <Badge
                                variant="outline"
                                className="gap-1.5 cursor-default"
                              >
                                <span
                                  className="size-2 rounded-full"
                                  style={{ backgroundColor: category.color }}
                                />
                                {category.name}
                                {category.source === "manual" ? (
                                  <span className="text-[10px] text-onSurface-default-tertiary">
                                    manual
                                  </span>
                                ) : category.source === "auto" ? (
                                  <span className="text-[10px] text-onSurface-default-tertiary">
                                    auto
                                  </span>
                                ) : (
                                  category.confidence !== null && (
                                    <span className="text-[10px] text-onSurface-default-tertiary">
                                      {Math.round(category.confidence * 100)}%
                                    </span>
                                  )
                                )}
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>
                              {category.source === "manual"
                                ? "Manually assigned"
                                : category.source === "auto"
                                  ? "Auto-added by category rule"
                                  : `AI · ${category.reason || "no reason given"}`}
                            </TooltipContent>
                          </Tooltip>
                        ))
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}
