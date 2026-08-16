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
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { CATEGORY_ENDPOINTS, EXPORT_ENDPOINTS } from "@/utils/api-endpoints";
import { Category, Memory } from "@/types/api";
import { INSTANCE_SLUG } from "@/lib/instance";

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
  const [previewRows, setPreviewRows] = useState<Memory[]>([]);

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
      const params = buildParams("json");
      params.set("limit", "10");
      const res = await api.get<{
        total: number;
        returned: number;
        memories: Memory[];
      }>(`${EXPORT_ENDPOINTS.BASE}?${params.toString()}`);
      setPreviewCount(res.data?.total ?? 0);
      setPreviewRows(res.data?.memories ?? []);
    } catch (error) {
      setPreviewRows([]);
      setPreviewCount(null);
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

          {previewCount !== null && (
            <div className="space-y-2 border-t border-memBorder-primary pt-4">
              {previewCount === 0 ? (
                <p className="text-sm text-onSurface-default-tertiary">
                  No memories match these filters.
                </p>
              ) : (
                <>
                  <p className="text-xs text-onSurface-default-tertiary">
                    Showing {previewRows.length} of {previewCount} — first rows
                    of what will be exported.
                  </p>
                  {previewRows.map((memory) => (
                    <div
                      key={memory.id}
                      className="rounded-md border border-memBorder-primary p-3 space-y-2"
                    >
                      <p className="text-sm">{memory.memory}</p>
                      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-onSurface-default-tertiary">
                        {memory.user_id && (
                          <Badge variant="outline">user: {memory.user_id}</Badge>
                        )}
                        {memory.agent_id && (
                          <Badge variant="outline">
                            agent: {memory.agent_id}
                          </Badge>
                        )}
                        {memory.run_id && (
                          <Badge variant="outline">run: {memory.run_id}</Badge>
                        )}
                        {(memory.categories ?? []).map((category) => (
                          <Badge
                            key={category.id}
                            variant="outline"
                            className="gap-1"
                          >
                            <span
                              className="size-2 rounded-full"
                              style={{ backgroundColor: category.color }}
                            />
                            {category.name}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
