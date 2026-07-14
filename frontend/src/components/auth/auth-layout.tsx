import type { ReactNode } from "react"
import { motion } from "framer-motion"
import { LayoutDashboard } from "lucide-react"

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
    <div className="min-h-screen bg-background">
      <div className="mx-auto grid w-full max-w-6xl items-center gap-10 px-6 py-12 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary/15 text-primary shadow-[0_0_16px_rgb(var(--primary)/.35)]">
              <LayoutDashboard className="size-5" />
            </div>
            <div>
              <p className="heading-font text-lg font-semibold text-foreground">
                BazarSync AI
              </p>
              <p className="text-xs text-muted-foreground">
                BazarSync AI for Bangladeshi sellers
              </p>
            </div>
          </div>
          <div className="space-y-2">
            <h1 className="heading-font text-3xl font-semibold text-foreground">
              {title}
            </h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
          <div className="glass-panel p-6">{children}</div>
          {footer ? (
            <div className="text-center text-sm text-muted-foreground">
              {footer}
            </div>
          ) : null}
        </div>
        {sideContent ? (
          <motion.div
            className="hidden lg:flex"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <div className="glass-panel relative w-full overflow-hidden p-8">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgb(var(--primary)/.2),_transparent_55%)]" />
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-[linear-gradient(180deg,_transparent,_rgb(var(--overlay)/.6))]" />
              <div className="relative">{sideContent}</div>
            </div>
          </motion.div>
        ) : null}
      </div>
    </div>
  )
}
