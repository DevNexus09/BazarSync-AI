import { motion } from "framer-motion"
import { Link } from "react-router-dom"
import {
  Activity,
  Bot,
  Cpu,
  LayoutDashboard,
  MessagesSquare,
  Sparkles,
  Zap,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  whileInView: { opacity: 1, y: 0 },
  transition: { duration: 0.6 },
  viewport: { once: true, amount: 0.2 },
}

const features = [
  {
    icon: Activity,
    title: "Realtime intelligence",
    description: "Detect price shifts, stock risks, and category spikes instantly.",
  },
  {
    icon: Sparkles,
    title: "AI recommendations",
    description: "Turn signals into precise actions with confidence scoring.",
  },
  {
    icon: MessagesSquare,
    title: "Telegram alerts",
    description: "Route critical updates to your ops team in seconds.",
  },
  {
    icon: Cpu,
    title: "Competitive heatmaps",
    description: "Visualize competitor moves across catalog segments.",
  },
  {
    icon: Bot,
    title: "Autopilot insights",
    description: "Automate your response to fast-moving marketplace changes.",
  },
  {
    icon: Zap,
    title: "Opportunity scoring",
    description: "Prioritize the highest-impact opportunities every day.",
  },
]

const previewCards = [
  {
    title: "Urgency score",
    value: "92",
    delta: "+12% since last sync",
    tone: "text-emerald-300",
  },
  {
    title: "Live competitors",
    value: "184",
    delta: "Tracking 41 categories",
    tone: "text-sky-300",
  },
  {
    title: "AI actions",
    value: "27",
    delta: "New recommendations",
    tone: "text-violet-300",
  },
]

function SectionHeader({
  overline,
  title,
  description,
  align = "left",
}: {
  overline: string
  title: string
  description: string
  align?: "left" | "center"
}) {
  return (
    <div
      className={cn(
        "space-y-3",
        align === "center" ? "text-center" : "text-left"
      )}
    >
      <p className="text-xs font-semibold uppercase tracking-[0.4em] text-muted-foreground">
        {overline}
      </p>
      <h2 className="heading-font text-3xl font-semibold text-foreground">
        {title}
      </h2>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  )
}

