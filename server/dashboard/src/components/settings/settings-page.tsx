"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The shared furniture of a settings page: title, sections, and a save bar.
 *
 * Seven pages share this so the "unsaved changes" affordance behaves the same
 * everywhere. A settings page where saving works differently per page is how
 * people lose edits.
 */

export function SettingsHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="mb-6">
      <h1 className="typo-heading-md text-onSurface-default-primary">
        {title}
      </h1>
      {description && (
        <p className="mt-1 max-w-prose typo-body-sm text-onSurface-default-tertiary">
          {description}
        </p>
      )}
    </header>
  );
}

export function SettingsSection({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("mb-6", className)}>
      <CardHeader className="pb-3">
        <CardTitle className="typo-body-md">{title}</CardTitle>
        {description && (
          <p className="max-w-prose typo-body-sm text-onSurface-default-tertiary">
            {description}
          </p>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  );
}

export function SettingsField({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={htmlFor}
        className="typo-body-sm text-onSurface-default-primary"
      >
        {label}
      </label>
      {children}
      {hint && (
        <p className="max-w-prose typo-caption-sm text-onSurface-default-tertiary">
          {hint}
        </p>
      )}
    </div>
  );
}

/**
 * A row for a boolean setting: label and explanation on the left, control right.
 * The whole row is not clickable — only the control is — so reading the
 * explanation cannot accidentally flip the thing it explains.
 */
export function SettingsToggleRow({
  label,
  description,
  control,
}: {
  label: string;
  description?: string;
  control: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <div className="typo-body-sm text-onSurface-default-primary">
          {label}
        </div>
        {description && (
          <p className="mt-0.5 max-w-prose typo-caption-sm text-onSurface-default-tertiary">
            {description}
          </p>
        )}
      </div>
      <div className="shrink-0 pt-0.5">{control}</div>
    </div>
  );
}

/**
 * The save bar. Sticks to the bottom of the viewport only while there are
 * changes to save, so it never occupies space it has not earned.
 */
export function SettingsSaveBar({
  dirty,
  saving,
  onSave,
  onReset,
}: {
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onReset?: () => void;
}) {
  if (!dirty) return null;
  return (
    <div className="sticky bottom-0 z-10 -mx-1 flex items-center justify-between gap-4 rounded-lg border border-memBorder-secondary bg-surface-default-primary px-4 py-3 shadow-lg">
      <span className="typo-body-sm text-onSurface-default-secondary">
        You have unsaved changes.
      </span>
      <div className="flex gap-2">
        {onReset && (
          <Button variant="ghost" size="sm" onClick={onReset} disabled={saving}>
            Discard
          </Button>
        )}
        <Button size="sm" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

export function SettingsSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

/** Shown in place of controls when the caller may look but not change. */
export function ReadOnlyNotice({ role }: { role: string }) {
  return (
    <p className="mb-6 rounded-md border border-memBorder-primary bg-surface-default-secondary px-3 py-2 typo-body-sm text-onSurface-default-tertiary">
      You have the <span className="font-medium">{role}</span> role here, so
      these settings are read-only.
    </p>
  );
}
