"use client";

import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/use-toast";
import { useAuth } from "@/hooks/use-auth";
import { useScope } from "@/lib/scope";
import { ThemeSegmented } from "@/components/shared/theme-segmented";
import { SettingsHeader } from "@/components/settings/settings-page";
import { getErrorMessage } from "@/lib/error-message";
import { INSTANCE_NAME } from "@/lib/instance";
import { api } from "@/utils/api";
import { AUTH_ENDPOINTS } from "@/utils/api-endpoints";

export default function SettingsPage() {
  const { user, refreshUser, logout } = useAuth();
  const { scope } = useScope();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  useEffect(() => {
    if (user) {
      setName(user.name);
      setEmail(user.email);
    }
  }, [user]);

  const profileDirty =
    user !== null && (name !== user.name || email !== user.email);
  const profileValid = name.trim().length > 0 && email.trim().length > 0;

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    try {
      await api.patch(AUTH_ENDPOINTS.ME, {
        name: name.trim(),
        email: email.trim(),
      });
      await refreshUser();
      toast({ title: "Profile updated", variant: "success" });
    } catch (error) {
      toast({
        title: "Failed to update profile",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setSavingProfile(false);
    }
  };

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      toast({
        title: "Passwords don't match",
        variant: "destructive",
      });
      return;
    }

    setSavingPassword(true);
    try {
      await api.post(AUTH_ENDPOINTS.CHANGE_PASSWORD, {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      toast({ title: "Password updated", variant: "success" });
    } catch (error) {
      toast({
        title: "Failed to update password",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setSavingPassword(false);
    }
  };

  const instanceName = INSTANCE_NAME;

  return (
    <div className="space-y-6">
      <SettingsHeader
        title="Your profile"
        description="Your account on this instance. These settings follow you across every organization and project."
      />

      <Card className="border-memBorder-primary">
        <CardHeader>
          <CardTitle className="text-sm">Instance</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-onSurface-default-tertiary">
                Instance name
              </dt>
              <dd className="mt-0.5 font-medium">{instanceName}</dd>
            </div>
            <div>
              <dt className="text-xs text-onSurface-default-tertiary">
                Deployment
              </dt>
              <dd className="mt-0.5 font-medium">Self-hosted</dd>
            </div>
            <div>
              <dt className="text-xs text-onSurface-default-tertiary">
                Your role here
              </dt>
              <dd className="mt-0.5 font-medium capitalize">
                {scope
                  ? `${scope.role} in ${scope.org_name}`
                  : (user?.role ?? "admin")}
              </dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-onSurface-default-tertiary">
            Self-hosted. Memories and request logs live in your own Postgres;
            nothing is sent to a hosted Mem0 service, and there are no plans,
            seats or quotas.
          </p>
        </CardContent>
      </Card>

      <Card className="border-memBorder-primary">
        <CardHeader>
          <CardTitle className="text-sm">Profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="settings-name" className="text-xs">
                Name
              </Label>
              <Input
                id="settings-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="settings-email" className="text-xs">
                Email
              </Label>
              <Input
                id="settings-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>
          <Button
            onClick={handleSaveProfile}
            disabled={!profileDirty || !profileValid || savingProfile}
          >
            {savingProfile ? "Saving..." : "Save profile"}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-memBorder-primary">
        <CardHeader>
          <CardTitle className="text-sm">Password</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="settings-current-password" className="text-xs">
              Current password
            </Label>
            <Input
              id="settings-current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="settings-new-password" className="text-xs">
                New password
              </Label>
              <Input
                id="settings-new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Min 8 characters"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="settings-confirm-password" className="text-xs">
                Confirm new password
              </Label>
              <Input
                id="settings-confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
          </div>
          <Button
            onClick={handleChangePassword}
            disabled={
              !currentPassword ||
              newPassword.length < 8 ||
              !confirmPassword ||
              savingPassword
            }
          >
            {savingPassword ? "Saving..." : "Update password"}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-memBorder-primary">
        <CardHeader>
          <CardTitle className="text-sm">Appearance</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <span className="text-sm text-onSurface-default-secondary">
              Theme
            </span>
            {/* The same control as the account menu, so the two never drift. */}
            <div className="w-36">
              <ThemeSegmented />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-memBorder-primary">
        <CardHeader>
          <CardTitle className="text-sm">Session</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <p className="text-xs text-onSurface-default-tertiary">
            Signs you out of this browser. Your memories and API keys are
            unaffected.
          </p>
          <Button variant="outline" onClick={logout}>
            <LogOut className="mr-2 size-4" />
            Log out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
