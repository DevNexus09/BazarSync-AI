import { createContext } from "react"

export type Theme = "light" | "dark"

export const themeStorageKey = "bazarsync-theme"

export type ThemeContextValue = {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

export const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

const isTheme = (value: string | null): value is Theme =>
  value === "light" || value === "dark"

export function resolveInitialTheme(
  storedTheme: string | null,
  systemPrefersDark: boolean
): Theme {
  if (isTheme(storedTheme)) {
    return storedTheme
  }

  return systemPrefersDark ? "dark" : "light"
}
