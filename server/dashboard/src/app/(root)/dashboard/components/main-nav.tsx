"use client";

import * as React from "react";
import Link from "next/link";
import {
  Activity,
  Archive,
  ChevronDown,
  FolderInput,
  GalleryVerticalEnd,
  HeartPulse,
  KeyRound,
  LayoutDashboard,
  ScrollText,
  Settings,
  Share2,
  Tags,
  Users,
  WebhookIcon,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarGroupLabel,
} from "@/components/ui/sidebar";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface NavItem {
  title: string;
  url: string;
  icon: LucideIcon;
}

// The three groups previously repeated the same twenty-line menu-item block,
// which is how "Operations" would otherwise have become a fourth copy. Groups
// are data; the item markup exists once, in NavLink below.
const ACTIVITY_ITEMS: NavItem[] = [
  { title: "Dashboard", url: "/dashboard/analytics", icon: LayoutDashboard },
  { title: "Requests", url: "/dashboard/requests", icon: Activity },
  { title: "Memories", url: "/dashboard/memories", icon: GalleryVerticalEnd },
  { title: "Entities", url: "/dashboard/entities", icon: Users },
  { title: "Graph", url: "/dashboard/graph", icon: Share2 },
];

const TOOL_ITEMS: NavItem[] = [
  { title: "Categories", url: "/dashboard/categories", icon: Tags },
  { title: "Webhooks", url: "/dashboard/webhooks", icon: WebhookIcon },
  { title: "Export", url: "/dashboard/export", icon: FolderInput },
];

const OPERATIONS_ITEMS: NavItem[] = [
  { title: "Health", url: "/dashboard/health", icon: HeartPulse },
  { title: "Backups", url: "/dashboard/backups", icon: Archive },
  { title: "Logs", url: "/dashboard/logs", icon: ScrollText },
];

const ACCOUNT_ITEMS: NavItem[] = [
  { title: "API Keys", url: "/dashboard/api-keys", icon: KeyRound },
  { title: "Configuration", url: "/dashboard/configuration", icon: Wrench },
  { title: "Settings", url: "/dashboard/settings", icon: Settings },
];

function NavLink({
  item,
  collapsed,
  active,
}: {
  item: NavItem;
  collapsed: boolean;
  active: boolean;
}) {
  return (
    <SidebarMenuItem key={item.title}>
      <SidebarMenuButton
        asChild
        collapsed={collapsed}
        active={active}
        tooltip={collapsed ? item.title : undefined}
      >
        <Link
          href={item.url}
          className={cn(
            "flex items-center w-full",
            collapsed ? "justify-center mx-auto" : "gap-1.5",
          )}
        >
          <item.icon className="size-4 shrink-0" />
          {!collapsed && <span>{item.title}</span>}
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function NavGroup({
  label,
  items,
  collapsed,
  pathname,
}: {
  label: string;
  items: NavItem[];
  collapsed: boolean;
  pathname: string;
}) {
  return (
    <div className="flex flex-col gap-0">
      {!collapsed && <SidebarGroupLabel className="mb-0">{label}</SidebarGroupLabel>}
      {items.map((item) => (
        <NavLink
          key={item.title}
          item={item}
          collapsed={collapsed}
          active={pathname === item.url}
        />
      ))}
    </div>
  );
}

export function MainNav({
  className,
  ...props
}: React.HTMLAttributes<HTMLElement>) {
  const pathname = usePathname();
  const isSidebarCollapsed = useSelector(
    (state: RootState) => state.layout.isSidebarCollapsed,
  );
  const [isToolsOpen, setIsToolsOpen] = React.useState(true);

  const divider = isSidebarCollapsed ? (
    <div className="h-[1px] w-full bg-memBorder-primary my-2" />
  ) : null;

  return (
    <Sidebar
      collapsible={isSidebarCollapsed ? "icon" : undefined}
      className={cn(className, "border-r-0 w-full mb-0 bg-transparent")}
      {...props}
    >
      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu className="gap-0">
            <div className="flex flex-col gap-3">
              <NavGroup
                label="ACTIVITY"
                items={ACTIVITY_ITEMS}
                collapsed={isSidebarCollapsed}
                pathname={pathname}
              />

              {divider}

              <Collapsible
                open={isToolsOpen}
                onOpenChange={setIsToolsOpen}
                className="flex flex-col gap-0"
              >
                {!isSidebarCollapsed && (
                  <CollapsibleTrigger asChild>
                    <SidebarGroupLabel className="cursor-pointer mb-0">
                      SELF-HOSTED TOOLS
                      <ChevronDown
                        className={cn(
                          "size-3 transition-transform duration-200",
                          isToolsOpen ? "" : "-rotate-90",
                        )}
                      />
                    </SidebarGroupLabel>
                  </CollapsibleTrigger>
                )}
                <CollapsibleContent className="flex flex-col gap-0">
                  {TOOL_ITEMS.map((item) => (
                    <NavLink
                      key={item.title}
                      item={item}
                      collapsed={isSidebarCollapsed}
                      active={pathname === item.url}
                    />
                  ))}
                </CollapsibleContent>
              </Collapsible>

              {divider}

              <NavGroup
                label="OPERATIONS"
                items={OPERATIONS_ITEMS}
                collapsed={isSidebarCollapsed}
                pathname={pathname}
              />

              {divider}

              <NavGroup
                label="ACCOUNT"
                items={ACCOUNT_ITEMS}
                collapsed={isSidebarCollapsed}
                pathname={pathname}
              />
            </div>
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  );
}
