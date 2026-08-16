/**
 * The display name of this deployment.
 *
 * Read in one place because it was previously derived at four call sites with
 * two different fallbacks ("Abhash Memory" and "abhash-memory"), so an instance
 * that did not set the variable was labelled inconsistently across the UI.
 */
export const INSTANCE_NAME =
  process.env.NEXT_PUBLIC_INSTANCE_NAME || "Abhash Memory";

/** Filesystem-safe form, for export filenames and similar. */
export const INSTANCE_SLUG = INSTANCE_NAME.trim()
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, "-")
  .replace(/^-+|-+$/g, "");
