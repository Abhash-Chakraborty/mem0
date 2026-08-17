"use client";

import Link from "next/link";
import { Boxes, Bot, Clock, FlaskConical, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { ENTITY_LABEL, type EntityType } from "@/constants/entities";

const ICONS: Record<EntityType, typeof User> = {
  user: User,
  agent: Bot,
  app: Boxes,
  run: Clock,
};

interface EntityChipProps {
  type: EntityType;
  id: string;
  /** Renders as a link to the entity's detail page. */
  href?: string;
  /** Marks playground-generated entities, matching the reference's flask icon. */
  isPlayground?: boolean;
  className?: string;
}

/**
 * An entity identifier, shown consistently wherever one appears.
 *
 * The id is monospace because these are opaque strings that get copied and
 * compared character by character — a proportional font makes
 * `playground-hermes-11d0021b` and `playground-hermes-11d002lb` look identical.
 */
export function EntityChip({
  type,
  id,
  href,
  isPlayground,
  className,
}: EntityChipProps) {
  const Icon = ICONS[type] ?? User;

  const body = (
    <>
      <Icon className="size-3.5 shrink-0 text-onSurface-default-tertiary" />
      <span className="truncate font-mono text-[12.5px]">{id}</span>
      {isPlayground && (
        <FlaskConical
          className="size-3 shrink-0 text-onSurface-default-tertiary"
          aria-label="Created in the playground"
        />
      )}
    </>
  );

  const classes = cn(
    "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded px-1.5 py-0.5 text-onSurface-default-primary",
    href && "transition-colors hover:bg-surface-default-secondary",
    className,
  );

  if (href) {
    return (
      <Link
        href={href}
        title={`${ENTITY_LABEL[type]}: ${id}`}
        className={classes}
        onClick={(e) => e.stopPropagation()}
      >
        {body}
      </Link>
    );
  }

  return (
    <span title={`${ENTITY_LABEL[type]}: ${id}`} className={classes}>
      {body}
    </span>
  );
}
