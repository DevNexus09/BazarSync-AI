import { useEffect } from "react"
import { Sparkles, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type ComingSoonModalProps = {
  open: boolean
  onClose: () => void
  className?: string
}

export function ComingSoonModal({ open, onClose, className }: ComingSoonModalProps) {
  useEffect(() => {
    if (!open) {
      return
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [onClose, open])

  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Coming Soon"
        className={cn(
          "relative w-full max-w-md rounded-2xl border bg-background p-6 shadow-xl",
          "animate-in fade-in zoom-in-95",
          className
        )}
      >
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Sparkles className="size-5" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Coming Soon
              </p>
              <h2 className="text-lg font-semibold text-foreground">Coming Soon</h2>
            </div>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onClose}>
            <X className="size-4" />
          </Button>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          This module is currently under development and will be available in a
          future release of BazarSync AI.
        </p>
        <div className="mt-5 inline-flex items-center rounded-full border border-dashed px-3 py-1 text-xs font-semibold text-muted-foreground">
          Coming Soon
        </div>
      </div>
    </div>
  )
}
