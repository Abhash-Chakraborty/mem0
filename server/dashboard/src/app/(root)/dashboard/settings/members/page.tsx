"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Mail, ShieldAlert, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { TENANCY_ENDPOINTS } from "@/utils/api-endpoints";
import { rankOf, useScope } from "@/lib/scope";
import { useAuth } from "@/hooks/use-auth";
import { getErrorMessage } from "@/lib/error-message";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
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

interface Member {
  user_id: string;
  name: string;
  email: string;
  role: string;
  project_role: string | null;
  joined_at: string;
}

interface Invite {
  id: string;
  email: string;
  role: string;
  expires_at: string;
  created_at: string;
  accepted_at: string | null;
}

const ROLES = ["reader", "member", "admin", "owner"] as const;

const ROLE_DESCRIPTION: Record<string, string> = {
  reader: "Read memories, requests, and entities. Cannot write or configure.",
  member: "Everything a reader can do, plus create and edit memories.",
  admin: "Manage projects, categories, members, and invitations.",
  owner: "Full control, including deleting projects and the organization.",
};

export default function MembersPage() {
  const { scope, projects, isLoading: scopeLoading, can } = useScope();
  const { user } = useAuth();

  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviting, setInviting] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);

  const orgId = scope?.org_id;

  const load = useCallback(async () => {
    if (!orgId) return;
    setLoading(true);
    try {
      const [memberList, inviteList] = await Promise.all([
        api.get<Member[]>(TENANCY_ENDPOINTS.ORG_MEMBERS(orgId)),
        can("admin")
          ? api.get<Invite[]>(TENANCY_ENDPOINTS.ORG_INVITES(orgId))
          : Promise.resolve({ data: [] as Invite[] }),
      ]);
      setMembers(memberList.data);
      setInvites(inviteList.data);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load members."));
    } finally {
      setLoading(false);
    }
  }, [orgId, can]);

  useEffect(() => {
    void load();
  }, [load]);

  const ownerCount = useMemo(
    () => members.filter((m) => m.role === "owner").length,
    [members],
  );

  const changeRole = async (member: Member, role: string) => {
    if (!orgId) return;
    try {
      await api.patch(TENANCY_ENDPOINTS.ORG_MEMBER(orgId, member.user_id), {
        role,
      });
      toast.success(`${member.name} is now ${role}`);
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not change that role."));
    }
  };

  const remove = async () => {
    if (!orgId || !removing) return;
    try {
      await api.delete(TENANCY_ENDPOINTS.ORG_MEMBER(orgId, removing.user_id));
      toast.success(`Removed ${removing.name}`);
      setRemoving(null);
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not remove that member."));
    }
  };

  const invite = async () => {
    if (!orgId || !inviteEmail.trim()) return;
    try {
      const res = await api.post(TENANCY_ENDPOINTS.ORG_INVITES(orgId), {
        email: inviteEmail.trim(),
        role: inviteRole,
      });
      // The token is shown here and never again - this instance has no mail
      // transport, so the admin has to carry it across themselves.
      setIssuedToken(res.data.token);
      setInviteEmail("");
      setInviting(false);
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not create that invitation."));
    }
  };

  const revoke = async (inviteId: string) => {
    if (!orgId) return;
    try {
      await api.delete(TENANCY_ENDPOINTS.ORG_INVITE(orgId, inviteId));
      toast.success("Invitation revoked");
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not revoke that invitation."));
    }
  };

  if (scopeLoading || loading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const myRank = rankOf(scope?.role);

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="typo-heading-md text-onSurface-default-primary">
            Members &amp; access
          </h1>
          <p className="typo-body-sm text-onSurface-default-tertiary">
            Who can reach {scope?.org_name} and its {projects.length}{" "}
            {projects.length === 1 ? "project" : "projects"}.
          </p>
        </div>
        {can("admin") && (
          <Button onClick={() => setInviting(true)}>
            <UserPlus className="mr-2 size-4" />
            Invite
          </Button>
        )}
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="typo-body-md">
            Members ({members.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead className="w-40">Role</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => {
                const isMe = member.user_id === user?.id;
                // The last owner is protected server-side too; disabling the
                // control here just avoids offering an action that will fail.
                const isLastOwner = member.role === "owner" && ownerCount <= 1;
                const canEdit =
                  can("admin") && rankOf(member.role) <= myRank && !isLastOwner;

                return (
                  <TableRow key={member.user_id}>
                    <TableCell className="text-onSurface-default-primary">
                      {member.name}
                      {isMe && (
                        <span className="ml-2 typo-caption-sm text-onSurface-default-tertiary">
                          you
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-onSurface-default-secondary">
                      {member.email}
                    </TableCell>
                    <TableCell>
                      {canEdit ? (
                        <Select
                          value={member.role}
                          onValueChange={(role) => changeRole(member, role)}
                        >
                          <SelectTrigger className="h-8">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {ROLES.filter((r) => rankOf(r) <= myRank).map(
                              (role) => (
                                <SelectItem key={role} value={role}>
                                  {role}
                                </SelectItem>
                              ),
                            )}
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className="typo-body-sm text-onSurface-default-secondary">
                          {member.role}
                          {isLastOwner && (
                            <span
                              className="ml-2 inline-flex items-center gap-1 typo-caption-sm text-onSurface-default-tertiary"
                              title="An organization must always have an owner."
                            >
                              <ShieldAlert className="size-3" />
                              last owner
                            </span>
                          )}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {(canEdit || (isMe && !isLastOwner)) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setRemoving(member)}
                          aria-label={`Remove ${member.name}`}
                        >
                          <Trash2 className="size-4 text-onSurface-danger-primary" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {can("admin") && (
        <Card>
          <CardHeader>
            <CardTitle className="typo-body-md">
              Pending invitations ({invites.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {invites.length === 0 ? (
              <p className="typo-body-sm text-onSurface-default-tertiary">
                No invitations outstanding.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead className="w-32">Role</TableHead>
                    <TableHead className="w-48">Expires</TableHead>
                    <TableHead className="w-24" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="text-onSurface-default-primary">
                        {item.email}
                      </TableCell>
                      <TableCell className="text-onSurface-default-secondary">
                        {item.role}
                      </TableCell>
                      <TableCell className="text-onSurface-default-secondary">
                        {new Date(item.expires_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => revoke(item.id)}
                        >
                          Revoke
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog open={inviting} onOpenChange={setInviting}>
        <DialogContent className="sm:max-w-[460px]">
          <DialogHeader>
            <DialogTitle>Invite someone</DialogTitle>
            <DialogDescription>
              This instance does not send email. You will get a link to pass on
              yourself.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                autoFocus
                value={inviteEmail}
                placeholder="teammate@example.com"
                onChange={(e) => setInviteEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="invite-role">Role</Label>
              <Select value={inviteRole} onValueChange={setInviteRole}>
                <SelectTrigger id="invite-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.filter((r) => rankOf(r) <= myRank).map((role) => (
                    <SelectItem key={role} value={role}>
                      {role}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="typo-caption-sm text-onSurface-default-tertiary">
                {ROLE_DESCRIPTION[inviteRole]}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInviting(false)}>
              Cancel
            </Button>
            <Button onClick={invite} disabled={!inviteEmail.trim()}>
              <Mail className="mr-2 size-4" />
              Create invitation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={issuedToken !== null}
        onOpenChange={(open) => !open && setIssuedToken(null)}
      >
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>Invitation created</DialogTitle>
            <DialogDescription>
              Copy this token now. Only its hash is stored, so it cannot be
              shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 rounded-md border border-memBorder-primary bg-surface-default-secondary p-2">
            <code className="min-w-0 flex-1 truncate font-mono text-xs text-onSurface-default-primary">
              {issuedToken}
            </code>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(issuedToken ?? "");
                toast.success("Copied");
              }}
            >
              <Copy className="size-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setIssuedToken(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* A plain confirm rather than the type-the-name modal used for
          destroying data: removing a member revokes access and is undone by
          re-inviting them, so the heavier ceremony would not fit the risk. */}
      <Dialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
      >
        <DialogContent className="sm:max-w-[440px]">
          <DialogHeader>
            <DialogTitle>
              {removing?.user_id === user?.id
                ? "Leave this organization?"
                : `Remove ${removing?.name}?`}
            </DialogTitle>
            <DialogDescription>
              {removing?.user_id === user?.id
                ? `You will lose access to ${scope?.org_name} and everything in it.`
                : `${removing?.name} will lose access to ${scope?.org_name}. Their memories are not deleted.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={remove}>
              {removing?.user_id === user?.id ? "Leave" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
