import {
  Activity,
  Bell,
  LayoutDashboard,
  LineChart,
  Package,
  Sparkles,
  Users,
} from "lucide-react"

import type { NavItem } from "@/types/navigation"

export const appNavItems: NavItem[] = [
  {
    label: "Overview",
    path: "/app/dashboard",
    icon: LayoutDashboard,
    description: "Core marketplace pulse",
  },
  {
    label: "Products",
    path: "/app/products",
    icon: Package,
    description: "Catalog for AI pricing",
  },
  {
    label: "Competitors",
    path: "/app/competitors",
    icon: Users,
    description: "Competitive benchmarking",
  },
  {
    label: "AI Recommendations",
    path: "/app/recommendations",
    icon: Sparkles,
    description: "Next-best actions",
  },
  {
    label: "Pricing Analytics",
    path: "/app/pricing",
    icon: LineChart,
    description: "Price elasticity insights",
  },
  {
    label: "WhatsApp Alerts",
    path: "/app/alerts",
    icon: Bell,
    description: "Seller notifications",
  },
  {
    label: "Realtime Monitoring",
    path: "/app/realtime",
    icon: Activity,
    description: "Live marketplace tracking",
  },
]
