"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Building2,
  Check,
  ChevronsUpDown,
  Plus,
  Settings2,
} from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The organization identity in the sidebar header, doubling as its switcher.
 *
 * A single-org instance - which most self-hosted ones are - still shows the
 * name but no chevron, so the control does not advertise a choice that does
 * not exist.
 */
export function OrgSwitcher({ collapsed }: { collapsed: boolean }) {
  const { scope, orgs, isLoading, switchOrg } = useScope();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const res = await api.post(TENANCY_ENDPOINTS.ORGS, { name: name.trim() });
      toast.success(`Created ${res.data.name}`);
      setCreating(false);
      setName("");
      switchOrg(res.data.id);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not create the organization."));
    } finally {
      setSaving(false);
    }
  };

  if (isLoading && !scope) {
    return collapsed ? (
      <Skeleton className="size-7 rounded-md" />
    ) : (
      <div className="flex w-full items-center gap-2">
        <Skeleton className="size-7 shrink-0 rounded-md" />
        <Skeleton className="h-3 w-24" />
      </div>
    );
  }

  const mark = (
    <div className="grid size-7 shrink-0 place-items-center rounded-md bg-surface-default-tertiary">
      <Building2 className="size-4 text-onSurface-default-primary" />
    </div>
  );

  if (collapsed) {
    return <div className="flex justify-center">{mark}</div>;
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            className="flex w-full items-center gap-2 rounded-md p-1 text-left transition-colors hover:bg-surface-default-secondary-hover"
            aria-label="Switch organization"
          >
            {mark}
            <span className="min-w-0 flex-1 truncate typo-body-xs text-onSurface-default-primary">
              {scope?.org_name ?? "Organization"}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 text-onSurface-default-tertiary" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="w-60 border-memBorder-secondary bg-surface-default-primary font-fustat"
        >
          <div className="px-2 py-1.5 typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
            Organizations
          </div>
          {orgs.map((org) => (
            <DropdownMenuItem
              key={org.id}
              onClick={() => org.id !== scope?.org_id && switchOrg(org.id)}
              className="cursor-pointer typo-body-sm text-onSurface-default-primary focus:bg-surface-default-tertiary-hover"
            >
              <Check
                className={cn(
                  "mr-2 size-4 shrink-0",
                  org.id === scope?.org_id ? "opacity-100" : "opacity-0",
                )}
              />
              <span className="min-w-0 flex-1 truncate">{org.name}</span>
              <span className="ml-2 shrink-0 typo-caption-sm text-onSurface-default-tertiary">
                {org.role}
              </span>
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator className="bg-memBorder-primary" />
          <DropdownMenuItem
            onClick={() => setCreating(true)}
            className="cursor-pointer typo-body-sm text-onSurface-default-primary focus:bg-surface-default-tertiary-hover"
          >
            <Plus className="mr-2 size-4" />
            New organization
          </DropdownMenuItem>
          <DropdownMenuItem
            asChild
            className="cursor-pointer typo-body-sm text-onSurface-default-primary focus:bg-surface-default-tertiary-hover"
          >
            <Link href="/dashboard/settings/members">
              <Settings2 className="mr-2 size-4" />
              Members &amp; access
            </Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>New organization</DialogTitle>
            <DialogDescription>
              A separate tenant with its own projects, members, and memories.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="org-name">Name</Label>
            <Input
              id="org-name"
              value={name}
              autoFocus
              placeholder="Acme Labs"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void create()}
            />
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