export default function LandingPage() {
  return (
    <div className="relative overflow-hidden bg-background pb-24">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.18),_transparent_55%)]" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-[45%] bg-[radial-gradient(circle,_rgba(139,92,246,0.18),_transparent_60%)]" />

      <header className="relative z-10">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary/15 text-primary shadow-[0_0_18px_rgba(59,130,246,0.35)]">
              <LayoutDashboard className="size-5" />
            </div>
            <div>
              <p className="heading-font text-lg font-semibold text-foreground">
                BazarSync AI
              </p>
              <p className="text-xs text-muted-foreground">Realtime intelligence</p>
            </div>
          </div>
          <Button asChild size="lg">
            <Link to="/login">Get Started</Link>
          </Button>
        </div>
      </header>

      <main className="relative z-10">
        <section className="mx-auto flex w-full max-w-6xl flex-col gap-12 px-6 pb-20 pt-12 lg:flex-row lg:items-center">
          <motion.div {...fadeUp} className="flex-1 space-y-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/40 px-3 py-1 text-xs text-muted-foreground">
              <span className="size-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
              Live intelligence online
            </div>
            <h1 className="heading-font text-4xl font-semibold text-foreground lg:text-5xl">
              AI-Powered Market Intelligence for Bangladeshi Sellers
            </h1>
            <p className="text-base text-muted-foreground">
              BazarSync AI turns realtime signals into decisive actions — competitor
              monitoring, pricing intelligence, and AI recommendations designed for
              operational teams.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link to="/login">Get Started</Link>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <Link to="/register">Request Access</Link>
              </Button>
            </div>
            <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
              <span>Realtime monitoring</span>
              <span>AI recommendations</span>
              <span>Telegram alerts</span>
            </div>
          </motion.div>

          <motion.div
            {...fadeUp}
            className="flex-1"
            transition={{ duration: 0.7, delay: 0.1 }}
          >
            <div className="glass-panel relative overflow-hidden p-6">
              <div className="absolute inset-0 bg-[linear-gradient(135deg,_rgba(59,130,246,0.12),_transparent_60%)]" />
              <div className="relative space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      AI Operations
                    </p>
                    <p className="heading-font text-lg text-foreground">
                      Intelligence Preview
                    </p>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="size-2 animate-pulse rounded-full bg-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.6)]" />
                    Live
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {previewCards.map((card) => (
                    <div
                      key={card.title}
                      className="rounded-xl border border-border/60 bg-card/60 p-3"
                    >
                      <p className="text-xs text-muted-foreground">{card.title}</p>
                      <p className="mt-2 text-2xl font-semibold text-foreground">
                        {card.value}
                      </p>
                      <p className={cn("text-xs font-semibold", card.tone)}>
                        {card.delta}
                      </p>
                    </div>
                  ))}
                </div>
                <div className="rounded-xl border border-border/60 bg-card/50 p-4">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>Competitor price trend</span>
                    <span className="text-emerald-300">+4.2% opportunity</span>
                  </div>
                  <div className="mt-3 h-20 w-full rounded-lg bg-[linear-gradient(90deg,_rgba(59,130,246,0.45),_rgba(139,92,246,0.15))]" />
                </div>
              </div>
            </div>
          </motion.div>
        </section>

        <section className="mx-auto w-full max-w-6xl space-y-12 px-6">
          <motion.div {...fadeUp}>
            <SectionHeader
              overline="Features"
              title="Operational intelligence that feels real-time"
              description="Purpose-built modules for pricing, competitor monitoring, and AI-driven actions."
              align="center"
            />
          </motion.div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => (
              <motion.div
                key={feature.title}
                {...fadeUp}
                className="glass-panel group p-5 transition hover:-translate-y-1"
              >
                <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-[0_0_14px_rgba(59,130,246,0.35)]">
                  <feature.icon className="size-5" />
                </div>
                <h3 className="mt-4 text-lg font-semibold text-foreground">
                  {feature.title}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>
        </section>

        <section className="mx-auto mt-20 w-full max-w-6xl px-6">
          <motion.div {...fadeUp} className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
            <SectionHeader
              overline="Realtime intelligence"
              title="Stay ahead of pricing shocks and competitor moves"
              description="BazarSync AI monitors live marketplace signals, recalculates urgency, and pushes opportunity scores to your team in seconds."
            />
            <div className="glass-panel p-6">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Live signal feed</span>
                <span className="rounded-full border border-border/60 px-2 py-1 text-[10px] uppercase">
                  Updating
                </span>
              </div>
              <div className="mt-4 space-y-3">
                {[
                  "Competitor price drop detected",
                  "Urgency score recalculated",
                  "Stock risk threshold triggered",
                ].map((item) => (
                  <div
                    key={item}
                    className="flex items-center justify-between rounded-lg border border-border/60 bg-card/60 px-3 py-2 text-xs text-muted-foreground"
                  >
                    <span>{item}</span>
                    <span className="size-2 animate-pulse rounded-full bg-emerald-400" />
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </section>

        <section className="mx-auto mt-20 w-full max-w-6xl px-6">
          <motion.div {...fadeUp} className="grid gap-8 lg:grid-cols-2">
            <div className="glass-panel p-6">
              <SectionHeader
                overline="Telegram"
                title="Telegram alert preview"
                description="Deliver decisive alerts directly to your Telegram ops channel."
              />
              <div className="mt-5 space-y-3 text-xs text-muted-foreground">
                <div className="rounded-xl border border-border/60 bg-card/60 p-4">
                  <p className="text-sm font-semibold text-foreground">
                    BazarSync AI • @bazarsync_bot
                  </p>
                  <p className="mt-2">
                    Competitor median price dropped by 7%. Price gap: ৳410.
                    Recommendation: adjust to ৳1,890.
                  </p>
                </div>
                <div className="rounded-xl border border-border/60 bg-card/60 p-4">
                  <p className="text-sm font-semibold text-foreground">
                    Stock risk detected
                  </p>
                  <p className="mt-2">
                    Inventory projected to run out in 4 days. Lead time: 8 days.
                  </p>
                </div>
              </div>
            </div>

            <div className="glass-panel p-6">
              <SectionHeader
                overline="AI Recommendations"
                title="Preview AI actions"
                description="Summaries and next-best actions prioritized by confidence and opportunity."
              />
              <div className="mt-5 space-y-3">
                {[
                  "Increase price by 4% to regain margin",
                  "Bundle accessories for higher conversion",
                  "Replenish stock with fast-moving supplier",
                ].map((item) => (
                  <div
                    key={item}
                    className="rounded-xl border border-border/60 bg-card/60 px-4 py-3 text-sm text-muted-foreground"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </section>

        <section className="mx-auto mt-20 w-full max-w-6xl px-6">
          <motion.div {...fadeUp} className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="glass-panel p-6">
              <SectionHeader
                overline="Dashboard preview"
                title="AI Operations Center layout"
                description="Center your analytics, recommendation feed, and realtime monitoring in a single command view."
              />
              <div className="mt-6 grid gap-3 md:grid-cols-2">
                {["KPI cards", "Competitor heatmap", "Price trend charts", "Live recommendation feed"].map(
                  (item) => (
                    <div
                      key={item}
                      className="rounded-xl border border-border/60 bg-card/60 px-4 py-3 text-sm text-muted-foreground"
                    >
                      {item}
                    </div>
                  )
                )}
              </div>
            </div>
            <div className="glass-panel p-6">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>AI confidence</span>
                <span className="text-emerald-300">High</span>
              </div>
              <div className="mt-4 h-36 rounded-xl bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.35),_transparent_70%)]" />
              <p className="mt-4 text-sm text-muted-foreground">
                Confidence score and opportunity signals update live as your data
                streams in.
              </p>
            </div>
          </motion.div>
        </section>

        <section className="mx-auto mt-24 w-full max-w-6xl px-6">
          <motion.div {...fadeUp} className="glass-panel p-8 text-center">
            <h2 className="heading-font text-3xl font-semibold text-foreground">
              Ready to run BazarSync AI?
            </h2>
            <p className="mt-3 text-sm text-muted-foreground">
              Launch BazarSync AI and keep every seller decision ahead of the market.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Button asChild size="lg">
                <Link to="/login">Get Started</Link>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <Link to="/register">Schedule Demo</Link>
              </Button>
            </div>
          </motion.div>
        </section>
      </main>
    </div>
  )
}
