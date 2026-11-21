import { useEffect, type ReactNode } from "react"

type ThemeProviderProps = {
  children: ReactNode
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = "dark"
    root.style.colorScheme = "dark"

    try {
      window.localStorage?.removeItem("bazarsync-theme")
    } catch {
      // Dark mode remains locked when storage is unavailable.
    }
  }, [])

  return children
}
