type Highlight = {
  title: string
  description: string
}

type AuthHighlightsProps = {
  title: string
  description: string
  highlights: Highlight[]
}

export function AuthHighlights({
  title,
  description,
  highlights,
}: AuthHighlightsProps) {
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
          BazarSync AI Intelligence
        </p>
        <h2 className="heading-font text-2xl font-semibold text-foreground">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="space-y-3">
        {highlights.map((item) => (
          <div
            key={item.title}
            className="rounded-2xl border border-border/60 bg-card/70 p-4 shadow-[0_0_0_1px_rgb(var(--accent)/.15)]"
          >
            <h3 className="text-sm font-semibold text-foreground">
              {item.title}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {item.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
