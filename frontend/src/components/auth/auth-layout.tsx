import type { ReactNode } from "react"

type AuthLayoutProps = {
  title: string
  description: string
  children: ReactNode
  footer?: ReactNode
  sideContent?: ReactNode
}

export function AuthLayout({
  title,
  description,
  children,
  footer,
  sideContent,
}: AuthLayoutProps) {
  return (
    <div className="min-h-screen bg-muted/40">
      <div className="mx-auto grid w-full max-w-6xl items-center gap-8 px-4 py-12 lg:grid-cols-[1fr_0.9fr]">
        <div className="space-y-6">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              BazarSync AI
            </p>
            <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
          <div className="rounded-2xl border bg-background p-6 shadow-sm">
            {children}
          </div>
          {footer ? (
            <div className="text-center text-sm text-muted-foreground">
              {footer}
            </div>
          ) : null}
        </div>
        {sideContent ? (
          <div className="hidden lg:flex">
            <div className="w-full rounded-3xl border bg-background p-6 shadow-sm">
              {sideContent}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
