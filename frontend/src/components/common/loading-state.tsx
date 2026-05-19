import { cn } from "@/lib/utils"

type LoadingStateProps = {
  label?: string
  className?: string
  size?: "sm" | "md" | "lg"
}

const sizeMap = {
  sm: "size-4 border",
  md: "size-6 border-2",
  lg: "size-8 border-[3px]",
} as const

export function LoadingState({
  label = "Loading...",
  className,
  size = "md",
}: LoadingStateProps) {
  return (
    <div
      className={cn(
        "flex w-full flex-col items-center justify-center gap-2 py-12 text-muted-foreground",
        className
      )}
      role="status"
      aria-live="polite"
    >
      <div
        className={cn(
          "animate-spin rounded-full border-muted border-t-primary",
          sizeMap[size]
        )}
      />
      <span className="text-sm">{label}</span>
    </div>
  )
}
