"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check, ChevronsUpDown, Plus, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { TENANCY_ENDPOINTS } from "@/utils/api-endpoints";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/error-message";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The project selector in the top bar.
 *
 * It sits above the content rather than in the sidebar because the project is
 * what every page on screen is showing - which memories, which requests, which
 * entities - and that context belongs next to the content it qualifies.
 */
export function ProjectSwitcher() {
  const { scope, projects, isLoading, switchProject, can } = useScope();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const sorted = useMemo(
    // The default project first, then alphabetical: it is the one that owns
    // pre-tenancy memories, so it is the one people look for.
    () =>
      [...projects].sort((a, b) => {
        if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
        return a.name.localeCompare(b.name);
      }),
    [projects],
  );

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const res = await api.post(TENANCY_ENDPOINTS.PROJECTS, {
        name: name.trim(),
        description: description.trim(),
      });
      toast.success(`Created ${res.data.name}`);
      setCreating(false);
      setName("");
      setDescription("");
      switchProject(res.data.id);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not create the project."));
    } finally {
      setSaving(false);
    }
  };

  if (isLoading && !scope) {
    return <Skeleton className="h-6 w-32 rounded-md" />;
  }
  if (!scope) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            className="flex items-center gap-1.5 rounded-md border border-memBorder-primary px-2 py-1 transition-colors hover:bg-surface-default-secondary-hover"
            aria-label="Switch project"
          >
            <span className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              Project
            </span>
            <span className="max-w-[180px] truncate typo-body-xs text-onSurface-default-primary">
              {scope.project_name}
            </span>
            <ChevronsUpDown className="size-3 shrink-0 text-onSurface-default-tertiary" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="w-72 border-memBorder-secondary bg-surface-default-primary font-fustat"
        >
          <div className="px-2 py-1.5 typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
            {scope.org_name}
          </div>
          {sorted.map((project) => (
            <DropdownMenuItem
              key={project.id}
              onClick={() =>
                project.id !== scope.project_id && switchProject(project.id)
              }
              className="cursor-pointer typo-body-sm text-onSurface-default-primary focus:bg-surface-default-tertiary-hover"
            >
              <Check
                className={cn(
                  "mr-2 size-4 shrink-0",
                  project.id === scope.project_id ? "opacity-100" : "opacity-0",
                )}
              />
              <span className="min-w-0 flex-1 truncate">{project.name}</span>
              {project.is_default && (
                <span className="ml-2 shrink-0 typo-caption-sm text-onSurface-default-tertiary">
                  default
                </span>
              )}
            </DropdownMenuItem>
          ))}
          {can("admin") && (
            <>
              <DropdownMenuSeparator className="bg-memBorder-primary" />
              <DropdownMenuItem
                onClick={() => setCreating(true)}
                className="cursor-pointer typo-body-sm text-onSurface-default-primary focus:bg-surface-default-tertiary-hover"
              >
                <Plus className="mr-2 size-4" />
                New project
              </DropdownMenuItem>
              <DropdownMenuItem
                asChild
                className="cursor-pointer typo-body-sm text-onSurface-default-primary focus:bg-surface-default-tertiary-hover"
              >
                <Link href="/dashboard/settings/general">
                  <Settings2 className="mr-2 size-4" />
                  Project settings
                </Link>
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-[460px]">
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              A separate memory namespace inside {scope.org_name}. Memories,
              entities, and requests do not cross between projects.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="project-name">Name</Label>
              <Input
                id="project-name"
                value={name}
                autoFocus
                placeholder="Staging"
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="project-description">Description</Label>
              <Textarea
                id="project-description"
                value={description}
                rows={2}
                placeholder="What this project is for."
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button onClick={create} disabled={saving || !name.trim()}>
              {saving ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
