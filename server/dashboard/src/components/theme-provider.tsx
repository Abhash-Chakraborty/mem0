"use client";

import * as React from "react";
import {
  ThemeProvider as NextThemesProvider,
  type ThemeProviderProps,
} from "next-themes";

/**
 * Theme configuration for every entry point in the app.
 *
 * These defaults live here rather than at each call site because they used to
 * be repeated in three layouts and had drifted apart: setup ran with
 * `defaultTheme="light"` and no `enableSystem`, so it ignored the OS setting
 * entirely and rendered light while the login screen beside it rendered dark.
 * Callers should pass children only; override a prop solely for a route that
 * genuinely needs to differ.
 */
const THEME_DEFAULTS = {
  attribute: "class",
  defaultTheme: "system",
  enableSystem: true,
  disableTransitionOnChange: true,
} as const satisfies Partial<ThemeProviderProps>;

export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  return (
    <NextThemesProvider {...THEME_DEFAULTS} {...props}>
      {children}
    </NextThemesProvider>
  );
}
