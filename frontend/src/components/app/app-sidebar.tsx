import { MotionConfig, motion } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import type { FocusEvent, PointerEvent } from "react"
import { NavLink, useLocation } from "react-router-dom"

import { ComingSoonModal } from "@/components/common/coming-soon-modal"
import { useComingSoon } from "@/hooks/useComingSoon"
import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"

type AppSidebarProps = {
  isExpanded: boolean
  onClose: () => void
}

export const SIDEBAR_COLLAPSE_DELAY_MS = 200

// Spring-like ease-out with no overshoot; shared by the shell, items and labels so they move as one object.
const GLASS_EASE = "ease-[cubic-bezier(0.22,1,0.36,1)]"

function isDesktopViewport() {
  if (typeof window === "undefined") {
    return false
  }

  return window.matchMedia?.("(min-width: 1024px)").matches ?? window.innerWidth >= 1024
}

function isKeyboardFocus(target: EventTarget) {
  try {
    return (target as Element).matches(":focus-visible")
  } catch {
    return true
  }
}

export default function AppSidebar({ isExpanded, onClose }: AppSidebarProps) {
  const location = useLocation()
  const comingSoon = useComingSoon()
  const previousPathRef = useRef(location.pathname)
  const collapseTimerRef = useRef<number | undefined>(undefined)
  const [isHovered, setIsHovered] = useState(false)
  const [hasKeyboardFocus, setHasKeyboardFocus] = useState(false)
  const isVisuallyExpanded = isExpanded || isHovered || hasKeyboardFocus

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

  useEffect(() => () => window.clearTimeout(collapseTimerRef.current), [])

  const handlePointerEnter = (event: PointerEvent) => {
    if (event.pointerType === "touch" || !isDesktopViewport()) {
      return
    }
    window.clearTimeout(collapseTimerRef.current)
    setIsHovered(true)
  }

  const handlePointerLeave = (event: PointerEvent) => {
    if (event.pointerType === "touch") {
      return
    }
    window.clearTimeout(collapseTimerRef.current)
    collapseTimerRef.current = window.setTimeout(
      () => setIsHovered(false),
      SIDEBAR_COLLAPSE_DELAY_MS
    )
  }

  const handleFocus = (event: FocusEvent) => {
    if (isDesktopViewport() && isKeyboardFocus(event.target)) {
      setHasKeyboardFocus(true)
    }
  }

  const handleBlur = (event: FocusEvent<HTMLElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setHasKeyboardFocus(false)
    }
  }

  const handleNavigation = (item: (typeof appNavItems)[number]) => {
    if (!item.comingSoon && !isDesktopViewport()) {
      onClose()
    }
  }

  return (
    <MotionConfig reducedMotion="user">
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
        data-expanded={isVisuallyExpanded}
        aria-label="Primary navigation"
        onPointerEnter={handlePointerEnter}
        onPointerLeave={handlePointerLeave}
        onFocus={handleFocus}
        onBlur={handleBlur}
        className={cn(
          "glass-surface fixed bottom-4 left-4 top-20 z-[60] flex w-[min(84vw,288px)] -translate-x-[calc(100%+2rem)] flex-col rounded-[30px] p-2.5 transition-[width,transform,border-radius] duration-[440ms] motion-reduce:transition-none lg:bottom-auto lg:top-1/2 lg:max-h-[calc(100dvh-12rem)] lg:w-16 lg:translate-x-0 lg:-translate-y-1/2 lg:rounded-[32px]",
          GLASS_EASE,
          isExpanded ? "translate-x-0" : "",
          isVisuallyExpanded ? "lg:w-[288px] lg:rounded-[30px]" : ""
        )}
      >
        <nav
          id="primary-navigation"
          aria-label="Dashboard pages"
          className="sidebar-scrollbar-hidden relative z-10 flex flex-1 flex-col justify-center gap-1.5 overflow-y-auto overflow-x-hidden"
        >
          {appNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              aria-label={item.label}
              onClick={(event) => {
                comingSoon.handleNavClick(event, item)
                if (!event.defaultPrevented) {
                  handleNavigation(item)
                }
              }}
              className={({ isActive }) =>
                cn(
                  "group relative flex h-11 shrink-0 items-center gap-3 overflow-hidden rounded-full pr-3 text-sm font-medium transition-[padding,color,transform] duration-[440ms] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 active:scale-[0.97] active:duration-100 motion-reduce:transition-none",
                  GLASS_EASE,
                  // 13px centers the 18px icon in the 44px collapsed rail; expanded it glides to 16px.
                  isVisuallyExpanded ? "pl-4" : "pl-[13px]",
                  isActive ? "text-sidebar-foreground" : "text-sidebar-foreground/70"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    <motion.span
                      layoutId="sidebar-active-indicator"
                      aria-hidden="true"
                      className="glass-pill pointer-events-none absolute inset-0"
                      style={{ borderRadius: 999 }}
                      transition={{ type: "spring", stiffness: 380, damping: 32, mass: 0.9 }}
                    />
                  ) : (
                    <span
                      aria-hidden="true"
                      className="glass-hover pointer-events-none absolute inset-0 rounded-full opacity-0 transition-opacity duration-200 group-hover:opacity-100 motion-reduce:transition-none"
                    />
                  )}
                  <item.icon
                    aria-hidden="true"
                    className={cn(
                      "relative size-[18px] shrink-0 transition-[color,transform,filter] duration-200 motion-reduce:transition-none",
                      isActive
                        ? "text-sidebar-foreground"
                        : "text-sidebar-foreground/70 group-hover:scale-[1.06] group-hover:text-sidebar-foreground group-hover:brightness-110 group-focus-visible:text-sidebar-foreground"
                    )}
                  />
                  <span
                    data-testid={`sidebar-label-${item.label}`}
                    aria-hidden={!isVisuallyExpanded}
                    className={cn(
                      "relative min-w-0 whitespace-nowrap transition-[opacity,transform] duration-[220ms] ease-out motion-reduce:transition-none",
                      isVisuallyExpanded
                        ? "translate-x-0 opacity-100 delay-[140ms]"
                        : "translate-x-2.5 opacity-0 delay-0 duration-150"
                    )}
                  >
                    {item.label}
                  </span>
                  {item.comingSoon ? (
                    <span
                      aria-hidden={!isVisuallyExpanded}
                      className={cn(
                        "relative ml-auto rounded-full border border-sidebar-foreground/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-sidebar-foreground/55 transition-opacity duration-[220ms] motion-reduce:transition-none",
                        isVisuallyExpanded ? "opacity-100 delay-[180ms]" : "opacity-0 delay-0"
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
            "relative z-10 mt-3 overflow-hidden whitespace-nowrap border-t border-sidebar-foreground/10 px-3.5 pt-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/40 transition-[max-height,opacity,padding] duration-[260ms] motion-reduce:transition-none",
            isVisuallyExpanded
              ? "max-h-8 opacity-100 delay-[140ms]"
              : "max-h-0 border-transparent pt-0 opacity-0"
          )}
        >
          Seller workspace
        </p>
      </aside>

      <ComingSoonModal open={comingSoon.open} onClose={comingSoon.onClose} />
    </MotionConfig>
  )
}
