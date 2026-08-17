"use client";

import React from "react";
import { ThemeProvider } from "@/components/theme-provider";
import "@/styles/globals.css";
import { ClientLayout } from "./clientLayout";
import { cn } from "@/lib/utils";
import { Inter, InterDisplay, Roboto, Fustat, DMMono } from "./fonts";
import { Provider } from "react-redux";
import store from "@/store/store";
import { AuthProvider } from "@/lib/auth";
import { ScopeProvider } from "@/lib/scope";
import dynamic from "next/dynamic";

const Toaster = dynamic(
  () =>
    import("@/components/ui/sonner").then((mod) => ({ default: mod.Toaster })),
  {
    ssr: false,
  },
);

export function DashboardClientLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={cn(
          Inter.className,
          InterDisplay.variable,
          Roboto.variable,
          Fustat.variable,
          DMMono.variable,
        )}
        suppressHydrationWarning
      >
        <Provider store={store}>
          <AuthProvider>
            {/* Inside AuthProvider: /scope needs a bearer token, so resolving
                scope before the session exists would always 401. */}
            <ScopeProvider>
              <ThemeProvider>
                <ClientLayout>{children}</ClientLayout>
                <Toaster />
              </ThemeProvider>
            </ScopeProvider>
          </AuthProvider>
        </Provider>
      </body>
    </html>
  );
}
