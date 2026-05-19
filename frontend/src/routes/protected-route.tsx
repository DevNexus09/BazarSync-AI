import { Navigate, Outlet, useLocation } from "react-router-dom"

import { LoadingState } from "@/components/common/loading-state"
import { useAuth } from "@/hooks/use-auth"

export default function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === "loading") {
    return <LoadingState label="Checking your session..." />
  }

  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
