"use client";

import React, { useEffect, useState } from "react";
import Image from "next/image";
import { useTheme } from "next-themes";
import { INSTANCE_NAME } from "@/lib/instance";

/**
 * The brand shown on the loading splash: the logo mark plus this instance's
 * name.
 *
 * It previously rendered /images/dark.svg, which is upstream's "mem0"
 * wordmark - so a fork that had renamed itself everywhere else still flashed
 * someone else's product name on every load. The mark is the same asset the
 * login screen and sidebar use, so the three agree.
 */
export default function ThemeAwareLogo({
  width = 120,
  height = 40,
}: {
  width?: number;
  height?: number;
}) {
  const [mounted, setMounted] = useState(false);
  const { theme, resolvedTheme } = useTheme();

  useEffect(() => {
    setMounted(true);
  }, []);

  // Reserve the space before mount so the splash does not jump when the
  // resolved theme arrives.
  if (!mounted) {
    return <div style={{ width, height }} />;
  }

  const currentTheme = theme === "system" ? resolvedTheme : theme;
  const markSrc =
    currentTheme === "dark"
      ? "/images/logos/logo-light.png"
      : "/images/logos/logo-dark.png";
  const markSize = Math.round(height * 0.8);

  return (
    <div className="flex items-center gap-2.5" style={{ minHeight: height }}>
      <Image
        src={markSrc}
        alt=""
        aria-hidden
        width={markSize}
        height={markSize}
        className="shrink-0"
      />
      <span className="text-lg font-semibold text-onSurface-default-primary font-fustat">
        {INSTANCE_NAME}
      </span>
    </div>
  );
}
