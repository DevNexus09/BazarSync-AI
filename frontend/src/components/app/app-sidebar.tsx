import { useEffect, useRef } from "react"
import type { RefObject } from "react"
import { NavLink, useLocation } from "react-router-dom"
import { Menu, X } from "lucide-react"

import { ComingSoonModal } from "@/components/common/coming-soon-modal"
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

  useEffect(() => {
    const pathChanged = previousPathRef.current !== location.pathname
    previousPathRef.current = location.pathname

    if (pathChanged && isExpanded && !isDesktopViewport()) {
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
          className="fixed inset-0 z-[55] bg-slate-950/65 backdrop-blur-[2px] transition-opacity duration-300 motion-reduce:transition-none lg:bg-transparent lg:backdrop-blur-none"
          onClick={onClose}
        />
      ) : null}

      <aside
        data-testid="app-sidebar"
        aria-label="Primary navigation"
        className={cn(
          "fixed inset-y-0 left-0 z-[60] flex w-[min(88vw,300px)] -translate-x-full flex-col overflow-hidden border-r border-white/10 bg-[rgba(8,10,15,0.84)] shadow-[18px_0_60px_rgba(0,0,0,0.32)] backdrop-blur-xl transition-[width,transform,background-color,box-shadow] duration-300 ease-out motion-reduce:transition-none lg:translate-x-0 lg:w-[72px]",
          isExpanded
            ? "translate-x-0 lg:w-[272px] lg:bg-[rgba(8,10,15,0.9)] lg:shadow-[18px_0_80px_rgba(0,0,0,0.42)]"
            : ""
        )}
      >
        <div className="flex h-20 shrink-0 items-center border-b border-white/10 px-3">
          <button
            ref={desktopToggleRef}
            type="button"
            aria-label={isExpanded ? "Collapse navigation" : "Expand navigation"}
            aria-expanded={isExpanded}
            aria-controls="primary-navigation"
            title={isExpanded ? "Collapse navigation" : "Expand navigation"}
            className={cn(
              "group flex min-w-0 items-center rounded-xl border border-transparent p-2.5 text-left transition-colors duration-200 hover:border-white/10 hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70",
              isExpanded ? "w-full gap-3" : "w-full justify-center"
            )}
            onClick={onToggle}
          >
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/15 font-heading text-lg font-bold text-primary shadow-[0_0_24px_rgba(59,130,246,0.16)]"
            >
              B
            </span>
            <span
              className={cn(
                "min-w-0 overflow-hidden whitespace-nowrap font-heading text-sm font-semibold tracking-wide text-foreground transition-[max-width,opacity,transform] duration-200 motion-reduce:transition-none",
                isExpanded
                  ? "max-w-[160px] translate-x-0 opacity-100"
                  : "max-w-0 -translate-x-2 opacity-0"
              )}
            >
              BazarSync AI
            </span>
            <span
              aria-hidden="true"
              className={cn(
                "ml-auto text-muted-foreground transition-opacity duration-200 motion-reduce:transition-none",
                isExpanded ? "opacity-100" : "hidden"
              )}
            >
              {isExpanded ? <X className="size-4" /> : <Menu className="size-4" />}
            </span>
          </button>
        </div>

        <nav
          id="primary-navigation"
          aria-label="Dashboard pages"
          className="flex flex-1 flex-col gap-2 overflow-y-auto px-3 py-5 [scrollbar-color:rgba(148,163,184,0.35)_transparent] [scrollbar-width:thin]"
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
                  "group/item relative flex h-12 shrink-0 items-center gap-3 rounded-xl border border-transparent px-3 text-sm font-medium text-slate-400 transition-[background-color,border-color,color,box-shadow] duration-200 hover:border-white/10 hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 motion-reduce:transition-none",
                  isExpanded ? "justify-start" : "justify-center",
                  isActive
                    ? "border-primary/20 bg-primary/10 text-white shadow-[inset_3px_0_0_rgb(59,130,246)]"
                    : ""
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon
                    aria-hidden="true"
                    className={cn(
                      "size-[21px] shrink-0 transition-colors duration-200 motion-reduce:transition-none",
                      isActive ? "text-primary" : "text-slate-400 group-hover/item:text-white"
                    )}
                  />
                  <span
                    data-testid={`sidebar-label-${item.label}`}
                    className={cn(
                      "min-w-0 overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-200 motion-reduce:transition-none",
                      isExpanded
                        ? "max-w-[190px] translate-x-0 opacity-100"
                        : "max-w-0 -translate-x-2 opacity-0"
                    )}
                  >
                    {item.label}
                  </span>
                  {item.comingSoon && isExpanded ? (
                    <span className="ml-auto rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                      Soon
                    </span>
                  ) : null}
                  {!isExpanded ? (
                    <span
                      aria-hidden="true"
                      role="tooltip"
                      className="pointer-events-none absolute left-[calc(100%+0.75rem)] z-[70] hidden whitespace-nowrap rounded-lg border border-white/10 bg-slate-950/95 px-3 py-2 text-xs font-medium text-white opacity-0 shadow-xl transition-opacity duration-150 group-hover/item:block group-hover/item:opacity-100 group-focus-visible/item:block group-focus-visible/item:opacity-100 lg:block"
                    >
                      {item.label}
                    </span>
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="shrink-0 border-t border-white/10 px-4 py-4">
          <p
            className={cn(
              "overflow-hidden whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-600 transition-[max-width,opacity] duration-200 motion-reduce:transition-none",
              isExpanded ? "max-w-[190px] opacity-100" : "max-w-0 opacity-0"
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
