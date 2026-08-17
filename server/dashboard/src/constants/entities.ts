/**
 * The one place the API's entity vocabulary is translated into the UI's.
 *
 * The API speaks in identifier fields — `user_id`, `agent_id`, `app_id`,
 * `run_id`. The dashboard speaks in what those things are to a person: a User,
 * an Agent, an App, a Session. Deriving that mapping inline is how "run" ends
 * up labelled three different ways on three different pages.
 */

export type EntityType = "user" | "agent" | "app" | "run";

export const ENTITY_TYPES: EntityType[] = ["user", "agent", "app", "run"];

/** Singular display name. */
export const ENTITY_LABEL: Record<EntityType, string> = {
  user: "User",
  agent: "Agent",
  app: "App",
  run: "Session",
};

/** Plural display name, for tabs and counts. */
export const ENTITY_LABEL_PLURAL: Record<EntityType, string> = {
  user: "Users",
  agent: "Agents",
  app: "Apps",
  run: "Sessions",
};

/** The query/filter field the API expects for each type. */
export const ENTITY_FIELD: Record<EntityType, string> = {
  user: "user_id",
  agent: "agent_id",
  app: "app_id",
  run: "run_id",
};

/** Reverse lookup, for turning an API payload key back into a type. */
export const FIELD_TO_ENTITY: Record<string, EntityType> = {
  user_id: "user",
  agent_id: "agent",
  app_id: "app",
  run_id: "run",
};

/** Route to an entity's detail page. */
export function entityHref(type: EntityType, id: string): string {
  return `/dashboard/entities/${type}/${encodeURIComponent(id)}`;
}
