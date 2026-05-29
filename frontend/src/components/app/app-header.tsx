import { useMemo } from "react"
import { NavLink, useLocation } from "react-router-dom"
import { Bell, Search } from "lucide-react"

import UserMenu from "@/components/app/user-menu"
import { ComingSoonModal } from "@/components/common/coming-soon-modal"
<<<<<<< HEAD
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useComingSoon } from "@/hooks/useComingSoon"
import { useTelegramConnection } from "@/hooks/useTelegramConnection"
=======
import { useComingSoon } from "@/hooks/useComingSoon"
>>>>>>> develop
import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"
import type { TelegramConnectionState } from "@/types/telegram"

export default function AppHeader() {
  const location = useLocation()
  const comingSoon = useComingSoon()
<<<<<<< HEAD
  const telegram = useTelegramConnection()

  const telegramState: TelegramConnectionState = telegram.status.isError
    ? "error"
    : telegram.status.isLoading
      ? "connecting"
      : telegram.status.data?.isConnected
        ? "connected"
        : "not_connected"
=======
>>>>>>> develop

  const activeItem = useMemo(
    () =>
      appNavItems.find((item) => location.pathname.startsWith(item.path)) ??
      appNavItems[0],
    [location.pathname]
  )

  return (
<<<<<<< HEAD
    <div className="sticky top-0 z-30">
      <div className="px-4 pt-4 sm:px-6 lg:px-8">
        <div className="rounded-2xl border border-border/70 bg-card/70 p-4 shadow-[0_0_0_1px_rgba(59,130,246,0.12),_0_20px_50px_rgba(4,8,16,0.55)] backdrop-blur">
          <div className="flex flex-wrap items-center gap-4">
            <div className="min-w-[180px]">
              <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                BazarSync AI
              </p>
              <h1 className="heading-font text-lg font-semibold text-foreground">
                {activeItem?.label ?? "BazarSync AI"}
              </h1>
            </div>
            <div className="flex min-w-[220px] flex-1 items-center">
              <div className="relative w-full">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search products, competitors, alerts..."
                  className="pl-9"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="hidden items-center gap-2 rounded-xl border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground lg:flex">
                <span className="font-semibold text-foreground">Telegram</span>
                <TelegramStatusBadge state={telegramState} />
              </div>
              <Button variant="ghost" size="icon" aria-label="Notifications">
                <Bell className="size-4" />
              </Button>
              <UserMenu />
            </div>
          </div>
=======
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
>>>>>>> develop
        </div>
      </div>
      <nav className="flex gap-2 overflow-x-auto px-4 py-3 lg:hidden">
        {appNavItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            onClick={(event) => comingSoon.handleNavClick(event, item)}
            className={({ isActive }) =>
              cn(
                "whitespace-nowrap rounded-full border border-border/70 px-3 py-1 text-xs font-medium transition-colors",
                isActive
                  ? "bg-primary/20 text-foreground"
                  : "bg-card/60 text-muted-foreground"
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
