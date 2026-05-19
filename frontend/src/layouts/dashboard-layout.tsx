import { Outlet } from "react-router-dom"

import AppHeader from "@/components/app/app-header"
import AppSidebar from "@/components/app/app-sidebar"

export default function DashboardLayout() {
  return (
    <div className="min-h-screen bg-muted/40">
      <AppSidebar />
      <div className="flex min-h-screen flex-col lg:pl-64">
        <AppHeader />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
