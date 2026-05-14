/**
 * Root Layout
 * ============
 * Top-level layout wrapper. Applied to all routes.
 * Handles: theme application, sidebar, header, main content area.
 * Phase 1: minimal shell. Phase 2+ will add nav, sidebar, etc.
 */

import { Outlet } from "react-router-dom";
import { useUIStore } from "@store/index";
import { useEffect } from "react";

export function RootLayout() {
  const theme = useUIStore((s) => s.theme);

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.classList.toggle("dark", prefersDark);
    } else {
      root.classList.toggle("dark", theme === "dark");
    }
  }, [theme]);

  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      {/* Phase 2+ will add: <Header />, <Sidebar />, <NotificationToast /> */}
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
