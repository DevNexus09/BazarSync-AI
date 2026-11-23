import {
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
    label: "Pricing Analytics",
    path: "/app/pricing",
    icon: LineChart,
    description: "Price elasticity insights",
  },
  {
    label: "Settings",
    path: "/app/profile",
    icon: Settings,
    description: "Account preferences",
  },
]

// Reached from the topbar Telegram status, not the sidebar; kept here so the header can title the page.
export const telegramNavItem: NavItem = {
  label: "Telegram Alerts",
  path: "/app/telegram-alerts",
  icon: MessageCircle,
  description: "BazarSync AI Telegram alerts",
}
