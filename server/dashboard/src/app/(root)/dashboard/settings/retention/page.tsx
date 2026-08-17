"use client";

import { useScope } from "@/lib/scope";
import { useProjectSettings } from "@/hooks/use-project-settings";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  ReadOnlyNotice,
  SettingsField,
  SettingsHeader,
  SettingsSaveBar,
  SettingsSection,
  SettingsSkeleton,
  SettingsToggleRow,
} from "@/components/settings/settings-page";

/**
 * Retention settings.
 *
 * Three controls with three different fates, and the page says which is which
 * rather than presenting them as equals. Expiry is enforced by the core today.
 * Decay and Dream are enforced by this server's own lifecycle layer, because
 * the OSS core rejects `decay=True` outright and has no concept of synthesis.
 */
export default function RetentionSettingsPage() {
  const { scope, can } = useScope();
  const { draft, set, save, discard, dirty, saving, loading } =
    useProjectSettings("retention");

  const editable = can("admin");

  if (loading || !scope) return <SettingsSkeleton />;

  const days = draft.default_expiration_days;

  return (
    <>
      <SettingsHeader
        title="Retention"
        description="How long memories live in this project, and what happens to them as they age."
      />

      {!editable && <ReadOnlyNotice role={scope.role} />}

      <SettingsSection
        title="Expiry"
        description="Applied when an add does not carry its own expiration date. Changing this does not touch memories that already exist."
      >
        <SettingsToggleRow
          label="Expire new memories"
          description="Off, memories in this project never expire."
          control={
            <Switch
              checked={days !== null}
              disabled={!editable}
              onCheckedChange={(on) =>
                set("default_expiration_days", on ? 90 : null)
              }
              aria-label="Expire new memories"
            />
          }
        />
        {days !== null && (
          <SettingsField
            label="Expire after"
            htmlFor="expiration-days"
            hint="Between 1 and 3650 days."
          >
            <div className="flex items-center gap-2">
              <Input
                id="expiration-days"
                type="number"
                min={1}
                max={3650}
                className="w-28"
                value={days}
                disabled={!editable}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10);
                  set(
                    "default_expiration_days",
                    Number.isNaN(next) ? 1 : Math.min(3650, Math.max(1, next)),
                  );
                }}
              />
              <span className="typo-body-sm text-onSurface-default-tertiary">
                days
              </span>
            </div>
          </SettingsField>
        )}
      </SettingsSection>

      <SettingsSection
        title="Decay"
        description="Ranks memories that have not been recalled in a long time below ones that have, instead of deleting them. Nothing is ever removed by decay."
      >
        <SettingsToggleRow
          label="Rank stale memories lower"
          description="Search scores are multiplied by a factor between 0.3× and 1.5× based on how recently and how often a memory has been recalled. Because the floor is 0.3×, anything that would have surfaced without decay can still surface with it — only the order changes."
          control={
            <Switch
              checked={draft.decay_enabled}
              disabled={!editable}
              onCheckedChange={(v) => set("decay_enabled", v)}
              aria-label="Rank stale memories lower"
            />
          }
        />
        {draft.decay_enabled && (
          <div className="rounded-md border border-memBorder-primary bg-surface-default-secondary p-3">
            <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              How the bias falls off
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 typo-caption-sm sm:grid-cols-3">
              {[
                ["Just recalled", "1.5×"],
                ["Recalled today", "1.4×"],
                ["Idle a few days", "1.0×"],
                ["Idle two weeks", "0.6×"],
                ["Idle a month", "0.4×"],
                ["Idle three months", "0.3× (floor)"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-2">
                  <dt className="text-onSurface-default-tertiary">{label}</dt>
                  <dd className="tabular-nums text-onSurface-default-secondary">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </SettingsSection>

      <SettingsSection
        title="Request traces"
        description="How long the Requests page keeps its history. Traces store request bodies, so this is the setting that governs how large that table can grow."
      >
        <SettingsField
          label="Keep traces for"
          htmlFor="trace-days"
          hint="Set to 0 to keep them forever — reasonable on a quiet instance, expensive on a busy one."
        >
          <div className="flex items-center gap-2">
            <Input
              id="trace-days"
              type="number"
              min={0}
              max={3650}
              className="w-28"
              value={draft.trace_retention_days ?? 30}
              disabled={!editable}
              onChange={(e) => {
                const next = Number.parseInt(e.target.value, 10);
                set(
                  "trace_retention_days",
                  Number.isNaN(next) ? 0 : Math.min(3650, Math.max(0, next)),
                );
              }}
            />
            <span className="typo-body-sm text-onSurface-default-tertiary">
              days
            </span>
          </div>
        </SettingsField>
      </SettingsSection>

      <SettingsSection
        title="Dream"
        description="A scheduled pass that consolidates this project's memories: superseding contradicted facts, merging duplicates, and drawing out patterns across many memories."
      >
        <SettingsToggleRow
          label="Run synthesis"
          description="Every action Dream takes is recorded and reversible. Nothing is deleted — superseded memories stay readable and keep their history."
          control={
            <Switch
              checked={draft.dream_enabled}
              disabled={!editable}
              onCheckedChange={(v) => set("dream_enabled", v)}
              aria-label="Run synthesis"
            />
          }
        />
      </SettingsSection>

      <SettingsSaveBar
        dirty={dirty}
        saving={saving}
        onSave={save}
        onReset={discard}
      />
    </>
  );
}
