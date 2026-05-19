import { Outlet } from "react-router-dom"

export default function RootLayout() {
  return (
    <div className="theme min-h-screen bg-background text-foreground">
      <Outlet />
    </div>
  )
}
