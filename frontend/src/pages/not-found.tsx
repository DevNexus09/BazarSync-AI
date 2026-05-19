import { useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-6">
      <div className="max-w-md rounded-xl border bg-background p-6 text-center shadow-sm">
        <h1 className="text-2xl font-semibold text-foreground">
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
