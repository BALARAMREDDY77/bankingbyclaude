/**
 * Global Store — Zustand
 * =======================
 * Lightweight global state using Zustand with devtools.
 * Each domain (auth, UI, notifications) has its own slice.
 *
 * Future phases will add auth slice (Phase 2), agent state (Phase 3), etc.
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

// ── Types ───────────────────────────────────────────────────

export type Theme = "light" | "dark" | "system";
export type Locale = "en" | "hi" | "ar";

export interface Notification {
  id: string;
  type: "success" | "error" | "warning" | "info";
  title: string;
  message?: string;
  duration?: number;
}

// ── UI Slice ────────────────────────────────────────────────

interface UIState {
  theme: Theme;
  locale: Locale;
  sidebarCollapsed: boolean;
  notifications: Notification[];

  setTheme: (theme: Theme) => void;
  setLocale: (locale: Locale) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  addNotification: (notification: Omit<Notification, "id">) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;
}

export const useUIStore = create<UIState>()(
  devtools(
    persist(
      (set) => ({
        theme: "system",
        locale: "en",
        sidebarCollapsed: false,
        notifications: [],

        setTheme: (theme) => set({ theme }, false, "ui/setTheme"),

        setLocale: (locale) => set({ locale }, false, "ui/setLocale"),

        toggleSidebar: () =>
          set(
            (state) => ({ sidebarCollapsed: !state.sidebarCollapsed }),
            false,
            "ui/toggleSidebar"
          ),

        setSidebarCollapsed: (collapsed) =>
          set({ sidebarCollapsed: collapsed }, false, "ui/setSidebarCollapsed"),

        addNotification: (notification) =>
          set(
            (state) => ({
              notifications: [
                ...state.notifications,
                { ...notification, id: crypto.randomUUID() },
              ],
            }),
            false,
            "ui/addNotification"
          ),

        removeNotification: (id) =>
          set(
            (state) => ({
              notifications: state.notifications.filter((n) => n.id !== id),
            }),
            false,
            "ui/removeNotification"
          ),

        clearNotifications: () =>
          set({ notifications: [] }, false, "ui/clearNotifications"),
      }),
      {
        name: "banking-ui-store",
        partialize: (state) => ({
          theme: state.theme,
          locale: state.locale,
          sidebarCollapsed: state.sidebarCollapsed,
        }),
      }
    ),
    { name: "UIStore" }
  )
);

// ── Future Slices (stub for Phase 2+) ───────────────────────
// export { useAuthStore } from "./auth.store";
// export { useAgentStore } from "./agent.store";
