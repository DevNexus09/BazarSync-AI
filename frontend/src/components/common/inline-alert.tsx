import { cn } from "@/lib/utils"

type InlineAlertProps = {
  title?: string
  message: string
  variant?: "success" | "error" | "info"
}

const variantStyles: Record<NonNullable<InlineAlertProps["variant"]>, string> =
  {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    error: "border-destructive/30 bg-destructive/10 text-destructive",
    info: "border-border bg-muted/40 text-foreground",
  }

export function InlineAlert({
  title,
  message,
  variant = "info",
}: InlineAlertProps) {
  return (
    <div className={cn("rounded-lg border px-3 py-2 text-sm", variantStyles[variant])}>
      {title ? <div className="font-semibold">{title}</div> : null}
      <div>{message}</div>
    </div>
  )
}
