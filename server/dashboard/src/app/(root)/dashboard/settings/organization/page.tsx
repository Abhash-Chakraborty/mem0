"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { TENANCY_ENDPOINTS } from "@/utils/api-endpoints";
import { useScope } from "@/lib/scope";
import { getErrorMessage } from "@/lib/error-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CopyInline } from "@/components/shared/copy-inline";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ReadOnlyNotice,
  SettingsField,
  SettingsHeader,
  SettingsSaveBar,
  SettingsSection,
  SettingsSkeleton,
} from "@/components/settings/settings-page";

export default function OrganizationSettingsPage() {
  const { scope, orgs, isLoading, can, reload } = useScope();

  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  useEffect(() => {
    if (scope) setName(scope.org_name);
  }, [scope]);

  const save = async () => {
    if (!scope) return;
    setSaving(true);
    try {
      await api.patch(TENANCY_ENDPOINTS.ORG_BY_ID(scope.org_id), {
        name: name.trim(),
      });
      await reload();
      toast.success("Organization updated");
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not save the organization."));
    } finally {
      setSaving(false);
    }
  };

  const destroy = async () => {
    if (!scope) return;
    try {
      await api.delete(TENANCY_ENDPOINTS.ORG_BY_ID(scope.org_id));
      toast.success("Organization deleted");
      // A hard reload rather than a scope refresh: the org the whole session is
      // pointed at no longer exists, so every cached id in memory is stale.
      window.location.href = "/dashboard/analytics";
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not delete the organization."));
    }
  };

  if (isLoading || !scope) return <SettingsSkeleton />;

  const editable = can("admin");
  const isOnlyOrg = orgs.length <= 1;

  return (
    <>
      <SettingsHeader
        title="Organization"
        description="Settings that apply to every project in this organization."
      />

      {!editable && <ReadOnlyNotice role={scope.role} />}

      <SettingsSection title="General">
        <SettingsField label="Name" htmlFor="org-name">
          <Input
            id="org-name"
            value={name}
            disabled={!editable}
            onChange={(e) => setName(e.target.value)}
          />
        </SettingsField>
        <SettingsField
          label="Slug"
          hint="What the X-Mem0-Org header accepts, alongside the ID."
        >
          <CopyInline value={scope.org_slug} />
        </SettingsField>
        <SettingsField label="Organization ID">
          <CopyInline value={scope.org_id} />
        </SettingsField>
      </SettingsSection>

      {can("owner") && (
        <SettingsSection
          title="Danger zone"
          description="This cannot be undone."
          className="border-surface-danger-primary"
        >
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="typo-body-sm text-onSurface-default-primary">
                Delete this organization
              </div>
              <p className="max-w-prose typo-caption-sm text-onSurface-default-tertiary">
                {isOnlyOrg
                  ? "This is the only organization on the instance, so it cannot be deleted — there would be no tenant left to resolve a request against."
                  : "Removes every project inside it, along with their memories, categories and API keys."}
              </p>
            </div>
            <Button
              variant="destructive"
              disabled={isOnlyOrg}
              onClick={() => setDeleting(true)}
            >
              <Trash2 className="mr-2 size-4" />
              Delete
            </Button>
          </div>
        </SettingsSection>
      )}

      <SettingsSaveBar
        dirty={name !== scope.org_name}
        saving={saving}
        onSave={save}
        onReset={() => setName(scope.org_name)}
      />

      <Dialog open={deleting} onOpenChange={setDeleting}>
        <DialogContent className="sm:max-w-[460px]">
          <DialogHeader>
            <DialogTitle>Delete {scope.org_name}?</DialogTitle>
            <DialogDescription>
              Every project, memory, category and API key inside it is removed.
              Type <span className="font-medium">{scope.org_name}</span> to
              confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            autoFocus
            placeholder={scope.org_name}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== scope.org_name}
              onClick={destroy}
            >
              Delete organization
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
