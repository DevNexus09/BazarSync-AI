import { createBrowserRouter, redirect } from "react-router-dom"

import RouteError from "@/components/common/route-error"
import DashboardLayout from "@/layouts/dashboard-layout"
import RootLayout from "@/layouts/root-layout"
import ProtectedRoute from "@/routes/protected-route"
import LoginPage from "@/pages/auth/login-page"
import RegisterPage from "@/pages/auth/register-page"
import ForgotPasswordPage from "@/pages/auth/forgot-password-page"
import NotFoundPage from "@/pages/not-found"
import LandingPage from "@/pages/landing/landing-page"
import { inventoryV2Enabled, pricingV2Enabled } from "@/utils/env"

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
      { path: "forgot-password", Component: ForgotPasswordPage },
      { path: "forgot-password/verify", Component: ForgotPasswordPage },
      { path: "forgot-password/reset", Component: ForgotPasswordPage },
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
                path: "products/:productId",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/products/product-detail-page"
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
                path: "products/:productId/visibility",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/products/product-visibility-page"
                  )).default,
                }),
              },
              {
                path: "inventory/receipts/new",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/inventory/inventory-receipt-page"
                  )).default,
                }),
              },
              {
                path: "sales/import",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/sales/sales-import-page"
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
                  Component: inventoryV2Enabled
                    ? (await import("@/pages/inventory-intelligence/v2/inventory-intelligence-v2-page")).default
                    : (await import("@/pages/inventory-intelligence/inventory-intelligence-page")).default,
                }),
              },
              ...(pricingV2Enabled
                ? [
                    {
                      path: "pricing",
                      // Old links used /app/pricing?productId=<id>; send them to the workspace.
                      loader: ({ request }: { request: Request }) => {
                        const productId = new URL(request.url).searchParams.get("productId")
                        return productId ? redirect(`/app/pricing/${productId}`) : null
                      },
                      lazy: async () => ({
                        Component: (await import("@/pages/pricing/v2/pricing-overview-page")).default,
                      }),
                    },
                    {
                      path: "pricing/setup",
                      lazy: async () => ({
                        Component: (await import("@/pages/pricing/v2/pricing-setup-page")).default,
                      }),
                    },
                    {
                      path: "pricing/:productId",
                      lazy: async () => ({
                        Component: (await import("@/pages/pricing/v2/pricing-workspace-page")).default,
                      }),
                    },
                  ]
                : [
                    {
                      path: "pricing",
                      lazy: async () => ({
                        Component: (await import("@/pages/pricing/pricing-page")).default,
                      }),
                    },
                  ]),
              {
                path: "pricing/fee-setup",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/pricing/marketplace-fee-setup-page"
                  )).default,
                }),
              },
              {
                path: "pricing/policy-setup",
                lazy: async () => ({
                  Component: (await import(
                    "@/pages/pricing/pricing-policy-setup-page"
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
