import { describe, expect, it } from "vitest"

import { createStrings, ui } from "@/lib/ui-i18n"

describe("i18n lookup", () => {
  const t = createStrings({
    greeting: { en: "Hello {name}", bn: "হ্যালো {name}" },
    onlyEnglish: { en: "Runs out in {days} days" },
  })

  it("uses Bangla when an entry exists and falls back to English otherwise", () => {
    expect(t("greeting", { name: "Rina" }, "bn")).toBe("হ্যালো Rina")
    expect(t("onlyEnglish", { days: 3 }, "bn")).toBe("Runs out in 3 days")
    expect(t("greeting", { name: "Rina" })).toBe("Hello Rina")
  })

  it("leaves unknown placeholders visible instead of dropping them", () => {
    expect(t("greeting")).toBe("Hello {name}")
    expect(ui("updated", { time: "2 hours ago" })).toBe("Updated 2 hours ago")
  })
})
