import { SettingsNav } from "./settings-nav";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-8 p-6 sm:flex-row">
      <SettingsNav />
      {/* min-w-0 so a wide table inside a settings page scrolls within its own
          container instead of stretching the flex row and the page with it. */}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
