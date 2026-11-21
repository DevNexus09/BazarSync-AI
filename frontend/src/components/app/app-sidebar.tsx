import { useEffect, useRef, useState } from "react"
import { NavLink, useLocation } from "react-router-dom"

import { ComingSoonModal } from "@/components/common/coming-soon-modal"
import { useComingSoon } from "@/hooks/useComingSoon"
import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"

type AppSidebarProps = {
  isExpanded: boolean
  onClose: () => void
}

function isDesktopViewport() {
  if (typeof window === "undefined") {
    return false
  }

  return window.matchMedia?.("(min-width: 1024px)").matches ?? window.innerWidth >= 1024
}

export default function AppSidebar({ isExpanded, onClose }: AppSidebarProps) {
  const location = useLocation()
  const comingSoon = useComingSoon()
  const previousPathRef = useRef(location.pathname)
  const [isHovered, setIsHovered] = useState(false)
  const isVisuallyExpanded = isExpanded || isHovered

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
          className="fixed inset-0 z-[55] bg-overlay/65 backdrop-blur-[2px] transition-opacity duration-300 motion-reduce:transition-none lg:hidden"
          onClick={onClose}
        />
      ) : null}

      <aside
        data-testid="app-sidebar"
        aria-label="Primary navigation"
        onMouseEnter={() => {
          if (isDesktopViewport()) {
            setIsHovered(true)
          }
        }}
        onMouseLeave={() => setIsHovered(false)}
        className={cn(
          "fixed bottom-4 left-4 top-20 z-[60] flex w-[min(84vw,248px)] -translate-x-[calc(100%+2rem)] flex-col overflow-hidden rounded-[24px] border border-border/40 bg-card/75 p-2.5 shadow-[0_22px_65px_rgb(var(--overlay)/.48)] backdrop-blur-2xl transition-[width,transform,background-color,box-shadow] duration-300 ease-out motion-reduce:transition-none lg:bottom-auto lg:top-24 lg:max-h-[calc(100dvh-7.5rem)] lg:w-16 lg:translate-x-0",
          isExpanded ? "translate-x-0" : "",
          isVisuallyExpanded ? "lg:w-[248px]" : ""
        )}
      >
        <nav
          id="primary-navigation"
          aria-label="Dashboard pages"
          className="sidebar-scrollbar-hidden flex flex-1 flex-col justify-center gap-1.5 overflow-y-auto"
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
                  "group flex min-h-11 items-center gap-3 rounded-full py-2.5 text-sm font-medium transition-[background-color,color,box-shadow,padding] duration-[250ms] ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 motion-reduce:transition-none",
                  isVisuallyExpanded ? "justify-start px-3.5" : "justify-center px-0",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-[0_8px_24px_rgb(var(--primary)/.24)]"
                    : "text-sidebar-foreground/70"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon
                    aria-hidden="true"
                    className={cn(
                      "size-[18px] shrink-0 transition-colors duration-[250ms] motion-reduce:transition-none",
                      isActive
                        ? "text-primary-foreground"
                        : "text-sidebar-foreground/70 group-hover:text-sidebar-foreground group-hover:drop-shadow-[0_0_9px_rgb(var(--accent))] group-focus-visible:text-sidebar-foreground group-focus-visible:drop-shadow-[0_0_9px_rgb(var(--accent))]"
                    )}
                  />
                  <span
                    data-testid={`sidebar-label-${item.label}`}
                    aria-hidden={!isVisuallyExpanded}
                    className={cn(
                      "min-w-0 overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-[250ms] motion-reduce:transition-none",
                      isVisuallyExpanded
                        ? "max-w-[180px] translate-x-0 opacity-100"
                        : "max-w-0 -translate-x-1 opacity-0"
                    )}
                  >
                    {item.label}
                  </span>
                  {item.comingSoon && isVisuallyExpanded ? (
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide",
                        isActive
                          ? "border-primary-foreground/25 text-primary-foreground/70"
                          : "border-sidebar-border text-sidebar-foreground/45"
                      )}
                    >
                      Soon
                    </span>
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <p
          aria-hidden={!isVisuallyExpanded}
          className={cn(
            "mt-3 overflow-hidden whitespace-nowrap border-t border-border/30 px-3.5 pt-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/40 transition-[max-height,opacity] duration-[250ms] motion-reduce:transition-none",
            isVisuallyExpanded ? "max-h-8 opacity-100" : "max-h-0 border-transparent pt-0 opacity-0"
          )}
        >
          Seller workspace
        </p>
      </aside>

      <ComingSoonModal open={comingSoon.open} onClose={comingSoon.onClose} />
    </>
  )
}
