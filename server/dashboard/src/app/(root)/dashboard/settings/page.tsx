import { redirect } from "next/navigation";

/**
 * Settings has no landing page of its own — it is seven pages behind a
 * sub-navigation. Anything pointing at /dashboard/settings (old links, the
 * account menu, a bookmark) lands on the project's General page.
 */
export default function SettingsIndex() {
  redirect("/dashboard/settings/general");
}
