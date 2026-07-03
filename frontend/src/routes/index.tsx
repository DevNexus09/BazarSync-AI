import { createBrowserRouter, redirect } from "react-router-dom"

import RouteError from "@/components/common/route-error"
import DashboardLayout from "@/layouts/dashboard-layout"
import RootLayout from "@/layouts/root-layout"
import ProtectedRoute from "@/routes/protected-route"
import LoginPage from "@/pages/auth/login-page"
import RegisterPage from "@/pages/auth/register-page"
import NotFoundPage from "@/pages/not-found"
import LandingPage from "@/pages/landing/landing-page"

const router = createBrowserRouter([
  {
    path: "/",
    Component: RootLayout,
    ErrorBoundary: RouteError,
    children: [
      {
        index: true,
        Component: LandingPage,
      },
      { path: "login", Component: LoginPage },
      { path: "register", Component: RegisterPage },
      {
        path: "app",
        Component: ProtectedRoute,
        children: [
          {
            Component: DashboardLayout,
            children: [
              {
                index: true,
                loader: () => redirect("/app/dashboard"),
              },
              {
                path: "dashboard",
                lazy: async () => ({
                  Component: (await import("@/pages/dashboard/dashboard-page"))
                    .default,
                }),
              },
              {
                path: "competitors",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/competitors/competitors-page"
                  )).default,
                }),
              },
              {
                path: "products",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/products/product-list-page"
                  )).default,
                }),
              },
              {
                path: "products/new",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/products/product-form-page"
                  )).default,
                }),
              },
              {
                path: "products/:productId/edit",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/products/product-edit-page"
                  )).default,
                }),
              },
              {
                path: "recommendations",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/recommendations/recommendations-page"
                  )).default,
                }),
              },
              {
                path: "inventory-intelligence",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/inventory-intelligence/inventory-intelligence-page"
                  )).default,
                }),
              },
              {
                path: "pricing",
                lazy: async () => ({
                  Component: (await import("@/pages/pricing/pricing-page"))
                    .default,
                }),
              },
              {
                path: "pricing/fee-setup",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/pricing/marketplace-fee-setup-page"
                  )).default,
                }),
              },
              {
                path: "pricing/fee-policies",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/pricing/marketplace-fee-management-page"
                  )).default,
                }),
              },
              {
                path: "telegram-alerts",
                lazy: async () => ({
                  Component: (await import("@/pages/telegram-alerts-page")).default,
                }),
              },
              {
                path: "alerts",
                loader: () => redirect("/app/telegram-alerts"),
              },
              {
                path: "realtime",
                lazy: async () => ({
                  Component: (await import("@/pages/realtime/realtime-page"))
                    .default,
                }),
              },
              {
                path: "profile",
                lazy: async () => ({
                  Component: (await import("@/pages/profile/profile-page"))
                    .default,
                }),
              },
            ],
          },
        ],
      },
      { path: "*", Component: NotFoundPage },
    ],
  },
])

export default router
