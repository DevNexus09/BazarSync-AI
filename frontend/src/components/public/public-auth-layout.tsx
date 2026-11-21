import type { ReactNode } from "react"
import { motion, useReducedMotion } from "framer-motion"

import { PublicHeader } from "@/components/public/public-header"

type PublicAuthLayoutProps = {
  title: string
  description: string
  children: ReactNode
  footer?: ReactNode
  action?: ReactNode
}

export function PublicAuthLayout({
  title,
  description,
  children,
  footer,
  action,
}: PublicAuthLayoutProps) {
  const shouldReduceMotion = useReducedMotion()

  return (
<div className="app-theme app-shell-canvas relative isolate min-h-[100dvh] overflow-y-auto bg-background">
<div className="app-shell-grid pointer-events-none absolute inset-0" aria-hidden="true" />
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_18%,_rgb(var(--primary)/.18),_transparent_42%),radial-gradient(circle_at_85%_70%,_rgb(var(--accent)/.08),_transparent_36%)]"
        aria-hidden="true"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-[18%] select-none text-center font-sans text-[clamp(5rem,14vw,14rem)] font-extrabold leading-none tracking-[-0.06em] text-foreground/[0.05]"
      >
        BazarSync AI
      </div>

      <PublicHeader action={action} />

      <main className="relative z-10 flex min-h-[calc(100dvh-72px)] items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
        <motion.section
          aria-labelledby="public-auth-title"
          initial={shouldReduceMotion ? false : { opacity: 0, y: 8, scale: 0.99 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.24, ease: "easeOut" }}
          className="w-full max-w-[420px] rounded-2xl border border-primary/15 bg-card/[0.78] p-5 shadow-[0_24px_80px_rgb(var(--overlay)/.24)] backdrop-blur-2xl sm:p-7"
        >
          <div className="mb-6 space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-primary">
              Seller workspace
            </p>
            <h1 id="public-auth-title" className="heading-font text-2xl font-semibold text-foreground">
              {title}
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">{description}</p>
          </div>

          {children}

          {footer ? (
            <div className="mt-6 border-t border-border/60 pt-5 text-center text-sm text-muted-foreground">
              {footer}
            </div>
          ) : null}
        </motion.section>
      </main>
    </div>
  )
}
