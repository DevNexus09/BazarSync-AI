import {
  Activity,
  ClipboardList,
  LayoutDashboard,
  LineChart,
  MessageCircle,
  Package,
  Sparkles,
  Settings,
  Users,
} from "lucide-react"

import type { NavItem } from "@/types/navigation"

export const appNavItems: NavItem[] = [
  {
    label: "Dashboard",
    path: "/app/dashboard",
    icon: LayoutDashboard,
    description: "AI operations center",
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
    label: "Recommendations",
    path: "/app/recommendations",
    icon: Sparkles,
    description: "Next-best actions",
  },
  {
    label: "Inventory Intelligence",
    path: "/app/inventory-intelligence",
    icon: ClipboardList,
    description: "Stockout risk and reorder planning",
  },
  {
    label: "Telegram Alerts",
    path: "/app/telegram-alerts",
    icon: MessageCircle,
    description: "BazarSync AI Telegram alerts",
  },
  {
    label: "Pricing Analytics",
    path: "/app/pricing",
    icon: LineChart,
    description: "Price elasticity insights",
  },
  {
    label: "Realtime Monitoring",
    path: "/app/realtime",
    icon: Activity,
    description: "Live marketplace tracking",
    comingSoon: true,
  },
  {
    label: "Settings",
    path: "/app/profile",
    icon: Settings,
    description: "Account preferences",
  },
]
