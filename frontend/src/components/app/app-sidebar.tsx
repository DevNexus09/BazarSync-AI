import { NavLink } from "react-router-dom"

import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"

export default function AppSidebar() {
  return (
    <aside className="hidden border-r bg-background lg:fixed lg:inset-y-0 lg:z-40 lg:flex lg:w-64 lg:flex-col">
      <div className="flex h-16 items-center px-6 text-lg font-semibold text-foreground">
        BazarSync AI
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {appNavItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )
            }
          >
            <item.icon className="size-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t px-6 py-4 text-xs text-muted-foreground">
        AI-powered intelligence for Bangladeshi sellers
      </div>
    </aside>
  )
}
