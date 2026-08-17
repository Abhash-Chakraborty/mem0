"use client";

import { MainNav } from "./main-nav";
import {
  PanelRight,
  LogOut,
  Settings,
  HelpCircle,
  UserRound,
  Users,
} from "lucide-react";
import { useCallback } from "react";
import {
  COLLAPSED_SIDEBAR_WIDTH,
  COLLAPSED_SIDEBAR_WIDTH_WITHOUT_PADDING,
  SIDEBAR_WIDTH,
} from "../../clientLayout";
import { useDispatch, useSelector } from "react-redux";
import { cn } from "@/lib/utils";
import { RootState } from "@/store/store";
import { toggleSidebar } from "@/store/reducers/layoutReducer";
import { useAuth } from "@/hooks/use-auth";
import { useScope } from "@/lib/scope";
import { BuildBadge } from "@/components/shared/build-badge";
import { ThemeSegmented } from "@/components/shared/theme-segmented";
import { OrgSwitcher } from "@/components/tenancy/org-switcher";
import { ProjectSwitcher } from "@/components/tenancy/project-switcher";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import Link from "next/link";

export default function NavWrapper() {
  const dispatch = useDispatch();
  const isSidebarCollapsed = useSelector(
    (state: RootState) => state.layout.isSidebarCollapsed,
  );
  const { user, logout } = useAuth();
  const { scope, can } = useScope();

  const handleToggle = useCallback(() => {
    dispatch(toggleSidebar());
  }, [dispatch]);

  return (
    <>
      <div
        className="fixed top-0 left-0 h-full flex justify-between flex-col overflow-hidden transition-all duration-300 ease-in-out z-30 bg-transparent"
        style={{
          width: isSidebarCollapsed ? COLLAPSED_SIDEBAR_WIDTH : SIDEBAR_WIDTH,
        }}
      >
        <div className="flex flex-col flex-1 min-h-0 items-start gap-5 px-3 py-3 overflow-y-auto overflow-x-hidden">
          <div
            className={cn(
              "relative flex w-full",
              isSidebarCollapsed ? "p-0 justify-center" : "",
            )}
          >
            <OrgSwitcher collapsed={isSidebarCollapsed} />
          </div>

          <MainNav className="w-full" />
        </div>

        {!isSidebarCollapsed && (
          <div className="flex flex-col shrink-0">
            <div className="mx-3 px-0 pt-3">
              <BuildBadge />
            </div>
            <div className="mx-3 px-0 py-3 border-t border-memBorder-primary">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button className="flex items-center gap-2 w-full text-left hover:bg-surface-default-secondary-hover rounded-md p-1.5 transition-colors">
                    <div className="grid size-7 place-items-center rounded-md bg-surface-default-tertiary text-onSurface-default-secondary text-xs font-semibold shrink-0">
                      {user?.name?.charAt(0).toUpperCase() || "?"}
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="typo-body-xs text-onSurface-default-primary truncate">
                        {user?.name}
                      </span>
                      <span className="typo-caption-sm text-onSurface-default-tertiary truncate">
                        {user?.email}
                      </span>
                    </div>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  side="top"
                  className="w-56 font-fustat bg-surface-default-primary border-memBorder-secondary"
                >
                  <div className="px-2 py-1.5">
                    <p className="typo-body-sm text-onSurface-default-primary">
                      {user?.name}
                    </p>
                    <p className="typo-body-xs text-onSurface-default-tertiary">
                      {user?.email}
                    </p>
                    {scope && (
                      <p className="typo-caption-sm text-onSurface-default-tertiary mt-1">
                        {scope.role} in {scope.org_name}
                      </p>
                    )}
                  </div>
                  <DropdownMenuSeparator className="bg-memBorder-primary" />
                  {/* Theme sits in the menu rather than in the top bar: it is
                      set once and then forgotten, so it does not earn permanent
                      chrome next to controls used on every visit. */}
                  <div className="px-2 py-1.5">
                    <ThemeSegmented />
                  </div>
                  <DropdownMenuSeparator className="bg-memBorder-primary" />
                  <DropdownMenuItem
                    asChild
                    className="typo-body-sm text-onSurface-default-primary hover:bg-surface-default-tertiary-hover focus:bg-surface-default-tertiary-hover cursor-pointer"
                  >
                    <Link href="/dashboard/settings">
                      <UserRound className="size-4 mr-2" />
                      Your profile
                    </Link>
                  </DropdownMenuItem>
                  {can("admin") && (
                    <DropdownMenuItem
                      asChild
                      className="typo-body-sm text-onSurface-default-primary hover:bg-surface-default-tertiary-hover focus:bg-surface-default-tertiary-hover cursor-pointer"
                    >
                      <Link href="/dashboard/settings/members">
                        <Users className="size-4 mr-2" />
                        Members &amp; access
                      </Link>
                    </DropdownMenuItem>
                  )}
                  {can("admin") && (
                    <DropdownMenuItem
                      asChild
                      className="typo-body-sm text-onSurface-default-primary hover:bg-surface-default-tertiary-hover focus:bg-surface-default-tertiary-hover cursor-pointer"
                    >
                      <Link href="/dashboard/settings/general">
                        <Settings className="size-4 mr-2" />
                        Project settings
                      </Link>
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator className="bg-memBorder-primary" />
                  <DropdownMenuItem
                    onClick={logout}
                    className="typo-body-sm text-onSurface-default-primary hover:bg-surface-default-tertiary-hover focus:bg-surface-default-tertiary-hover cursor-pointer"
                  >
                    <LogOut className="size-4 mr-2" />
                    Log out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        )}
      </div>

      <div
        className="bg-transparent left-0 top-0 fixed flex justify-between items-center pr-4 h-12 font-fustat z-20"
        style={{
          width: `calc(100% - ${isSidebarCollapsed ? COLLAPSED_SIDEBAR_WIDTH_WITHOUT_PADDING + 12 : SIDEBAR_WIDTH + 12}px)`,
          left: `${isSidebarCollapsed ? COLLAPSED_SIDEBAR_WIDTH_WITHOUT_PADDING + 12 : SIDEBAR_WIDTH + 12}px`,
        }}
      >
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleToggle}
            className="cursor-pointer text-onSurface-default-tertiary hover:text-onSurface-default-secondary"
            aria-label={
              isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"
            }
          >
            <PanelRight className="size-4" />
          </button>
          <ProjectSwitcher />
        </div>

        <div className="flex items-center gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <a
                href="https://docs.mem0.ai/open-source/overview"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center text-onSurface-default-tertiary hover:text-onSurface-default-secondary"
              >
                <HelpCircle className="size-4 shrink-0" />
              </a>
            </TooltipTrigger>
            <TooltipContent>Documentation</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </>
  );
}
