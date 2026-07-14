import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import {
  resolveInitialTheme,
  themeStorageKey,
  ThemeContext,
  type Theme,
} from "@/components/theme/theme-context"

type ThemeProviderProps = {
  children: ReactNode
}

function readStoredTheme(): string | null {
  try {
    return window.localStorage?.getItem(themeStorageKey) ?? null
  } catch {
    return null
  }
}

function readSystemPreference(): boolean {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() =>
    resolveInitialTheme(readStoredTheme(), readSystemPreference())
  )

  const setTheme = useCallback((nextTheme: Theme) => {
    setThemeState(nextTheme)
    try {
      window.localStorage?.setItem(themeStorageKey, nextTheme)
    } catch {
      // The theme still applies for this session when storage is unavailable.
    }
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark")
  }, [setTheme, theme])

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.style.colorScheme = theme
  }, [theme])

  const value = useMemo(
    () => ({ theme, setTheme, toggleTheme }),
    [setTheme, theme, toggleTheme]
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
