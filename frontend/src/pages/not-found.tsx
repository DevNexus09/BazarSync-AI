import { useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="glass-panel max-w-md p-6 text-center">
        <h1 className="heading-font text-2xl font-semibold text-foreground">
          Page not found
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you’re looking for doesn’t exist. Let’s get you back to
          BazarSync AI.
        </p>
        <Button className="mt-4" onClick={() => navigate("/app/dashboard")}>
          Back to dashboard
        </Button>
      </div>
    </div>
  )
}
