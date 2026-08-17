"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { TENANCY_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { useScope } from "@/lib/scope";

/**
 * Edit one section of `projects.settings`.
 *
 * Each settings page owns a section, and the server merges section-wise, so
 * two pages open in two tabs cannot clobber each other's section. Draft state
 * is local until saved; `dirty` drives the save bar.
 *
 * Mirrors the defaults in server/project_settings.py. They are duplicated
 * rather than fetched because the form needs them before the first response,
 * and a form that renders empty then jumps is worse than one that starts right.
 */

export interface ExtractionSettings {
  user_instructions: string;
  agent_instructions: string;
  multilingual: boolean;
  infer: boolean;
}

export interface RetentionSettings {
  default_expiration_days: number | null;
  decay_enabled: boolean;
  dream_enabled: boolean;
  trace_retention_days: number;
}

export interface CategorySettings {
  auto_classify: boolean;
  disabled_defaults: string[];
}

export interface ProjectSettings {
  extraction: ExtractionSettings;
  retention: RetentionSettings;
  categories: CategorySettings;
}

export const SETTINGS_DEFAULTS: ProjectSettings = {
  extraction: {
    user_instructions: "",
    agent_instructions: "",
    multilingual: false,
    infer: true,
  },
  retention: {
    default_expiration_days: null,
    decay_enabled: false,
    dream_enabled: false,
    trace_retention_days: 30,
  },
  categories: {
    auto_classify: true,
    disabled_defaults: [],
  },
};

export function useProjectSettings<K extends keyof ProjectSettings>(
  section: K,
) {
  const { scope, reload } = useScope();
  const projectId = scope?.project_id;

  const [saved, setSaved] = useState<ProjectSettings[K]>(
    SETTINGS_DEFAULTS[section],
  );
  const [draft, setDraft] = useState<ProjectSettings[K]>(
    SETTINGS_DEFAULTS[section],
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await api.get(TENANCY_ENDPOINTS.PROJECT_BY_ID(projectId));
      const stored = (res.data.settings ?? {})[section] ?? {};
      const merged = { ...SETTINGS_DEFAULTS[section], ...stored };
      setSaved(merged);
      setDraft(merged);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load project settings."));
    } finally {
      setLoading(false);
    }
  }, [projectId, section]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(saved),
    [draft, saved],
  );

  const set = useCallback(
    <F extends keyof ProjectSettings[K]>(
      field: F,
      value: ProjectSettings[K][F],
    ) => {
      setDraft((current) => ({ ...current, [field]: value }));
    },
    [],
  );

  const save = useCallback(async () => {
    if (!projectId) return;
    setSaving(true);
    try {
      const res = await api.patch(TENANCY_ENDPOINTS.PROJECT_BY_ID(projectId), {
        settings: { [section]: draft },
      });
      // Trust the response over the draft: the server drops unknown keys, so
      // reading back is the only way to know what was actually stored.
      const stored = (res.data.settings ?? {})[section] ?? {};
      const merged = { ...SETTINGS_DEFAULTS[section], ...stored };
      setSaved(merged);
      setDraft(merged);
      await reload();
      toast.success("Settings saved");
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not save these settings."));
    } finally {
      setSaving(false);
    }
  }, [projectId, section, draft, reload]);

  const discard = useCallback(() => setDraft(saved), [saved]);

  return { draft, set, save, discard, dirty, saving, loading, reload: load };
}
