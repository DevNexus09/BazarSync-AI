import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme/theme-provider"
import { resolveInitialTheme } from "@/components/theme/theme-context"
import { useTheme } from "@/components/theme/use-theme"

function ThemeHarness() {
  const { theme, toggleTheme } = useTheme()

  return (
    <button type="button" onClick={toggleTheme}>
      {theme}
    </button>
  )
}

function setMatchMedia(prefersDark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" && prefersDark,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    onchange: null,
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    },
  })
  document.documentElement.removeAttribute("data-theme")
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("ThemeProvider", () => {
  it("prefers a saved theme over the system preference", () => {
    expect(resolveInitialTheme("light", true)).toBe("light")
    expect(resolveInitialTheme("dark", false)).toBe("dark")
  })

  it("uses the system theme when no saved preference exists", () => {
    expect(resolveInitialTheme(null, true)).toBe("dark")
    expect(resolveInitialTheme(null, false)).toBe("light")
  })

  it("applies the root attribute and persists a user toggle", async () => {
    setMatchMedia(true)
    render(
      <ThemeProvider>
        <ThemeHarness />
      </ThemeProvider>
    )

    expect(screen.getByRole("button")).toHaveTextContent("dark")
    expect(document.documentElement).toHaveAttribute("data-theme", "dark")

    fireEvent.click(screen.getByRole("button"))

    expect(screen.getByRole("button")).toHaveTextContent("light")
    expect(document.documentElement).toHaveAttribute("data-theme", "light")
    expect(storage.get("bazarsync-theme")).toBe("light")
  })
})
