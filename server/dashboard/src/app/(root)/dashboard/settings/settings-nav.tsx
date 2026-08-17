"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";

/**
 * The settings sub-navigation.
 *
 * Grouped by *what the setting belongs to* rather than by topic, because that
 * is the question people actually have when they cannot find something: is
 * this per-project, org-wide, or just mine? A flat list of nine pages hides
 * exactly that.
 */

interface Item {
  href: string;
  label: string;
  /** Minimum role, if the page is not for everyone. */
  minimum?: string;
}

const GROUPS: { label: string; items: Item[] }[] = [
  {
    label: "Project",
    items: [
      { href: "/dashboard/settings/general", label: "General" },
      { href: "/dashboard/settings/extraction", label: "Extraction" },
      { href: "/dashboard/settings/categories", label: "Categories" },
      { href: "/dashboard/settings/retention", label: "Retention" },
    ],
  },
  {
    label: "Organization",
    items: [
      { href: "/dashboard/settings/organization", label: "General" },
      {
        href: "/dashboard/settings/members",
        label: "Members",
        minimum: "admin",
      },
    ],
  },
  {
    label: "Personal",
    items: [{ href: "/dashboard/settings/profile", label: "Your profile" }],
  },
];

export function SettingsNav() {
  const pathname = usePathname();
  const { can } = useScope();

  return (
    <nav
      className="flex w-full shrink-0 flex-col gap-5 sm:w-44"
      aria-label="Settings"
    >
      {GROUPS.map((group) => {
        const visible = group.items.filter((i) => !i.minimum || can(i.minimum));
        if (visible.length === 0) return null;
        return (
          <div key={group.label} className="flex flex-col gap-0.5">
            <div className="mb-1 px-2 typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              {group.label}
            </div>
            {visible.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "rounded-md px-2 py-1.5 typo-body-sm transition-colors",
                    active
                      ? "bg-surface-default-tertiary text-onSurface-default-primary"
                      : "text-onSurface-default-secondary hover:bg-surface-default-secondary-hover hover:text-onSurface-default-primary",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}
