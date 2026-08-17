"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
] as const;

/**
 * Theme as a three-way segmented control, for use inside the account menu.
 *
 * A segmented control rather than a submenu because all three states are
 * visible at once - you can see which one is active without opening anything,
 * and switching is one click instead of two.
 */
export function ThemeSegmented() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // next-themes only knows the resolved theme on the client, so rendering the
  // active segment during SSR would hydrate with the wrong one selected.
  useEffect(() => setMounted(true), []);

  return (
    <div
      className="flex items-center gap-0.5 rounded-md bg-surface-default-tertiary p-0.5"
      role="radiogroup"
      aria-label="Theme"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = mounted && theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={(e) => {
              // The menu stays open: picking a theme is something you want to
              // see the result of, and reopening to try another is friction.
              e.preventDefault();
              e.stopPropagation();
              setTheme(value);
            }}
            className={cn(
              "grid h-6 flex-1 place-items-center rounded transition-colors",
              active
                ? "bg-surface-default-primary text-onSurface-default-primary shadow-sm"
                : "text-onSurface-default-tertiary hover:text-onSurface-default-secondary",
            )}
          >
            <Icon className="size-3.5" />
          </button>
        );
      })}
    </div>
  );
}
