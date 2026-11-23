import { useMemo } from "react"
import type { RefObject } from "react"
import { Link, useLocation } from "react-router-dom"
import { Bell, Menu, Search } from "lucide-react"

import UserMenu from "@/components/app/user-menu"
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useTelegramConnection } from "@/hooks/useTelegramConnection"
import { appNavItems, telegramNavItem } from "@/routes/nav-config"
import type { TelegramConnectionState } from "@/types/telegram"

type AppHeaderProps = {
  isSidebarOpen?: boolean
  onMenuClick?: () => void
  mobileMenuButtonRef?: RefObject<HTMLButtonElement | null>
}

export default function AppHeader({
  isSidebarOpen = false,
  onMenuClick,
  mobileMenuButtonRef,
}: AppHeaderProps) {
  const location = useLocation()
  const telegram = useTelegramConnection()

  const telegramState: TelegramConnectionState = telegram.status.isError
    ? "error"
    : telegram.status.isLoading
      ? "connecting"
      : telegram.status.data?.isConnected
        ? "connected"
        : "not_connected"

  const activeItem = useMemo(
    () =>
      [...appNavItems, telegramNavItem].find((item) =>
        location.pathname.startsWith(item.path)
      ) ??
      appNavItems[0],
    [location.pathname]
  )

  return (
    <div className="sticky top-0 z-30">
      <div className="px-4 pt-4 sm:px-6 lg:px-8">
        <div className="rounded-2xl border border-border/60 bg-card/75 p-4 shadow-[0_0_0_1px_rgb(var(--primary)/.12),_0_20px_50px_rgb(var(--overlay)/.38)] backdrop-blur-2xl">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex min-w-[180px] items-center gap-3">
              <Button
                ref={mobileMenuButtonRef}
                variant="outline"
                size="icon"
                className="shrink-0 lg:hidden"
                aria-label={isSidebarOpen ? "Close navigation" : "Open navigation"}
                aria-expanded={isSidebarOpen}
                aria-controls="primary-navigation"
                onClick={onMenuClick}
              >
                <Menu className="size-4" aria-hidden="true" />
              </Button>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-primary">
                  BazarSync AI
                </p>
                <h1 className="heading-font text-lg font-semibold text-foreground">
                  {activeItem?.label ?? "BazarSync AI"}
                </h1>
              </div>
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
              <Link
                to={telegramNavItem.path}
                title="Open Telegram alerts"
                className="flex items-center gap-2 rounded-xl border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="hidden font-semibold text-foreground sm:inline">Telegram</span>
                <TelegramStatusBadge state={telegramState} />
              </Link>
              <Button variant="ghost" size="icon" aria-label="Notifications">
                <Bell className="size-4" />
              </Button>
              <UserMenu />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
