import * as React from "react"
import { isAxiosError } from "axios"
import { motion, useReducedMotion } from "framer-motion"
import { Link, useNavigate } from "react-router-dom"
import {
  Activity,
  Bot,
  Cpu,
  LayoutDashboard,
  Loader2,
  PlayCircle,
  MessagesSquare,
  Sparkles,
  Zap,
} from "lucide-react"

import { PublicHeader } from "@/components/public/public-header"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"

const featurePreviews = [
  {
    icon: LayoutDashboard,
    title: "Products",
    caption: "Catalog clarity",
    bars: [35, 54, 42, 70, 62],
    tone: "bg-primary",
  },
  {
    icon: Activity,
    title: "Inventory",
    caption: "Coverage signals",
    bars: [64, 46, 58, 34, 27],
    tone: "bg-info",
  },
  {
    icon: Cpu,
    title: "Competitors",
    caption: "Market movement",
    bars: [28, 42, 38, 62, 78],
    tone: "bg-warning",
  },
  {
    icon: Sparkles,
    title: "Pricing",
    caption: "Margin-safe moves",
    bars: [36, 40, 58, 54, 73],
    tone: "bg-accent",
  },
  {
    icon: Zap,
    title: "Revenue",
    caption: "Profit direction",
    bars: [30, 48, 45, 68, 82],
    tone: "bg-success",
  },
  {
    icon: Bot,
    title: "AI Copilot",
    caption: "Decisions with evidence",
    bars: [44, 32, 60, 48, 74],
    tone: "bg-primary",
  },
]

function FeaturePreview({
  feature,
  index,
  reducedMotion,
}: {
  feature: (typeof featurePreviews)[number]
  index: number
  reducedMotion: boolean
}) {
  const Icon = feature.icon

  return (
    <motion.div
      initial={reducedMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: reducedMotion ? 0 : index * 0.035 }}
      className="rounded-xl border border-border/60 bg-card/60 px-3 py-3 text-left shadow-[0_0_0_1px_rgb(var(--primary)/.04)] backdrop-blur"
    >
      <div className="flex items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-3.5" aria-hidden="true" />
        </span>
        <span className="min-w-0 truncate text-xs font-semibold text-foreground">
          {feature.title}
        </span>
      </div>
      <div className="mt-2 flex h-7 items-end gap-1" aria-hidden="true">
        {feature.bars.map((height, barIndex) => (
          <span
            key={`${feature.title}-${barIndex}`}
            className={`flex-1 rounded-sm ${feature.tone}`}
            style={{ height: `${height}%`, opacity: 0.35 + barIndex * 0.1 }}
          />
        ))}
      </div>
      <p className="mt-2 truncate text-[10px] text-muted-foreground">{feature.caption}</p>
    </motion.div>
  )
}

export default function LandingPage() {
  const { status, startDemo } = useAuth()
  const navigate = useNavigate()
  const reducedMotion = Boolean(useReducedMotion())
  const isAuthenticated = status === "authenticated"
  const getStartedPath = isAuthenticated ? "/app/dashboard" : "/login"
  const [demoState, setDemoState] = React.useState<"idle" | "opening" | "waking">("idle")
  const [demoError, setDemoError] = React.useState<string | null>(null)

  const handleExperience = async () => {
    setDemoError(null)
    setDemoState("opening")
    // The free demo server sleeps when idle; tell visitors why the first open is slow.
    const wakeTimer = window.setTimeout(() => setDemoState("waking"), 4000)
    try {
      await startDemo()
      navigate("/app/dashboard")
    } catch (error) {
      const detail = isAxiosError<{ detail?: unknown }>(error) ? error.response?.data?.detail : null
      setDemoError(
        typeof detail === "string" ? detail : "The demo is not reachable right now. Please try again shortly."
      )
      setDemoState("idle")
    } finally {
      window.clearTimeout(wakeTimer)
    }
  }

  return (
    <div className="relative min-h-[100dvh] overflow-hidden bg-background">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_18%,_rgb(var(--primary)/.22),_transparent_42%),radial-gradient(circle_at_85%_70%,_rgb(var(--accent)/.1),_transparent_34%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.18] [background-image:linear-gradient(rgb(var(--foreground)/.05)_1px,transparent_1px),linear-gradient(90deg,rgb(var(--foreground)/.05)_1px,transparent_1px)] [background-size:48px_48px] [mask-image:linear-gradient(to_bottom,black,transparent_72%)]"
      />

      <PublicHeader
        action={
          <Link
            to={isAuthenticated ? "/app/dashboard" : "/login"}
            className="rounded-lg px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          >
            {isAuthenticated ? "Dashboard" : "Sign in"}
          </Link>
        }
      />

      <main className="relative z-10 mx-auto flex min-h-[calc(100dvh-72px)] w-full max-w-6xl flex-col items-center justify-center px-4 pb-6 pt-4 text-center sm:px-6 lg:px-8">
        <motion.div
          initial={reducedMotion ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.26, ease: "easeOut" }}
          className="max-w-3xl"
        >
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.24em] text-primary">
            <MessagesSquare className="size-3.5" aria-hidden="true" />
            Marketplace intelligence
          </div>
          <h1 className="heading-font text-[clamp(3.2rem,8vw,6.6rem)] font-bold leading-[0.95] tracking-[-0.055em] text-foreground">
            BazarSync <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">AI</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-[clamp(1.2rem,2.4vw,1.75rem)] font-medium leading-tight text-foreground">
            AI-powered marketplace intelligence for smarter selling.
          </p>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
            Understand products, inventory, pricing, competitors, revenue, and opportunities from one intelligent platform.
          </p>
          <div className="mt-6 flex flex-col items-center gap-3">
            <Button asChild size="lg" className="px-6">
              <Link to={getStartedPath}>
                Get Started
                <Zap className="size-4" aria-hidden="true" />
              </Link>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="lg"
              className="px-6"
              onClick={handleExperience}
              disabled={demoState !== "idle"}
            >
              {demoState === "idle" ? (
                <PlayCircle className="size-4" aria-hidden="true" />
              ) : (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              )}
              Experience BazarSync
            </Button>
            <p className="min-h-5 max-w-sm text-xs text-muted-foreground" role="status" aria-live="polite">
              {demoState === "opening" && "Opening the demo store…"}
              {demoState === "waking" && "Waking up the demo server. The first visit can take up to a minute."}
              {demoState === "idle" && !demoError && "No sign-up needed. Explore a live demo store."}
              {demoState === "idle" && demoError && <span className="text-destructive">{demoError}</span>}
            </p>
          </div>
        </motion.div>

        <div className="mt-8 grid w-full max-w-5xl grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
          {featurePreviews.map((feature, index) => (
            <FeaturePreview
              key={feature.title}
              feature={feature}
              index={index}
              reducedMotion={reducedMotion}
            />
          ))}
        </div>
      </main>
    </div>
  )
}
