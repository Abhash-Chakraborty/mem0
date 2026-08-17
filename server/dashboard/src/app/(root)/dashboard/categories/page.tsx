import { redirect } from "next/navigation";

/**
 * Categories moved under settings when they became project-scoped: they are
 * configuration for a project, not a place you go to browse. Kept as a
 * redirect so existing links and bookmarks do not 404.
 */
export default function CategoriesRedirect() {
  redirect("/dashboard/settings/categories");
}
