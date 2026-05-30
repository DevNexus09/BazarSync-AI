import { NavLink } from "react-router-dom"

import { ComingSoonModal } from "@/components/common/coming-soon-modal"
import { useComingSoon } from "@/hooks/useComingSoon"
import { appNavItems } from "@/routes/nav-config"
import { cn } from "@/lib/utils"

export default function AppSidebar() {
  const comingSoon = useComingSoon()

  return (
    <>
      <aside className="peer group relative hidden overflow-hidden border-r border-border/40 bg-sidebar/30 backdrop-blur-2xl lg:fixed lg:inset-y-0 lg:z-40 lg:flex lg:w-20 lg:flex-col lg:transition-[width,background-color,box-shadow] lg:duration-700 lg:ease-out lg:hover:w-64 lg:hover:bg-white/8 lg:hover:shadow-[0_0_80px_rgba(15,23,42,0.6)] before:absolute before:inset-0 before:bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.16),_transparent_55%)] before:opacity-0 before:transition-opacity before:duration-700 before:content-[''] lg:hover:before:opacity-100">
        <nav className="relative flex flex-1 flex-col items-center justify-center gap-2 px-2 py-4">
          {appNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              title={item.label}
              onClick={(event) => comingSoon.handleNavClick(event, item)}
              className={({ isActive }) =>
                cn(
                  "group/item flex w-full items-center justify-center gap-3 rounded-2xl border border-transparent px-3 py-3 text-sm font-medium text-muted-foreground transition-all duration-300",
                  "hover:border-white/10 hover:bg-white/10 hover:backdrop-blur-xl hover:text-foreground lg:group-hover:justify-start",
                  isActive
                    ? "group-hover:border-white/20 group-hover:bg-white/15 group-hover:text-foreground group-hover:shadow-[0_0_24px_rgba(255,255,255,0.35)]"
                    : ""
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon
                    className={cn(
                      "size-5 transition-colors duration-300",
                      isActive ? "text-sky-400" : "text-sky-400",
                      "group-hover/item:text-white"
                    )}
                  />
                  <span className="min-w-0 flex-1 translate-x-1 opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100">
                    {item.label}
                  </span>
                  {item.comingSoon ? (
                    <span className="hidden rounded-full border border-border/60 px-2 py-0.5 text-[10px] uppercase text-muted-foreground group-hover:inline-flex">
                      Soon
                    </span>
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>
      <ComingSoonModal open={comingSoon.open} onClose={comingSoon.onClose} />
    </>
  )
}
