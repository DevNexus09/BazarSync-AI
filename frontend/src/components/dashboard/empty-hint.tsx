import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"

type EmptyHintProps = {
  message: string
  actionLabel?: string
  to?: string
}

// Tells the seller why a widget is empty and where to go to fill it.
export function EmptyHint({ message, actionLabel, to }: EmptyHintProps) {
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-border/60 bg-muted/30 p-4 text-xs text-muted-foreground">
      <span>{message}</span>
      {actionLabel && to ? (
        <Button variant="outline" size="xs" asChild>
          <Link to={to}>{actionLabel}</Link>
        </Button>
      ) : null}
    </div>
  )
}
