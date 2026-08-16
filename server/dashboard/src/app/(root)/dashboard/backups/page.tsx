"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Archive,
  Download,
  Loader2,
  Play,
  RotateCcw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { BACKUP_ENDPOINTS } from "@/utils/api-endpoints";
import { Backup, BackupListResponse } from "@/types/api";
import { cn } from "@/lib/utils";

const RESTORE_CONFIRMATION = "restore";

function formatBytes(value: number): string {
  if (!value) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function StatusBadge({ backup }: { backup: Backup }) {
  if (backup.status === "completed") {
    return (
      <Badge
        variant="secondary"
        className="text-emerald-600 dark:text-emerald-400 gap-1"
      >
        {backup.verified_at && <ShieldCheck className="size-3" />}
        {backup.verified_at ? "Verified" : "Complete"}
      </Badge>
    );
  }
  if (backup.status === "running") {
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 className="size-3 animate-spin" />
        Running
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="text-red-600 dark:text-red-400">
      Failed
    </Badge>
  );
}

export default function BackupsPage() {
  const [busy, setBusy] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<Backup | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState("");

  const backupsQuery = useApiQuery<BackupListResponse | undefined>(
    async () => (await api.get(BACKUP_ENDPOINTS.BASE)).data,
    { errorToast: "Failed to load backups" },
  );

  const data = backupsQuery.data;
  const backups = data?.backups ?? [];
  const toolsMissing = (data?.missing_tools ?? []).length > 0;

  const runBackup = async () => {
    setBusy(true);
    try {
      await api.post(BACKUP_ENDPOINTS.BASE);
      toast({ title: "Backup complete", variant: "success" });
      await backupsQuery.refetch();
    } catch (error) {
      toast({
        title: "Backup failed",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const deleteBackup = async (backup: Backup) => {
    setBusy(true);
    try {
      await api.delete(BACKUP_ENDPOINTS.BY_ID(backup.id));
      toast({ title: "Backup deleted", variant: "success" });
      await backupsQuery.refetch();
    } catch (error) {
      toast({
        title: "Could not delete backup",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const confirmRestore = async () => {
    if (!restoreTarget) return;
    setBusy(true);
    try {
      await api.post(BACKUP_ENDPOINTS.RESTORE(restoreTarget.id), {
        confirm: true,
      });
      toast({
        title: "Restore complete",
        description: "Restart the API so cached state is rebuilt.",
        variant: "success",
      });
      setRestoreTarget(null);
      setRestoreConfirm("");
      await backupsQuery.refetch();
    } catch (error) {
      toast({
        title: "Restore failed",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const download = (backup: Backup, part: "vector" | "app") => {
    // Goes through the API client's base URL so the auth header is applied by
    // the same interceptor as every other call.
    void api
      .get(BACKUP_ENDPOINTS.DOWNLOAD(backup.id, part), { responseType: "blob" })
      .then((res) => {
        const url = URL.createObjectURL(res.data as Blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${backup.filename}.${part}`;
        link.click();
        URL.revokeObjectURL(url);
      })
      .catch((error) =>
        toast({
          title: "Download failed",
          description: getErrorMessage(error),
          variant: "destructive",
        }),
      );
  };

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-onSurface-default-primary">
            Backups
          </h1>
          <p className="text-sm text-onSurface-default-tertiary mt-1">
            Snapshots of the memory store and application database, taken
            together. Keeping the newest {data?.retention_count ?? 7}.
          </p>
        </div>
        <Button onClick={runBackup} disabled={busy || toolsMissing}>
          {busy ? (
            <Loader2 className="size-4 mr-2 animate-spin" />
          ) : (
            <Play className="size-4 mr-2" />
          )}
          Back up now
        </Button>
      </div>

      {toolsMissing && (
        <Card className="border-amber-500/40">
          <CardContent className="flex items-start gap-3 p-4">
            <AlertTriangle className="size-5 shrink-0 text-amber-500 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-onSurface-default-primary">
                Backups are unavailable on this image
              </p>
              <p className="text-onSurface-default-tertiary mt-1">
                {data?.missing_tools.join(", ")} could not be found. Rebuild the
                API image with the Postgres client tools installed, then reload
                this page.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {backupsQuery.isLoading ? (
        <TableSkeleton />
      ) : backups.length === 0 ? (
        <EmptyState
          title="No backups yet"
          description="Take one now, and restore it once to prove it works before you need it."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {backups.map((backup) => (
            <Card key={backup.id}>
              <CardContent className="flex flex-wrap items-center gap-4 p-4">
                <Archive className="size-5 shrink-0 text-onSurface-default-tertiary" />

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-onSurface-default-primary truncate">
                      {backup.filename}
                    </p>
                    <StatusBadge backup={backup} />
                    {backup.kind === "scheduled" && (
                      <Badge variant="outline">Scheduled</Badge>
                    )}
                  </div>
                  <p className="text-xs text-onSurface-default-tertiary mt-1">
                    {backup.started_at
                      ? new Date(backup.started_at).toLocaleString()
                      : "—"}
                    {backup.status === "completed" &&
                      ` · ${formatBytes(backup.size_bytes)}`}
                  </p>
                  {backup.error && (
                    <p className="text-xs text-onSurface-danger-primary mt-1 break-words">
                      {backup.error}
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  {backup.status === "completed" && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => download(backup, "vector")}
                        title="Download memory store dump"
                      >
                        <Download className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setRestoreTarget(backup)}
                        disabled={busy}
                        title="Restore this snapshot"
                      >
                        <RotateCcw className="size-4" />
                      </Button>
                    </>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deleteBackup(backup)}
                    disabled={busy}
                    title="Delete"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={restoreTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRestoreTarget(null);
            setRestoreConfirm("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore this backup?</DialogTitle>
            <DialogDescription>
              This replaces every memory, category and webhook currently in the
              instance with the contents of{" "}
              <span className="font-mono">{restoreTarget?.filename}</span>.
              Anything created since that snapshot is lost.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="restore-confirm">
              Type <span className="font-mono">{RESTORE_CONFIRMATION}</span> to
              confirm
            </Label>
            <Input
              id="restore-confirm"
              value={restoreConfirm}
              onChange={(e) => setRestoreConfirm(e.target.value)}
              autoComplete="off"
            />
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRestoreTarget(null);
                setRestoreConfirm("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={confirmRestore}
              disabled={busy || restoreConfirm !== RESTORE_CONFIRMATION}
            >
              {busy && <Loader2 className="size-4 mr-2 animate-spin" />}
              Restore
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
