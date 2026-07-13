import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { CopilotAssistantMessage } from "@/components/copilot/CopilotAssistantMessage"
import { CopilotEvidenceList } from "@/components/copilot/CopilotEvidenceList"
import { CopilotMissingDataPanel } from "@/components/copilot/CopilotMissingDataPanel"
import type { CopilotLocalMessage } from "@/types/copilot"

describe("Copilot evidence and missing data UI", () => {
  it("expands evidence and renders snippets safely", async () => {
    render(
      <CopilotEvidenceList
        evidence={[
          {
            evidence_id: "products:1",
            domain: "PRODUCT_CATALOG",
            source_type: "products",
            source_table: "products",
            source_id: "1",
            product_name: "Product A",
            title: "Product evidence",
            summary: "Direct product row.",
            snippet: "<strong>unsafe html</strong>",
            event_time: "2026-07-01T00:00:00+00:00",
            freshness: "FRESH",
            confidence: "HIGH",
          },
        ]}
      />
    )

    await userEvent.click(screen.getByText(/product evidence/i))
    expect(screen.getByText("<strong>unsafe html</strong>")).toBeInTheDocument()
    expect(document.querySelector("strong")).toBeNull()
    expect(screen.getByText(/product_catalog/i)).toBeInTheDocument()
    expect(screen.getByText(/fresh/i)).toBeInTheDocument()
  })

  it("groups missing data by domain and marks blocking items", () => {
    render(
      <CopilotMissingDataPanel
        missingData={[
          {
            key: "MISSING_PRODUCT_COST",
            domain: "PROFIT_MARGIN",
            source_table: "products",
            message: "Product cost is missing.",
            blocking: true,
            next_action: "Add product landed cost.",
            setup_href: "/dashboard/products",
            required_for: ["profit", "margin"],
            severity: "HIGH",
          },
          {
            key: "MISSING_SALES_HISTORY",
            domain: "SALES_REVENUE",
            message: "Sales history is incomplete.",
            blocking: false,
            next_action: "Import sales records.",
            required_for: ["revenue diagnosis"],
            severity: "MEDIUM",
          },
        ]}
      />
    )

    expect(screen.getByText("PROFIT_MARGIN")).toBeInTheDocument()
    expect(screen.getByText("SALES_REVENUE")).toBeInTheDocument()
    expect(screen.getByText("Blocking")).toBeInTheDocument()
    expect(screen.getByText("Optional")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /open setup/i })).toHaveAttribute(
      "href",
      "/dashboard/products"
    )
  })

  it("renders assistant confidence, domains, tools, and freshness warnings", () => {
    const message: Extract<CopilotLocalMessage, { role: "assistant" }> = {
      id: "m1",
      role: "assistant",
      content: "Answer",
      confidence: "LOW",
      questionType: "ANALYTIC",
      domainsUsed: ["SALES_REVENUE"],
      toolsUsed: [
        {
          tool_name: "get_revenue_summary",
          domain: "SALES_REVENUE",
          status: "SUCCEEDED",
          evidence_count: 1,
          missing_data_count: 0,
        },
      ],
      evidence: [],
      missingData: [],
      dataFreshness: [
        {
          domain: "SALES_REVENUE",
          source_table: "sales_records",
          latest_available_at: "2024-01-01T00:00:00+00:00",
          status: "STALE",
          message: "Sales data is stale.",
        },
      ],
      recommendedNextSteps: [],
      actionProposal: null,
    }

    render(<CopilotAssistantMessage message={message} />)

    expect(screen.getByText(/confidence: low/i)).toBeInTheDocument()
    expect(screen.getAllByText("SALES_REVENUE").length).toBeGreaterThan(0)
    expect(screen.getByText("get_revenue_summary")).toBeInTheDocument()
    expect(screen.getByText(/data freshness warnings/i)).toBeInTheDocument()
    expect(screen.getByText(/sales data is stale/i)).toBeInTheDocument()
  })
})
