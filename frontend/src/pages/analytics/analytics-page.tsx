import { Sparkles } from "lucide-react"

export default function AnalyticsPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="glass-panel w-full max-w-lg p-8 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/15 text-primary shadow-[0_0_18px_rgba(59,130,246,0.35)]">
          <Sparkles className="size-6" />
        </div>
        <p className="mt-4 text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
          Coming Soon
        </p>
        <h1 className="heading-font mt-2 text-2xl font-semibold text-foreground">
          Analytics
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Advanced realtime intelligence modules are under development.
        </p>
      </div>
    </div>
  )
}
