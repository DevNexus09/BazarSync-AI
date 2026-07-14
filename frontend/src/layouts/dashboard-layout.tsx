import { useCallback, useEffect, useRef, useState } from "react"
import { Outlet } from "react-router-dom"

import AppHeader from "@/components/app/app-header"
import AppSidebar from "@/components/app/app-sidebar"
import { CopilotWidget } from "@/components/copilot/CopilotWidget"
import { RealtimeProvider } from "@/context/realtime-context"
import { useAuth } from "@/hooks/use-auth"

export default function DashboardLayout() {
  const { user } = useAuth()
  const [sidebarExpanded, setSidebarExpanded] = useState(false)
  const desktopToggleRef = useRef<HTMLButtonElement>(null)
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
      <div className="min-h-screen bg-background">
        <AppSidebar
          isExpanded={sidebarExpanded}
          onToggle={() => setSidebarExpanded((expanded) => !expanded)}
          onClose={closeSidebar}
          desktopToggleRef={desktopToggleRef}
        />
        <div className="flex min-h-screen flex-col lg:pl-[72px]">
          <AppHeader
            isSidebarOpen={sidebarExpanded}
            onMenuClick={() => setSidebarExpanded(true)}
            mobileMenuButtonRef={mobileToggleRef}
          />
          <main className="flex-1 px-4 pb-10 pt-6 sm:px-6 lg:px-8">
            <Outlet />
          </main>
        </div>
        <CopilotWidget />
      </div>
    </RealtimeProvider>
  )
}
