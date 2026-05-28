import { useMemo } from "react"
import { NavLink, useLocation } from "react-router-dom"

import UserMenu from "@/components/app/user-menu"
import { ComingSoonModal } from "@/components/common/coming-soon-modal"
import { useComingSoon } from "@/hooks/useComingSoon"
import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"

export default function AppHeader() {
  const location = useLocation()
  const comingSoon = useComingSoon()

  const activeItem = useMemo(
    () =>
      appNavItems.find((item) => location.pathname.startsWith(item.path)) ??
      appNavItems[0],
    [location.pathname]
  )

  return (
    <div className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur">
      <div className="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            BazarSync AI
          </p>
          <h1 className="text-lg font-semibold text-foreground">
            {activeItem?.label ?? "BazarSync AI"}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <UserMenu />
        </div>
      </div>
      <nav className="flex gap-2 overflow-x-auto border-t px-4 py-2 lg:hidden">
        {appNavItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            onClick={(event) => comingSoon.handleNavClick(event, item)}
            className={({ isActive }) =>
              cn(
                "whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <ComingSoonModal open={comingSoon.open} onClose={comingSoon.onClose} />
    </div>
  )
}
