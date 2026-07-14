import type { ReactNode } from "react"
import { Sparkles } from "lucide-react"
import { Link } from "react-router-dom"

import { PublicThemeToggle } from "@/components/public/public-theme-toggle"
import { cn } from "@/lib/utils"

type PublicHeaderProps = {
  action?: ReactNode
  className?: string
}

export function PublicHeader({ action, className }: PublicHeaderProps) {
  return (
    <header
      className={cn(
        "relative z-30 mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8",
        className
      )}
    >
      <Link
        to="/"
        aria-label="BazarSync AI home"
        className="group inline-flex items-center gap-2.5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
      >
        <span className="flex size-8 items-center justify-center rounded-lg border border-primary/25 bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
          <Sparkles className="size-4" aria-hidden="true" />
        </span>
        <span className="heading-font text-sm font-semibold tracking-wide text-foreground sm:text-base">
          BazarSync AI
        </span>
      </Link>
      <nav aria-label="Public navigation" className="flex items-center gap-1.5 sm:gap-3">
        <PublicThemeToggle />
        {action}
      </nav>
    </header>
  )
}
