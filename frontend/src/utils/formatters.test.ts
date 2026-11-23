import { describe, expect, it } from "vitest"

import { formatMoney, formatRelativeTime, hoursSince } from "@/utils/formatters"

describe("formatMoney", () => {
  it("formats decimal strings exactly, without float rounding", () => {
    expect(formatMoney("349.50")).toMatch(/349\.50$/)
    expect(formatMoney("349.00")).toMatch(/349$/)
    // Beyond float precision: a float would print ...992.00, the string stays exact.
    expect(formatMoney("90071992547409.93")?.replace(/[^\d.]/g, "")).toBe("90071992547409.93")
  })

  it("accepts numbers", () => {
    expect(formatMoney(120)).toContain("120")
  })

  it("returns null for missing or non-numeric values instead of a fake zero", () => {
    expect(formatMoney(null)).toBeNull()
    expect(formatMoney(undefined)).toBeNull()
    expect(formatMoney("")).toBeNull()
    expect(formatMoney("abc")).toBeNull()
  })
})

describe("formatRelativeTime", () => {
  const now = new Date("2026-11-23T12:00:00Z")

  it("uses the largest whole unit", () => {
    expect(formatRelativeTime("2026-11-23T10:00:00Z", now)).toBe("2 hours ago")
    expect(formatRelativeTime("2026-11-23T11:55:00Z", now)).toBe("5 minutes ago")
    expect(formatRelativeTime("2026-11-20T12:00:00Z", now)).toBe("3 days ago")
    expect(formatRelativeTime("2026-11-26T12:00:00Z", now)).toBe("in 3 days")
    expect(formatRelativeTime("2026-11-23T11:59:50Z", now)).toBe("now")
  })

  it("returns null for missing or invalid input", () => {
    expect(formatRelativeTime(null, now)).toBeNull()
    expect(formatRelativeTime("not a date", now)).toBeNull()
    expect(hoursSince(undefined, now)).toBeNull()
    expect(hoursSince("2026-11-23T09:00:00Z", now)).toBe(3)
  })
})
