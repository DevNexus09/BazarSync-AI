import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { CopilotAssistantMessage } from "@/components/copilot/CopilotAssistantMessage"
import { headlineFigure } from "@/components/copilot/copilot-i18n"
import type { CopilotLocalMessage } from "@/types/copilot"

type AssistantMessage = Extract<CopilotLocalMessage, { role: "assistant" }>

const base: AssistantMessage = {
  id: "m1",
  role: "assistant",
  content: "Black Casual Shoes For Men: reorder 72",
  confidence: "LOW",
  questionType: "ANALYTIC",
  domainsUsed: ["SALES_REVENUE"],
  toolsUsed: [{ tool_name: "get_revenue_summary", domain: "SALES_REVENUE", status: "SUCCEEDED", evidence_count: 1, missing_data_count: 0 }],
  evidence: [
    { evidence_id: "rag:1", source_type: "INVENTORY_LIFECYCLE", title: "Stock received for Sandak NIPUN", event_time: "2026-11-12T03:22:00+06:00", freshness: "FRESH" },
  ],
  missingData: [{ message: "Supplier lead time is missing." }],
  dataFreshness: [],
  recommendedNextSteps: ["Review cited evidence."],
  memoryCoverageWarning: true,
  actionProposal: null,
}

describe("CopilotAssistantMessage", () => {
  it("leads with the answer; confidence, domains and next steps are never shown", () => {
    render(<CopilotAssistantMessage message={base} />)

    expect(screen.getByText("Black Casual Shoes For Men: reorder 72")).toBeInTheDocument()
    for (const junk of [/confidence/i, /^sales$/i, /not indexed/i, /next steps/i, /review cited evidence/i]) {
      expect(screen.queryByText(junk)).toBeNull()
    }
  })

  it("keeps sources collapsed until opened, then lists tools, memory with freshness and what is not recorded", async () => {
    render(<CopilotAssistantMessage message={base} />)

    const sources = screen.getByText(/sources/i).closest("details") as HTMLDetailsElement
    expect(sources).not.toHaveAttribute("open")
    expect(screen.getByText(/sources/i)).toHaveTextContent("2")

    await userEvent.click(screen.getByText(/sources/i))

    expect(sources).toHaveAttribute("open")
    const panel = within(sources)
    expect(panel.getByText("Revenue summary")).toBeInTheDocument()
    expect(panel.getByText("Stock received for Sandak NIPUN")).toBeInTheDocument()
    expect(panel.getByText("Fresh")).toBeInTheDocument()
    expect(panel.getByText("2026-11-12")).toBeInTheDocument()
    expect(panel.getByText("Supplier lead time is missing.")).toBeInTheDocument()
  })

  it("hides sources when the answer used no tools or memory", () => {
    render(<CopilotAssistantMessage message={{ ...base, toolsUsed: [], evidence: [], missingData: [] }} />)
    expect(screen.queryByText(/sources/i)).toBeNull()
  })

  it("shows a headline figure only when the summary states exactly one", () => {
    render(<CopilotAssistantMessage message={{ ...base, summary: "Revenue was BDT 290,360.28 from 1 to 15 November.", content: "Revenue was **BDT 290,360.28** from 1 to 15 November, down 5.6% on the previous period." }} />)
    expect(screen.getByTestId("copilot-headline")).toHaveTextContent("BDT 290,360.28")
  })
})

describe("headlineFigure", () => {
  it("picks the single money or count figure the answer states", () => {
    expect(headlineFigure("Revenue was BDT 290,360.28 in total.")).toBe("BDT 290,360.28")
    expect(headlineFigure("মোট বিক্রি ৳২,৯০,৩৬০.২৮")).toBe("৳২,৯০,৩৬০.২৮")
    expect(headlineFigure("You received 156 units of stock.")).toBe("156 units")
    expect(headlineFigure("You have 15 products.")).toBe("15 products")
  })

  it("returns nothing for zero or several figures, or bare numbers", () => {
    expect(headlineFigure("No invoices are recorded.")).toBeNull()
    expect(headlineFigure("Top: BDT 127,470 and BDT 82,718.")).toBeNull()
    expect(headlineFigure("Between 2026-11-01 and 2026-11-15")).toBeNull()
  })
})
