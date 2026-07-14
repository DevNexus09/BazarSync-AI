import { useEffect, useRef, useState } from "react"
import type { RefObject } from "react"
import { NavLink, useLocation } from "react-router-dom"
import { Menu, Moon, Sun, X } from "lucide-react"

import { ComingSoonModal } from "@/components/common/coming-soon-modal"
import { useTheme } from "@/components/theme/use-theme"
import { useComingSoon } from "@/hooks/useComingSoon"
import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"

type AppSidebarProps = {
  isExpanded: boolean
  onToggle: () => void
  onClose: () => void
  desktopToggleRef: RefObject<HTMLButtonElement | null>
}

function isDesktopViewport() {
  if (typeof window === "undefined") {
    return false
  }

  return window.matchMedia?.("(min-width: 1024px)").matches ?? window.innerWidth >= 1024
}

export default function AppSidebar({
  isExpanded,
  onToggle,
  onClose,
  desktopToggleRef,
}: AppSidebarProps) {
  const location = useLocation()
  const comingSoon = useComingSoon()
  const previousPathRef = useRef(location.pathname)
  const [isHovered, setIsHovered] = useState(false)
  const [hasFocusWithin, setHasFocusWithin] = useState(false)
  const { theme, toggleTheme } = useTheme()
  const isHoverExpanded = isHovered && isDesktopViewport()
  const isVisuallyExpanded = isExpanded || isHoverExpanded

  useEffect(() => {
    const pathChanged = previousPathRef.current !== location.pathname
    previousPathRef.current = location.pathname

    if (pathChanged && isExpanded) {
      onClose()
    }
  }, [isExpanded, location.pathname, onClose])

  useEffect(() => {
    if (!isExpanded) {
      return
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [isExpanded, onClose])

  const handleNavigation = (item: (typeof appNavItems)[number]) => {
    if (!item.comingSoon && !isDesktopViewport()) {
      onClose()
    }
  }

  return (
    <>
      {isExpanded ? (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-[55] bg-overlay/65 backdrop-blur-[2px] transition-opacity duration-300 motion-reduce:transition-none lg:bg-transparent lg:backdrop-blur-none"
          onClick={onClose}
        />
      ) : null}

      <aside
        data-testid="app-sidebar"
        aria-label="Primary navigation"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => {
          setIsHovered(false)
          if (isDesktopViewport() && isExpanded) {
            onClose()
          }
        }}
        onFocusCapture={() => setHasFocusWithin(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setHasFocusWithin(false)
          }
        }}
        className={cn(
          "fixed inset-y-0 left-0 z-[60] flex w-[min(88vw,300px)] -translate-x-full flex-col overflow-hidden bg-sidebar/95 shadow-[18px_0_60px_rgb(var(--overlay)/.32)] backdrop-blur-xl transition-[width,transform,background-color,box-shadow,backdrop-filter] duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none lg:translate-x-0 lg:w-[72px] lg:bg-transparent lg:shadow-none lg:backdrop-blur-none",
          isExpanded ? "translate-x-0" : "",
          isVisuallyExpanded
            ? "lg:w-[272px] lg:bg-sidebar/10 lg:shadow-[18px_0_80px_rgb(var(--overlay)/.18)] lg:backdrop-blur-2xl"
            : ""
        )}
      >
        <div className="flex h-20 shrink-0 items-center px-3">
          <button
            ref={desktopToggleRef}
            type="button"
            aria-label={isExpanded ? "Collapse navigation" : "Expand navigation"}
            aria-expanded={isExpanded}
            aria-controls="primary-navigation"
            title={isExpanded ? "Collapse navigation" : "Expand navigation"}
            className={cn(
              "group flex min-w-0 items-center rounded-xl p-2.5 text-left transition-colors duration-300 ease-out hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70",
              isVisuallyExpanded ? "w-full gap-3" : "w-full justify-center"
            )}
            onClick={onToggle}
          >
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/15 font-heading text-lg font-bold text-primary shadow-[0_0_24px_rgb(var(--primary)/.16)]"
            >
              B
            </span>
            <span
              className={cn(
                "min-w-0 overflow-hidden whitespace-nowrap font-heading text-sm font-semibold tracking-wide text-foreground transition-[max-width,opacity,transform] duration-[320ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none",
                isVisuallyExpanded
                  ? "max-w-[160px] translate-x-0 opacity-100 delay-75"
                  : "max-w-0 -translate-x-2 opacity-0"
              )}
            >
              BazarSync AI
            </span>
            <span
              aria-hidden="true"
              className={cn(
                "ml-auto text-muted-foreground transition-opacity duration-[260ms] ease-out motion-reduce:transition-none",
                isVisuallyExpanded ? "opacity-100" : "hidden"
              )}
            >
              {isExpanded ? <X className="size-4" /> : <Menu className="size-4" />}
            </span>
          </button>
        </div>

        <nav
          id="primary-navigation"
          aria-label="Dashboard pages"
          className="sidebar-scrollbar-hidden flex flex-1 flex-col gap-2 overflow-x-hidden overflow-y-auto px-3 py-5"
        >
          {appNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              title={item.label}
              aria-label={item.label}
              onClick={(event) => {
                comingSoon.handleNavClick(event, item)
                if (!event.defaultPrevented) {
                  handleNavigation(item)
                }
              }}
              className={({ isActive }) =>
                cn(
                  "group/item relative flex h-12 shrink-0 items-center gap-3 rounded-xl px-3 text-sm font-medium text-sidebar-foreground/70 transition-[background-color,color,box-shadow] duration-300 ease-out hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 motion-reduce:transition-none",
                  isVisuallyExpanded ? "justify-start" : "justify-center",
                  isActive ? "text-sidebar-foreground" : ""
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon
                    aria-hidden="true"
                    className={cn(
                      "size-[21px] shrink-0 transition-colors duration-300 ease-out motion-reduce:transition-none",
                      isActive
                        ? "text-primary"
                        : "text-sidebar-foreground/70 group-hover/item:text-sidebar-foreground"
                    )}
                  />
                  <span
                    data-testid={`sidebar-label-${item.label}`}
                    className={cn(
                      "min-w-0 overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-[320ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none",
                      isVisuallyExpanded
                        ? "max-w-[190px] translate-x-0 opacity-100 delay-75"
                        : "max-w-0 -translate-x-2 opacity-0"
                    )}
                  >
                    {item.label}
                  </span>
                  {item.comingSoon && isVisuallyExpanded ? (
                    <span className="ml-auto rounded-full border border-sidebar-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-sidebar-foreground/60">
                      Soon
                    </span>
                  ) : null}
                  {!isVisuallyExpanded ? (
                    <span
                      aria-hidden="true"
                      role="tooltip"
                      className="pointer-events-none absolute left-[calc(100%+0.75rem)] z-[70] hidden whitespace-nowrap rounded-lg border border-popover-foreground/15 bg-popover/95 px-3 py-2 text-xs font-medium text-popover-foreground opacity-0 shadow-xl transition-opacity duration-150 group-hover/item:block group-hover/item:opacity-100 group-focus-visible/item:block group-focus-visible/item:opacity-100 lg:block"
                    >
                      {item.label}
                    </span>
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="shrink-0 px-3 py-3">
          <div className="h-10">
            <button
              type="button"
              role="switch"
              aria-checked={theme === "dark"}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              tabIndex={isExpanded || isHovered || hasFocusWithin ? 0 : -1}
              aria-hidden={!(isExpanded || isHovered || hasFocusWithin)}
              onClick={toggleTheme}
              className={cn(
                "flex h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-xs font-semibold text-sidebar-foreground/70 transition-[background-color,color,opacity] duration-300 ease-out hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 motion-reduce:transition-none",
                isVisuallyExpanded ? "justify-start" : "justify-center",
                isExpanded || isHovered || hasFocusWithin
                  ? "pointer-events-auto opacity-100"
                  : "pointer-events-none opacity-0"
              )}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  toggleTheme()
                }
              }}
            >
              {theme === "dark" ? (
                <Sun className="size-4 shrink-0" aria-hidden="true" />
              ) : (
                <Moon className="size-4 shrink-0" aria-hidden="true" />
              )}
              <span
                className={cn(
                  "overflow-hidden whitespace-nowrap transition-[max-width,opacity] duration-[320ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none",
                  isVisuallyExpanded
                    ? "max-w-[190px] opacity-100 delay-75"
                    : "max-w-0 opacity-0"
                )}
              >
                {theme === "dark" ? "Light mode" : "Dark mode"}
              </span>
            </button>
          </div>
          <p
            className={cn(
              "overflow-hidden whitespace-nowrap px-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/45 transition-[max-width,opacity] duration-[320ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none",
              isVisuallyExpanded
                ? "max-w-[190px] opacity-100 delay-75"
                : "max-w-0 opacity-0"
            )}
          >
            Seller workspace
          </p>
        </div>
      </aside>

      <ComingSoonModal open={comingSoon.open} onClose={comingSoon.onClose} />
    </>
  )
}
