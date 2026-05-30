import { Outlet } from "react-router-dom"

import AppHeader from "@/components/app/app-header"
import AppSidebar from "@/components/app/app-sidebar"
import { RealtimeProvider } from "@/context/realtime-context"
import { useAuth } from "@/hooks/use-auth"

export default function DashboardLayout() {
  const { user } = useAuth()

  return (
    <RealtimeProvider sellerId={user?.id}>
      <div className="min-h-screen bg-background">
        <AppSidebar />
        <div className="flex min-h-screen flex-col transition-all lg:pl-20 lg:peer-hover:pl-64">
          <AppHeader />
          <main className="flex-1 px-4 pb-10 pt-6 sm:px-6 lg:px-8">
            <Outlet />
          </main>
        </div>
      </div>
    </RealtimeProvider>
  )
}
