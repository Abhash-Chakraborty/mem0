"use client";

import { useState } from "react";
import { Download, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { CATEGORY_ENDPOINTS, EXPORT_ENDPOINTS } from "@/utils/api-endpoints";
import { Category } from "@/types/api";

const INSTANCE_SLUG = (
  process.env.NEXT_PUBLIC_INSTANCE_NAME || "abhash-memory"
)
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, "-")
  .replace(/(^-|-$)/g, "");

export default function ExportPage() {
  const { data: categories = [] } = useApiQuery<Category[]>(
    async () => (await api.get(CATEGORY_ENDPOINTS.BASE)).data ?? [],
    { errorToast: "Failed to load categories", initialData: [] },
  );

  const [userId, setUserId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [runId, setRunId] = useState("");
  const [categoryId, setCategoryId] = useState("all");
  const [busy, setBusy] = useState(false);
  const [previewCount, setPreviewCount] = useState<number | null>(null);

  const buildParams = (format: "json" | "csv") => {
    const params = new URLSearchParams({ format });
    if (userId.trim()) params.set("user_id", userId.trim());
    if (agentId.trim()) params.set("agent_id", agentId.trim());
    if (runId.trim()) params.set("run_id", runId.trim());
    if (categoryId && categoryId !== "all") params.set("category_id", categoryId);
    return params;
  };

  const preview = async () => {
    setBusy(true);
    try {
      const res = await api.get(
        `${EXPORT_ENDPOINTS.BASE}?${buildParams("json").toString()}`,
      );
      setPreviewCount(res.data?.total ?? 0);
    } catch (error) {
      toast({
        title: "Failed to preview export",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const download = async (format: "json" | "csv") => {
    setBusy(true);
    try {
      const res = await api.get(
        `${EXPORT_ENDPOINTS.BASE}?${buildParams(format).toString()}`,
        { responseType: "blob" },
      );
      const blob = new Blob([res.data], {
        type: format === "json" ? "application/json" : "text/csv",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `${INSTANCE_SLUG}-export-${stamp}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast({
        title: "Failed to export",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat">Export</h1>
        <p className="text-sm text-onSurface-default-secondary mt-1">
          Download memories, metadata, and category assignments from this
          self-hosted instance. Leave filters empty to export everything.
        </p>
      </div>

      <Card className="border-memBorder-primary">
        <CardContent className="p-5 space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>User ID</Label>
              <Input
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Agent ID</Label>
              <Input
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Run ID</Label>
              <Input
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Select value={categoryId} onValueChange={setCategoryId}>
                <SelectTrigger>
                  <SelectValue placeholder="All categories" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All categories</SelectItem>
                  {categories.map((category) => (
                    <SelectItem key={category.id} value={category.id}>
                      {category.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-memBorder-primary pt-4">
            <Button variant="outline" onClick={preview} disabled={busy}>
              <Eye className="size-4 mr-2" />
              Preview
            </Button>
            <Button onClick={() => void download("json")} disabled={busy}>
              <Download className="size-4 mr-2" />
              Download JSON
            </Button>
            <Button
              variant="outline"
              onClick={() => void download("csv")}
              disabled={busy}
            >
              <Download className="size-4 mr-2" />
              Download CSV
            </Button>
            {previewCount !== null && (
              <span className="text-sm text-onSurface-default-secondary">
                {previewCount} memor{previewCount === 1 ? "y" : "ies"} match
                {previewCount === 1 ? "es" : ""} these filters.
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
