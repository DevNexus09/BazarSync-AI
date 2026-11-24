import { Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"

export function DemoBanner() {
  const { user, logout } = useAuth()

  if (!user?.isDemo) {
    return null
  }

  const leaveDemo = (to: string) => {
    logout()
    // Full load: beats the protected-route redirect to /login and drops cached demo data.
    window.location.assign(to)
  }

  return (
    <div
      role="region"
      aria-label="Demo mode"
      className="mx-4 mt-3 flex flex-col gap-2 rounded-2xl border border-primary/25 bg-primary/10 px-4 py-2.5 text-sm sm:mx-6 sm:flex-row sm:items-center lg:mx-8"
    >
      <Sparkles className="hidden size-4 shrink-0 text-primary sm:block" aria-hidden="true" />
      <p className="flex-1 text-foreground">
        <span className="font-semibold">You're exploring a demo store.</span>{" "}
        <span className="text-muted-foreground">
          Generate recommendations, run price simulations and ask the AI Copilot anything. Edits to
          store data are turned off.
        </span>
      </p>
      <div className="flex shrink-0 gap-2">
        <Button size="sm" onClick={() => leaveDemo("/register")}>
          Create your account
        </Button>
        <Button size="sm" variant="ghost" onClick={() => leaveDemo("/")}>
          Exit demo
        </Button>
      </div>
    </div>
  )
}
