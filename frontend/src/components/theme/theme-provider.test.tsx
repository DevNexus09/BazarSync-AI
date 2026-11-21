import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme/theme-provider"

const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    },
  })
  document.documentElement.dataset.theme = "light"
  document.documentElement.style.colorScheme = "light"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("ThemeProvider", () => {
  it("permanently applies dark mode and clears an old preference", () => {
    storage.set("bazarsync-theme", "light")

    render(
      <ThemeProvider>
        <p>Seller workspace</p>
      </ThemeProvider>
    )

    expect(screen.getByText("Seller workspace")).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute("data-theme", "dark")
    expect(document.documentElement.style.colorScheme).toBe("dark")
    expect(storage.has("bazarsync-theme")).toBe(false)
  })
})
