import {
  Activity,
  LayoutDashboard,
  LineChart,
  MessageCircle,
  Package,
  Shield,
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
    label: "War Room",
    path: "/app/war-room",
    icon: Shield,
    description: "Realtime competitor intelligence",
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
<<<<<<< HEAD
    label: "Telegram Alerts",
    path: "/app/telegram-alerts",
    icon: MessageCircle,
    description: "BazarSync AI Telegram alerts",
  },
  {
    label: "Analytics",
    path: "/app/analytics",
    icon: LineChart,
    description: "Market analytics suite",
    comingSoon: true,
=======
    label: "Pricing Analytics",
    path: "/app/pricing",
    icon: LineChart,
    description: "Price elasticity insights",
    comingSoon: true,
  },
  {
    label: "Telegram Alerts",
    path: "/app/telegram-alerts",
    icon: MessageCircle,
    description: "BazarSync AI Telegram alerts",
>>>>>>> develop
  },
  {
    label: "Realtime Monitoring",
    path: "/app/realtime",
    icon: Activity,
    description: "Live marketplace tracking",
    comingSoon: true,
<<<<<<< HEAD
  },
  {
    label: "Settings",
    path: "/app/profile",
    icon: Settings,
    description: "Account preferences",
=======
>>>>>>> develop
  },
]
