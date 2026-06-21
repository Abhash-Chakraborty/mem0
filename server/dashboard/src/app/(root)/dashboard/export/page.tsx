"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { CATEGORY_ENDPOINTS, EXPORT_ENDPOINTS } from "@/utils/api-endpoints";
import { Category } from "@/types/api";

export default function ExportPage() {
  const { data: categories = [] } = useApiQuery<Category[]>(
    async () => (await api.get(CATEGORY_ENDPOINTS.BASE)).data ?? [],
    { errorToast: "Failed to load categories", initialData: [] },
  );

  const buildParams = (format: "json" | "csv") => {
    const form = document.getElementById(
      "export-form",
    ) as HTMLFormElement | null;
    const params = new URLSearchParams({ format });
    if (form) {
      const data = new FormData(form);
      for (const key of ["user_id", "agent_id", "run_id", "category_id"]) {
        const value = String(data.get(key) || "").trim();
        if (value) params.set(key, value);
      }
    }
    return params;
  };

  const download = async (format: "json" | "csv") => {
    const params = buildParams(format);
    const res = await api.get(`${EXPORT_ENDPOINTS.BASE}?${params.toString()}`, {
      responseType: "blob",
    });
    const blob = new Blob([res.data], {
      type: format === "json" ? "application/json" : "text/csv",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `abhash-memory-export.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat">Export</h1>
        <p className="text-sm text-onSurface-default-secondary mt-1">
          Download memories, metadata, and category assignments from this
          self-hosted instance.
        </p>
      </div>

      <Card className="border-memBorder-primary">
        <CardContent className="p-5">
          <form id="export-form" className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>User ID</Label>
              <Input name="user_id" placeholder="Optional" />
            </div>
            <div className="space-y-1.5">
              <Label>Agent ID</Label>
              <Input name="agent_id" placeholder="Optional" />
            </div>
            <div className="space-y-1.5">
              <Label>Run ID</Label>
              <Input name="run_id" placeholder="Optional" />
            </div>
            <div className="space-y-1.5">
              <Label>Category</Label>
              <select
                name="category_id"
                className="h-10 w-full rounded-md border border-memBorder-primary bg-surface-default-primary px-3 text-sm"
                defaultValue=""
              >
                <option value="">All categories</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </div>
          </form>

          <div className="mt-5 flex gap-3">
            <Button onClick={() => void download("json")}>
              <Download className="size-4 mr-2" />
              Download JSON
            </Button>
            <Button variant="outline" onClick={() => void download("csv")}>
              <Download className="size-4 mr-2" />
              Download CSV
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
