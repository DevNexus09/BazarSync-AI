import type { LucideIcon } from "lucide-react"

export type NavItem = {
  label: string
  path: string
  icon: LucideIcon
  description?: string
  comingSoon?: boolean
}
