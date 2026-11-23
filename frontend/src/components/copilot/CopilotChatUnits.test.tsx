import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { CopilotMarkdown } from "@/components/copilot/CopilotMarkdown"
import { CopilotQuestionInput } from "@/components/copilot/CopilotQuestionInput"
import {
  classifyCopilotError,
  domainLabel,
  langAttribute,
  resolveUiLanguage,
  toolLabel,
} from "@/components/copilot/copilot-i18n"

describe("CopilotMarkdown", () => {
  it("renders bold, lists and tables as elements", () => {
    render(
      <CopilotMarkdown
        text={"**Quick recommendation**\n- Restock Product A\n- Review fees\n\n| Product | Stock |\n| --- | --- |\n| Product A | 4 |"}
      />
    )

    expect(screen.getByText("Quick recommendation").tagName).toBe("STRONG")
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.getByRole("columnheader", { name: "Product" })).toBeInTheDocument()
    expect(screen.getByRole("cell", { name: "4" })).toBeInTheDocument()
  })

  it("never turns answer text into HTML", () => {
    const { container } = render(<CopilotMarkdown text={'<img src=x onerror="alert(1)"> <script>bad()</script>'} />)

    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("script")).toBeNull()
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument()
  })

  it("keeps plain multi-line text", () => {
    render(<CopilotMarkdown text={"Line one\nLine two"} />)
    expect(screen.getByText(/Line one/)).toBeInTheDocument()
    expect(screen.getByText(/Line two/)).toBeInTheDocument()
  })
})

describe("copilot i18n helpers", () => {
  it("classifies errors by kind", () => {
    expect(classifyCopilotError({ response: { status: 429 } })).toBe("rate_limited")
    expect(classifyCopilotError({ code: "ECONNABORTED", message: "timeout of 30000ms exceeded" })).toBe("timeout")
    expect(classifyCopilotError({ response: { status: 503 } })).toBe("server")
    expect(classifyCopilotError({ code: "ERR_NETWORK", message: "Network Error" })).toBe("network")
    expect(classifyCopilotError(new Error("boom"))).toBe("generic")
  })

  it("labels languages, domains and tools for people", () => {
    expect(langAttribute("banglish")).toBe("bn-Latn")
    expect(langAttribute("bn")).toBe("bn")
    expect(langAttribute(undefined, "আমার বিক্রি")).toBe("bn")
    expect(langAttribute(undefined, "my sales")).toBeUndefined()
    expect(domainLabel("SALES_REVENUE")).toBe("Sales")
    expect(domainLabel("SALES_REVENUE", "bn")).toBe("বিক্রি")
    expect(domainLabel("SOMETHING_NEW")).toBe("Something new")
    expect(toolLabel("get_inventory_risks")).toBe("Inventory risks")
    expect(resolveUiLanguage("auto", "banglish")).toBe("banglish")
    expect(resolveUiLanguage("bn", "en")).toBe("bn")
    expect(resolveUiLanguage("auto", null)).toBe("en")
  })
})

describe("CopilotQuestionInput", () => {
  it("does not send while an IME is composing (Bangla keyboards, Safari ordering)", () => {
    const onSubmit = vi.fn()
    render(<CopilotQuestionInput onSubmit={onSubmit} onEscape={vi.fn()} />)
    const input = screen.getByLabelText(/ask copilot a business question/i)

    fireEvent.change(input, { target: { value: "আমার বিক্রি" } })
    fireEvent.keyDown(input, { key: "Enter", isComposing: true })
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 })
    expect(onSubmit).not.toHaveBeenCalled()

    fireEvent.keyDown(input, { key: "Enter" })
    expect(onSubmit).toHaveBeenCalledWith("আমার বিক্রি")
  })

  it("restores a question and shows a counter near the limit", async () => {
    const { rerender } = render(<CopilotQuestionInput onSubmit={vi.fn()} onEscape={vi.fn()} restore={null} />)
    rerender(<CopilotQuestionInput onSubmit={vi.fn()} onEscape={vi.fn()} restore={{ text: "Why is revenue down?", nonce: 1 }} />)

    const input = screen.getByLabelText(/ask copilot a business question/i) as HTMLTextAreaElement
    expect(input.value).toBe("Why is revenue down?")

    fireEvent.change(input, { target: { value: "x".repeat(1700) } })
    expect(screen.getByText("1700/2000")).toBeInTheDocument()

    await userEvent.clear(input)
    expect(screen.queryByText(/\/2000/)).toBeNull()
  })
})

describe("CopilotStageSteps", () => {
  it("shows one status line that follows the streamed stage in each language", async () => {
    const { CopilotStageSteps } = await import("@/components/copilot/CopilotStageSteps")
    const { rerender } = render(<CopilotStageSteps stage={{ stage: "understanding" }} language="en" />)
    expect(screen.getByRole("status")).toHaveTextContent("Thinking…")

    rerender(<CopilotStageSteps stage={{ stage: "tool", tool: "Revenue summary", status: "SUCCEEDED" }} language="en" />)
    expect(screen.getByRole("status")).toHaveTextContent("Checking revenue summary…")

    rerender(<CopilotStageSteps stage={{ stage: "writing" }} language="banglish" />)
    expect(screen.getByRole("status")).toHaveTextContent("Preparing answer…")

    rerender(<CopilotStageSteps stage={null} language="bn" />)
    expect(screen.getByRole("status")).toHaveTextContent("বিশ্লেষণ করা হচ্ছে…")
  })
})

describe("CopilotChatPanel full-page mode", () => {
  it("switches between side panel and full page", async () => {
    const { CopilotChatPanel } = await import("@/components/copilot/CopilotChatPanel")
    const onToggle = vi.fn()
    const { rerender } = render(
      <CopilotChatPanel open onClose={() => {}} expanded={false} onToggleExpanded={onToggle}>
        <p>body</p>
      </CopilotChatPanel>
    )

    const toggle = screen.getByRole("button", { name: /full page/i })
    expect(toggle).toHaveAttribute("aria-pressed", "false")
    expect(screen.getByTestId("copilot-chat-panel")).not.toHaveAttribute("data-expanded")
    await userEvent.click(toggle)
    expect(onToggle).toHaveBeenCalledTimes(1)

    rerender(
      <CopilotChatPanel open onClose={() => {}} expanded onToggleExpanded={onToggle}>
        <p>body</p>
      </CopilotChatPanel>
    )
    expect(screen.getByRole("button", { name: /full page/i })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByTestId("copilot-chat-panel")).toHaveAttribute("data-expanded")
  })
})
