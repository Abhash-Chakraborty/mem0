/**
 * Build identity for the dashboard bundle.
 *
 * These are inlined by Next at build time from the Docker build args, so they
 * describe the commit this bundle was compiled from. The API reports its own
 * equivalents at GET /system/version; when the two disagree, the dashboard and
 * the API were deployed from different commits and the footer says so.
 */
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || "dev";
export const GIT_SHA = process.env.NEXT_PUBLIC_GIT_SHA || "unknown";
export const BUILT_AT = process.env.NEXT_PUBLIC_BUILT_AT || "unknown";

/** Short display form, e.g. `dev · a3f91c2`. */
export const BUILD_LABEL = `${APP_VERSION}${
  GIT_SHA && GIT_SHA !== "unknown" ? ` · ${GIT_SHA.slice(0, 7)}` : ""
}`;

export interface ServerVersion {
  version: string;
  git_sha: string;
  built_at: string;
  python: string;
  mem0_core: string;
  started_at: string;
  uptime_seconds: number;
}

/**
 * Whether two build SHAs represent a real mismatch.
 *
 * Only claims drift when both sides actually know their SHA — an `unknown` on
 * either side means the image was built outside Compose, which is not the same
 * thing as a mismatched deploy and must not raise a false alarm. A footer that
 * cries mismatch on every missing SHA trains people to ignore it, and then it
 * is worth nothing on the day the deploy really did drift.
 *
 * Split out from isBuildMismatch so the rule is testable: GIT_SHA is a
 * build-time constant, and a test that reimplements the comparison around it
 * would be asserting a copy of the logic rather than the logic.
 */
export function shasDiffer(bundleSha: string, serverSha: string): boolean {
  if (bundleSha === "unknown" || serverSha === "unknown") return false;
  return bundleSha !== serverSha;
}

/** True when the API is running a different commit than this bundle. */
export function isBuildMismatch(server: ServerVersion | undefined): boolean {
  if (!server) return false;
  return shasDiffer(GIT_SHA, server.git_sha);
}
