"use client";

import { useState } from "react";
import {
  Play,
  Power,
  RefreshCw,
  RotateCcw,
  RotateCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { WEBHOOK_ENDPOINTS } from "@/utils/api-endpoints";
import { WebhookDelivery, WebhookEndpoint } from "@/types/api";

const EVENTS = [
  "memory.created",
  "memory.updated",
  "memory.deleted",
  "search.performed",
  "backup.completed",
  "backup.failed",
  "system.degraded",
];

// Chat services reject the raw signed envelope, so the payload is reshaped per
// channel. Generic keeps the exact body existing receivers already parse.
const CHANNELS = [
  { value: "generic", label: "Generic (signed JSON)" },
  { value: "discord", label: "Discord" },
  { value: "slack", label: "Slack" },
];

export default function WebhooksPage() {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["memory.created"]);
  const [channel, setChannel] = useState("generic");
  const [busy, setBusy] = useState(false);

  const endpointsQuery = useApiQuery<WebhookEndpoint[]>(
    async () => (await api.get(WEBHOOK_ENDPOINTS.BASE)).data ?? [],
    { errorToast: "Failed to load webhooks", initialData: [] },
  );
  const deliveriesQuery = useApiQuery<WebhookDelivery[]>(
    async () => (await api.get(WEBHOOK_ENDPOINTS.DELIVERIES)).data ?? [],
    { errorToast: "Failed to load webhook deliveries", initialData: [] },
  );

  const endpoints = endpointsQuery.data ?? [];
  const deliveries = deliveriesQuery.data ?? [];

  const refreshAll = async () => {
    await Promise.all([endpointsQuery.refetch(), deliveriesQuery.refetch()]);
  };

  const toggleEvent = (eventName: string) => {
    setEvents((current) =>
      current.includes(eventName)
        ? current.filter((item) => item !== eventName)
        : [...current, eventName],
    );
  };

  const createWebhook = async () => {
    setBusy(true);
    try {
      const res = await api.post(WEBHOOK_ENDPOINTS.BASE, { name, url, events, channel });
      toast({
        title: "Webhook created",
        description: res.data.secret ? `Secret: ${res.data.secret}` : undefined,
        variant: "success",
      });
      setName("");
      setUrl("");
      setChannel("generic");
      setEvents(["memory.created"]);
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to create webhook",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const deleteWebhook = async (endpointId: string) => {
    setBusy(true);
    try {
      await api.delete(WEBHOOK_ENDPOINTS.BY_ID(endpointId));
      toast({ title: "Webhook deleted", variant: "success" });
      await refreshAll();
    } catch (error) {
      toast({
        title: "Failed to delete webhook",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const testWebhook = async (endpointId: string) => {
    setBusy(true);
    try {
      await api.post(WEBHOOK_ENDPOINTS.TEST(endpointId));
      toast({ title: "Test delivery queued", variant: "success" });
      await deliveriesQuery.refetch();
    } catch (error) {
      toast({
        title: "Failed to test webhook",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const toggleWebhook = async (endpoint: WebhookEndpoint) => {
    setBusy(true);
    try {
      await api.patch(WEBHOOK_ENDPOINTS.BY_ID(endpoint.id), {
        is_active: !endpoint.is_active,
      });
      toast({
        title: endpoint.is_active ? "Webhook disabled" : "Webhook enabled",
        variant: "success",
      });
      await endpointsQuery.refetch();
    } catch (error) {
      toast({
        title: "Failed to update webhook",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const regenerateSecret = async (endpointId: string) => {
    setBusy(true);
    try {
      const res = await api.post(
        WEBHOOK_ENDPOINTS.REGENERATE_SECRET(endpointId),
      );
      toast({
        title: "Webhook secret regenerated",
        description: `New secret: ${res.data.secret}`,
        variant: "success",
      });
      await endpointsQuery.refetch();
    } catch (error) {
      toast({
        title: "Failed to regenerate secret",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const retryDelivery = async (deliveryId: string) => {
    setBusy(true);
    try {
      await api.post(WEBHOOK_ENDPOINTS.RETRY_DELIVERY(deliveryId));
      toast({ title: "Delivery retried", variant: "success" });
      await deliveriesQuery.refetch();
    } catch (error) {
      toast({
        title: "Failed to retry delivery",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const endpointName = (endpointId: string) =>
    endpoints.find((endpoint) => endpoint.id === endpointId)?.name ?? "endpoint";

  const statusClassName = (status: string) => {
    if (status === "delivered")
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
    if (status === "pending")
      return "border-amber-200 bg-amber-50 text-amber-700";
    if (status === "disabled")
      return "border-zinc-200 bg-zinc-50 text-zinc-600";
    return "border-rose-200 bg-rose-50 text-rose-700";
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold font-fustat">Webhooks</h1>
          <p className="text-sm text-onSurface-default-secondary mt-1">
            Signed self-hosted events for memory changes and searches.
          </p>
        </div>
        <Button variant="outline" onClick={refreshAll} disabled={busy}>
          <RefreshCw className="size-4 mr-2" />
          Refresh
        </Button>
      </div>

      <Card className="border-memBorder-primary">
        <CardContent className="grid gap-4 p-5 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Local receiver"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Endpoint URL</Label>
            <Input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.com/webhook"
            />
          </div>
          <div className="space-y-1.5 md:col-span-2">
            <Label>Format</Label>
            <Select value={channel} onValueChange={setChannel}>
              <SelectTrigger className="md:max-w-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CHANNELS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2 md:col-span-2">
            <Label>Events</Label>
            <div className="grid gap-2 md:grid-cols-4">
              {EVENTS.map((eventName) => (
                <label
                  key={eventName}
                  className="flex items-center gap-2 text-sm"
                >
                  <Checkbox
                    checked={events.includes(eventName)}
                    onCheckedChange={() => toggleEvent(eventName)}
                  />
                  {eventName}
                </label>
              ))}
            </div>
          </div>
          <div className="md:col-span-2">
            <Button
              onClick={createWebhook}
              disabled={
                busy || !name.trim() || !url.trim() || events.length === 0
              }
            >
              Create webhook
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-start gap-2 rounded-md border border-memBorder-primary bg-surface-default-secondary/40 p-3 text-xs text-onSurface-default-secondary">
        <ShieldCheck className="size-4 shrink-0 mt-0.5 text-onSurface-default-tertiary" />
        <p>
          Every delivery is signed. Verify it by computing{" "}
          <code className="font-mono">HMAC-SHA256(secret, rawBody)</code> and
          comparing it to the{" "}
          <code className="font-mono">X-Mem0-Signature-256</code> header. The
          event name is also sent as <code className="font-mono">X-Mem0-Event</code>.
        </p>
      </div>

      {endpointsQuery.isLoading ? (
        <TableSkeleton rows={3} columns={4} />
      ) : endpoints.length === 0 ? (
        <EmptyState
          title="No webhooks yet"
          description="Create an endpoint to receive signed memory events."
        />
      ) : (
        <div className="space-y-3">
          {endpoints.map((endpoint) => (
            <Card key={endpoint.id} className="border-memBorder-primary">
              <CardContent className="flex flex-col gap-4 p-4 md:flex-row md:items-center">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium">{endpoint.name}</p>
                    <Badge variant="outline">
                      {endpoint.is_active ? "Active" : "Disabled"}
                    </Badge>
                    {endpoint.channel && endpoint.channel !== "generic" && (
                      <Badge variant="secondary">{endpoint.channel}</Badge>
                    )}
                  </div>
                  <p className="text-xs text-onSurface-default-secondary break-all mt-1">
                    {endpoint.url}
                  </p>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {endpoint.events.map((eventName) => (
                      <Badge key={eventName} variant="outline">
                        {eventName}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleWebhook(endpoint)}
                    disabled={busy}
                  >
                    <Power className="size-3.5 mr-1" />
                    {endpoint.is_active ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => testWebhook(endpoint.id)}
                    disabled={busy}
                  >
                    <Play className="size-3.5 mr-1" />
                    Test
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => regenerateSecret(endpoint.id)}
                    disabled={busy}
                  >
                    <RotateCcw className="size-3.5 mr-1" />
                    Secret
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteWebhook(endpoint.id)}
                    disabled={busy}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="space-y-3">
        <h2 className="text-base font-medium">Recent deliveries</h2>
        {deliveries.length === 0 ? (
          <EmptyState
            title="No deliveries yet"
            description="Deliveries appear after events are queued."
          />
        ) : (
          <div className="space-y-2">
            {deliveries.slice(0, 50).map((delivery) => (
              <Card key={delivery.id} className="border-memBorder-primary">
                <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3 text-sm">
                  <Badge
                    variant="outline"
                    className={statusClassName(delivery.status)}
                  >
                    {delivery.status}
                  </Badge>
                  <span className="font-mono text-xs">{delivery.event_type}</span>
                  <span className="text-xs text-onSurface-default-tertiary">
                    → {endpointName(delivery.endpoint_id)}
                  </span>
                  <span className="text-xs text-onSurface-default-secondary">
                    {delivery.attempts} attempt
                    {delivery.attempts === 1 ? "" : "s"}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs text-onSurface-default-secondary">
                    {delivery.response_status
                      ? `HTTP ${delivery.response_status}`
                      : ""}{" "}
                    {delivery.response_body}
                  </span>
                  {(delivery.status === "failed" ||
                    delivery.status === "disabled") && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => retryDelivery(delivery.id)}
                      disabled={busy}
                    >
                      <RotateCw className="size-3.5 mr-1" />
                      Retry now
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
