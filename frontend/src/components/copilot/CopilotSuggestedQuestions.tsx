const suggestedQuestionGroups = [
  {
    title: "Business overview",
    questions: [
      "Summarize my business today.",
      "How many products do I have listed?",
      "Which products are missing setup data?",
    ],
  },
  {
    title: "Revenue",
    questions: [
      "What is my revenue this week?",
      "Why is revenue down?",
      "Which products generated the most revenue?",
    ],
  },
  {
    title: "Profit",
    questions: [
      "What is my estimated profit this month?",
      "Which products cannot calculate profit because of missing setup?",
    ],
  },
  {
    title: "Inventory",
    questions: [
      "What should I restock?",
      "Which products may stock out?",
      "Which products are overstocked?",
    ],
  },
  {
    title: "Competitors",
    questions: [
      "Which competitor is hurting me?",
      "Which products are being undercut?",
      "What changed in competitor prices?",
    ],
  },
  {
    title: "Pricing",
    questions: [
      "Which products need price changes?",
      "Which products are unsafe to discount?",
      "Can I lower price by 5%?",
    ],
  },
  {
    title: "Promotions",
    questions: [
      "Which promotion should I run?",
      "Which promotions worked before?",
      "Which products are suitable for flash sale?",
    ],
  },
  {
    title: "Dead stock",
    questions: [
      "Which products are becoming dead stock?",
      "How much capital is locked in dead stock?",
      "What recovery action should I take?",
    ],
  },
  {
    title: "SEO",
    questions: [
      "Which listings need SEO fixes?",
      "Which products have low visibility?",
    ],
  },
  {
    title: "Memory",
    questions: [
      "What happened last time sales dropped?",
      "Which recommendations worked before?",
    ],
  },
]

export function CopilotSuggestedQuestions({
  onSelect,
  disabled,
}: {
  onSelect: (question: string) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-3">
      {suggestedQuestionGroups.map((group) => (
        <section key={group.title}>
          <h4 className="mb-1.5 text-xs font-semibold text-muted-foreground">
            {group.title}
          </h4>
          <div className="flex flex-wrap gap-2">
            {group.questions.map((question) => (
              <button
                key={question}
                type="button"
                disabled={disabled}
                onClick={() => onSelect(question)}
                className="rounded-full border border-border/70 bg-card/70 px-3 py-1.5 text-left text-xs font-medium text-foreground transition hover:border-sky-400/40 hover:bg-sky-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/40 disabled:opacity-50"
              >
                {question}
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
