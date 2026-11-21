import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { CopilotAssistantMessage } from "@/components/copilot/CopilotAssistantMessage"
import type { CopilotLocalMessage } from "@/types/copilot"

describe("CopilotAssistantMessage", () => {
  it("shows only the answer, never confidence, domains, tools, freshness, evidence or missing data", () => {
    const message: Extract<CopilotLocalMessage, { role: "assistant" }> = {
      id: "m1",
      role: "assistant",
      content: "Black Casual Shoes For Men: reorder 72",
      confidence: "LOW",
      questionType: "ANALYTIC",
      domainsUsed: ["SALES_REVENUE"],
      toolsUsed: [
        { tool_name: "get_revenue_summary", domain: "SALES_REVENUE", status: "FAILED", evidence_count: 1, missing_data_count: 0 },
      ],
      evidence: [{ evidence_id: "sales_records:1", source_type: "sales_records", title: "Sales import" }],
      missingData: [{ message: "Supplier lead time is missing." }],
      dataFreshness: [
        { domain: "SALES_REVENUE", source_table: "sales_records", latest_available_at: null, status: "STALE", message: "Sales data is stale." },
      ],
      recommendedNextSteps: ["Review cited evidence."],
      memoryCoverageWarning: true,
      actionProposal: null,
    }

    render(<CopilotAssistantMessage message={message} />)

    expect(screen.getByText("Black Casual Shoes For Men: reorder 72")).toBeInTheDocument()
    for (const junk of [/confidence/i, /^sales$/i, /revenue summary/i, /failed/i, /stale/i, /evidence/i, /supplier lead time/i, /not indexed/i, /next steps/i]) {
      expect(screen.queryByText(junk)).toBeNull()
    }
  })
})
