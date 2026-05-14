/**
 * Route Architecture
 * ===================
 * Centralized route definitions using React Router v6.
 * Route groups:
 *  - Public: /login, /register (Phase 2)
 *  - Protected: /dashboard, /accounts, etc. (Phase 2+)
 *  - Admin: /admin/* (Phase 5+)
 *
 * Lazy loading is used for all page components to optimize bundle size.
 */

import { lazy, Suspense } from "react";
import {
  createBrowserRouter,
  RouterProvider,
  Outlet,
  Navigate,
} from "react-router-dom";

import { RootLayout } from "@components/layout/RootLayout";
import { PageLoader } from "@components/common/PageLoader";

// ── Lazy Page Imports ────────────────────────────────────────
// Phase 1: Placeholder pages only
const NotFoundPage = lazy(() => import("@pages/NotFoundPage"));
const HealthPage = lazy(() => import("@pages/HealthPage"));

// Phase 2+ (uncomment as implemented):
// const LoginPage = lazy(() => import("@pages/auth/LoginPage"));
// const DashboardPage = lazy(() => import("@pages/dashboard/DashboardPage"));
// const AccountsPage = lazy(() => import("@pages/accounts/AccountsPage"));
// const TransactionsPage = lazy(() => import("@pages/transactions/TransactionsPage"));
// const AgentsPage = lazy(() => import("@pages/agents/AgentsPage"));

// ── Route Guards (stubs for Phase 2) ────────────────────────
const ProtectedRoute = () => {
  // Phase 2 will check auth state here
  // const { isAuthenticated } = useAuthStore();
  // if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <Outlet />;
};

// ── Router Definition ────────────────────────────────────────
const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      // Public routes
      {
        path: "health",
        element: (
          <Suspense fallback={<PageLoader />}>
            <HealthPage />
          </Suspense>
        ),
      },

      // Protected routes (Phase 2+)
      {
        element: <ProtectedRoute />,
        children: [
          {
            index: true,
            element: <Navigate to="/health" replace />,
          },
          // {
          //   path: "dashboard",
          //   element: <Suspense fallback={<PageLoader />}><DashboardPage /></Suspense>,
          // },
        ],
      },

      // 404
      {
        path: "*",
        element: (
          <Suspense fallback={<PageLoader />}>
            <NotFoundPage />
          </Suspense>
        ),
      },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
