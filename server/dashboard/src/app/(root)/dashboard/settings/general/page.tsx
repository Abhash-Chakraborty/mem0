"use client";

import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS, TENANCY_ENDPOINTS } from "@/utils/api-endpoints";
import { rankOf, useScope } from "@/lib/scope";
import { getErrorMessage } from "@/lib/error-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CopyInline } from "@/components/shared/copy-inline";
import {
  ReadOnlyNotice,
  SettingsField,
  SettingsHeader,
  SettingsSaveBar,
  SettingsSection,
  SettingsSkeleton,
} from "@/components/settings/settings-page";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

interface ProjectMember {
  user_id: string;
  name: string;
  email: string;
  /** Always the organization role. */
  role: string;
  /** The narrowing row, if one exists. */
  project_role: string | null;
  /** What `role` narrowed to, which is what actually applies here. */
  effective_role: string | null;
  joined_at: string;
}

const ROLES = ["reader", "member", "admin", "owner"] as const;

type DangerAction = "memories" | "project" | null;

export default function ProjectGeneralPage() {
  const { scope, projects, isLoading, can, reload, switchProject } = useScope();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [danger, setDanger] = useState<DangerAction>(null);
  const [confirmText, setConfirmText] = useState("");

  const project = projects.find((p) => p.id === scope?.project_id);
  const projectId = scope?.project_id;

  useEffect(() => {
    if (project) {
      setName(project.name);
      setDescription(project.description);
    }
  }, [project]);

  const loadMembers = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await api.get<ProjectMember[]>(
        TENANCY_ENDPOINTS.PROJECT_MEMBERS(projectId),
      );
      setMembers(res.data);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load project access."));
    }
  }, [projectId]);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  const save = async () => {
    if (!projectId) return;
    setSaving(true);
    try {
      await api.patch(TENANCY_ENDPOINTS.PROJECT_BY_ID(projectId), {
        name: name.trim(),
        description: description.trim(),
      });
      await reload();
      toast.success("Project updated");
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not save the project."));
    } finally {
      setSaving(false);
    }
  };

  const setProjectRole = async (member: ProjectMember, role: string) => {
    if (!projectId) return;
    try {
      if (role === "__inherit__") {
        await api.delete(
          TENANCY_ENDPOINTS.PROJECT_MEMBER(projectId, member.user_id),
        );
      } else {
        await api.put(
          TENANCY_ENDPOINTS.PROJECT_MEMBER(projectId, member.user_id),
          { role },
        );
      }
      await loadMembers();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not change that access level."));
    }
  };

  const closeDanger = () => {
    setDanger(null);
    setConfirmText("");
  };

  const deleteAllMemories = async () => {
    try {
      // No entity filter, so this walks every entity in the project. The
      // server refuses a filterless delete_all, so the sweep is per-entity.
      const listed = await api.get(MEMORY_ENDPOINTS.BASE);
      const users = new Set<string>();
      for (const memory of listed.data?.results ?? []) {
        if (memory.user_id) users.add(memory.user_id);
      }
      for (const userId of users) {
        await api.delete(
          `${MEMORY_ENDPOINTS.BASE}?user_id=${encodeURIComponent(userId)}`,
        );
      }
      toast.success(
        users.size === 0
          ? "There were no memories to delete."
          : `Deleted memories for ${users.size} ${users.size === 1 ? "user" : "users"}.`,
      );
      closeDanger();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not delete the memories."));
    }
  };

  const deleteProject = async () => {
    if (!projectId) return;
    try {
      await api.delete(TENANCY_ENDPOINTS.PROJECT_BY_ID(projectId));
      toast.success("Project deleted");
      const fallback = projects.find((p) => p.is_default);
      if (fallback) switchProject(fallback.id);
      else await reload();
      closeDanger();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not delete the project."));
    }
  };

  if (isLoading || !scope) return <SettingsSkeleton />;

  const dirty =
    project !== undefined &&
    (name !== project.name || description !== project.description);
  const editable = can("admin");
  const confirmWord = danger === "project" ? scope.project_name : "delete";

  return (
    <>
      <SettingsHeader
        title="Project settings"
        description={`General settings for ${scope.project_name} in ${scope.org_name}.`}
      />

      {!editable && <ReadOnlyNotice role={scope.role} />}

      <SettingsSection title="General">
        <SettingsField label="Name" htmlFor="project-name">
          <Input
            id="project-name"
            value={name}
            disabled={!editable}
            onChange={(e) => setName(e.target.value)}
          />
        </SettingsField>
        <SettingsField
          label="Description"
          htmlFor="project-description"
          hint="Only shown here and in the project switcher."
        >
          <Textarea
            id="project-description"
            rows={2}
            value={description}
            disabled={!editable}
            onChange={(e) => setDescription(e.target.value)}
          />
        </SettingsField>
        <SettingsField
          label="Project ID"
          hint="What an API key is bound to, and what the X-Mem0-Project header accepts."
        >
          <CopyInline value={scope.project_id} />
        </SettingsField>
      </SettingsSection>

      <SettingsSection
        title="Access"
        description="A project role can only narrow what someone already has in the organization — it never grants more."
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Member</TableHead>
                <TableHead className="w-32">Org role</TableHead>
                <TableHead className="w-48">On this project</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => (
                <TableRow key={member.user_id}>
                  <TableCell>
                    <div className="text-onSurface-default-primary">
                      {member.name}
                    </div>
                    <div className="typo-caption-sm text-onSurface-default-tertiary">
                      {member.email}
                    </div>
                  </TableCell>
                  <TableCell className="text-onSurface-default-secondary">
                    {member.role}
                  </TableCell>
                  <TableCell>
                    {editable ? (
                      <Select
                        value={member.project_role ?? "__inherit__"}
                        onValueChange={(role) => setProjectRole(member, role)}
                      >
                        <SelectTrigger className="h-8">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__inherit__">
                            Same as organization
                          </SelectItem>
                          {ROLES.filter(
                            (r) => rankOf(r) <= rankOf(member.role),
                          ).map((role) => (
                            <SelectItem key={role} value={role}>
                              {role}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <span className="typo-body-sm text-onSurface-default-secondary">
                        {member.project_role ?? "same as organization"}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </SettingsSection>

      {can("admin") && (
        <SettingsSection
          title="Danger zone"
          description="These actions cannot be undone."
          className="border-surface-danger-primary"
        >
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="typo-body-sm text-onSurface-default-primary">
                Delete all memories
              </div>
              <p className="typo-caption-sm text-onSurface-default-tertiary">
                Empties this project. Categories and settings are kept.
              </p>
            </div>
            <Button variant="destructive" onClick={() => setDanger("memories")}>
              Delete memories
            </Button>
          </div>

          {can("owner") && !scope.is_default_project && (
            <div className="flex items-center justify-between gap-6 border-t border-memBorder-primary pt-4">
              <div>
                <div className="typo-body-sm text-onSurface-default-primary">
                  Delete this project
                </div>
                <p className="typo-caption-sm text-onSurface-default-tertiary">
                  Removes the project, its memories, its categories, and any API
                  keys bound to it.
                </p>
              </div>
              <Button
                variant="destructive"
                onClick={() => setDanger("project")}
              >
                <Trash2 className="mr-2 size-4" />
                Delete project
              </Button>
            </div>
          )}

          {scope.is_default_project && (
            <p className="border-t border-memBorder-primary pt-4 typo-caption-sm text-onSurface-default-tertiary">
              The default project cannot be deleted — it holds every memory
              recorded before this instance had projects.
            </p>
          )}
        </SettingsSection>
      )}

      <SettingsSaveBar
        dirty={dirty}
        saving={saving}
        onSave={save}
        onReset={() => {
          setName(project?.name ?? "");
          setDescription(project?.description ?? "");
        }}
      />

      <Dialog
        open={danger !== null}
        onOpenChange={(open) => !open && closeDanger()}
      >
        <DialogContent className="sm:max-w-[460px]">
          <DialogHeader>
            <DialogTitle>
              {danger === "project"
                ? `Delete ${scope.project_name}?`
                : "Delete every memory in this project?"}
            </DialogTitle>
            <DialogDescription>
              {danger === "project"
                ? "Its memories, categories and API keys go with it."
                : "Every memory in this project is removed. Categories and settings stay."}{" "}
              Type <span className="font-medium">{confirmWord}</span> to
              confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            autoFocus
            placeholder={confirmWord}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={closeDanger}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== confirmWord}
              onClick={danger === "project" ? deleteProject : deleteAllMemories}
            >
              {danger === "project" ? "Delete project" : "Delete memories"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
