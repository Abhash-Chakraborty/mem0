"use client";

import { useState } from "react";
import { Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useScope } from "@/lib/scope";
import { getErrorMessage } from "@/lib/error-message";
import { useProjectSettings } from "@/hooks/use-project-settings";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  SettingsHeader,
  SettingsSaveBar,
  SettingsSection,
  SettingsSkeleton,
  SettingsToggleRow,
} from "@/components/settings/settings-page";

/**
 * Extraction settings.
 *
 * The USER / AGENT split matches how the core resolves instructions: an add
 * carrying only an agent id uses the agent set, anything else uses the user
 * set, and an add carrying both gets the two concatenated. That rule is stated
 * on the page rather than left to be discovered, because a set of instructions
 * that silently never applies is the failure people hit here.
 */

const EXAMPLE = {
  kept: [
    "Prefers dark mode across all apps",
    "Allergic to shellfish",
    "Works in the Europe/Berlin timezone",
  ],
  ignored: [
    "hey, are you there?",
    "thanks, that worked",
    "let me check and get back to you",
  ],
};

export default function ExtractionSettingsPage() {
  const { scope, can } = useScope();
  const { draft, set, save, discard, dirty, saving, loading } =
    useProjectSettings("extraction");

  const [guiding, setGuiding] = useState(false);
  const [useCase, setUseCase] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [proposal, setProposal] = useState<string | null>(null);
  const [target, setTarget] = useState<
    "user_instructions" | "agent_instructions"
  >("user_instructions");

  const editable = can("admin");

  const generate = async () => {
    if (!useCase.trim()) return;
    setDrafting(true);
    try {
      const res = await api.post(MEMORY_ENDPOINTS.GENERATE_INSTRUCTIONS, {
        use_case: useCase.trim(),
      });
      const text = res.data?.custom_instructions ?? "";
      if (!text) {
        toast.error("The model did not return any instructions.");
        return;
      }
      // Never written straight to the field: instructions decide what is kept
      // forever, so they get read before they take effect.
      setProposal(text);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not draft instructions."));
    } finally {
      setDrafting(false);
    }
  };

  const accept = () => {
    if (proposal) set(target, proposal);
    setProposal(null);
    setGuiding(false);
    setUseCase("");
  };

  if (loading || !scope) return <SettingsSkeleton />;

  return (
    <>
      <SettingsHeader
        title="Extraction"
        description="What this project keeps from a conversation, and how it is worded."
      />

      {!editable && <ReadOnlyNotice role={scope.role} />}

      <SettingsSection
        title="Custom instructions"
        description="Instructions are passed to the model that decides which facts are worth keeping. An add with only an agent ID uses the agent set; anything else uses the user set. An add carrying both gets both."
      >
        <Tabs defaultValue="user">
          <div className="flex items-center justify-between gap-4">
            <TabsList>
              <TabsTrigger value="user">User</TabsTrigger>
              <TabsTrigger value="agent">Agent</TabsTrigger>
            </TabsList>
            {editable && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setGuiding(true)}
              >
                <Wand2 className="mr-2 size-4" />
                Draft from a use case
              </Button>
            )}
          </div>

          <TabsContent value="user" className="mt-4">
            <Textarea
              aria-label="User extraction instructions"
              rows={8}
              value={draft.user_instructions}
              disabled={!editable}
              placeholder="e.g. Record stable preferences, constraints, and facts about the person. Ignore small talk and anything only true for this conversation."
              onChange={(e) => set("user_instructions", e.target.value)}
            />
            <p className="mt-2 typo-caption-sm text-onSurface-default-tertiary">
              Applied when the add carries a user ID. Leave empty to use the
              instance default.
            </p>
          </TabsContent>

          <TabsContent value="agent" className="mt-4">
            <Textarea
              aria-label="Agent extraction instructions"
              rows={8}
              value={draft.agent_instructions}
              disabled={!editable}
              placeholder="e.g. Record what the agent learned about its own tools, failures, and successful strategies. Ignore per-turn reasoning."
              onChange={(e) => set("agent_instructions", e.target.value)}
            />
            <p className="mt-2 typo-caption-sm text-onSurface-default-tertiary">
              Applied when the add carries an agent ID and no user ID.
            </p>
          </TabsContent>
        </Tabs>
      </SettingsSection>

      <SettingsSection
        title="What this looks like"
        description="A rough guide to the split these instructions are asking for."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-2 typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              Kept
            </div>
            <ul className="flex flex-col gap-1.5">
              {EXAMPLE.kept.map((line) => (
                <li
                  key={line}
                  className="rounded-md border border-memBorder-primary bg-surface-default-secondary px-3 py-1.5 typo-body-sm text-onSurface-default-primary"
                >
                  {line}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-2 typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              Ignored
            </div>
            <ul className="flex flex-col gap-1.5">
              {EXAMPLE.ignored.map((line) => (
                <li
                  key={line}
                  className="rounded-md border border-dashed border-memBorder-primary px-3 py-1.5 typo-body-sm text-onSurface-default-tertiary line-through"
                >
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title="Behaviour">
        <SettingsToggleRow
          label="Keep the original language"
          description="Store each memory in the language it was written in, rather than translating to English."
          control={
            <Switch
              checked={draft.multilingual}
              disabled={!editable}
              onCheckedChange={(v) => set("multilingual", v)}
              aria-label="Keep the original language"
            />
          }
        />
        <SettingsToggleRow
          label="Extract facts"
          description="On, each message is distilled into standalone facts. Off, messages are stored verbatim — useful for transcripts, expensive for recall."
          control={
            <Switch
              checked={draft.infer}
              disabled={!editable}
              onCheckedChange={(v) => set("infer", v)}
              aria-label="Extract facts"
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

      <Dialog open={guiding} onOpenChange={setGuiding}>
        <DialogContent className="sm:max-w-[540px]">
          <DialogHeader>
            <DialogTitle>Draft instructions from a use case</DialogTitle>
            <DialogDescription>
              Describe what this project is for. You will review the result
              before it is applied.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <Textarea
              rows={3}
              autoFocus
              value={useCase}
              placeholder="A support assistant for a hosting company. It should remember the customer's plan, their stack, and past incidents."
              onChange={(e) => setUseCase(e.target.value)}
            />
            <div className="flex items-center gap-3">
              <span className="typo-body-sm text-onSurface-default-secondary">
                Apply to
              </span>
              <div className="flex gap-2">
                {(
                  [
                    ["user_instructions", "User"],
                    ["agent_instructions", "Agent"],
                  ] as const
                ).map(([value, label]) => (
                  <Button
                    key={value}
                    size="sm"
                    variant={target === value ? "default" : "outline"}
                    onClick={() => setTarget(value)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGuiding(false)}>
              Cancel
            </Button>
            <Button onClick={generate} disabled={drafting || !useCase.trim()}>
              {drafting ? "Drafting…" : "Draft"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={proposal !== null}
        onOpenChange={(open) => !open && setProposal(null)}
      >
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Review before applying</DialogTitle>
            <DialogDescription>
              These instructions decide what is remembered from every future
              conversation in this project.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            rows={10}
            value={proposal ?? ""}
            onChange={(e) => setProposal(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setProposal(null)}>
              Discard
            </Button>
            <Button onClick={accept}>
              Use for {target === "user_instructions" ? "User" : "Agent"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
