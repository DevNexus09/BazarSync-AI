import { useCallback, useEffect, useRef, useState } from "react"
import { Outlet } from "react-router-dom"

import AppHeader from "@/components/app/app-header"
import AppSidebar from "@/components/app/app-sidebar"
import { DemoBanner } from "@/components/app/demo-banner"
import { CopilotWidget } from "@/components/copilot/CopilotWidget"
import { RealtimeProvider } from "@/context/realtime-context"
import { useAuth } from "@/hooks/use-auth"

export default function DashboardLayout() {
  const { user } = useAuth()
  const [sidebarExpanded, setSidebarExpanded] = useState(false)
  const mobileToggleRef = useRef<HTMLButtonElement>(null)

  const closeSidebar = useCallback(() => {
    setSidebarExpanded(false)
    window.setTimeout(() => {
      mobileToggleRef.current?.focus()
    }, 0)
  }, [])

  useEffect(() => {
    const handleResize = () => {
      const isDesktop =
        window.matchMedia?.("(min-width: 1024px)").matches ?? window.innerWidth >= 1024
      if (!isDesktop && sidebarExpanded) {
        setSidebarExpanded(false)
      }
    }

    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [sidebarExpanded])

  return (
    <RealtimeProvider sellerId={user?.id}>
      <div className="app-theme app-shell-canvas relative min-h-screen overflow-x-clip bg-background">
        <div
          aria-hidden="true"
          className="app-shell-grid pointer-events-none fixed inset-0"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none fixed -left-28 top-1/3 size-72 rounded-full bg-primary/10 blur-3xl"
        />
        <div className="glass-surface fixed left-4 top-4 z-[65] hidden size-16 items-center justify-center rounded-[24px] lg:flex">
          <span className="flex size-10 items-center justify-center rounded-[14px] bg-primary font-heading text-lg font-bold text-primary-foreground shadow-[0_8px_22px_rgb(var(--primary)/.22)]">
            B
          </span>
        </div>
        <AppSidebar
          isExpanded={sidebarExpanded}
          onClose={closeSidebar}
        />
        <div className="relative z-10 flex min-h-screen flex-col lg:pl-24">
          <AppHeader
            isSidebarOpen={sidebarExpanded}
            onMenuClick={() => setSidebarExpanded(true)}
            mobileMenuButtonRef={mobileToggleRef}
          />
          <DemoBanner />
          <main className="flex-1 px-4 pb-12 pt-6 sm:px-6 lg:px-8">
            <div className="mx-auto w-full max-w-[1600px]">
              <Outlet />
            </div>
          </main>
        </div>
        <CopilotWidget />
      </div>
    </RealtimeProvider>
  )
}
