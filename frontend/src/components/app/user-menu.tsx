import { useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import type { User } from "@/types/auth"

const requiredProfileFields: Array<Exclude<keyof User, "isDemo">> = [
  "fullName",
  "businessName",
  "profileImageUrl",
  "industry",
  "website",
  "addressLine",
  "city",
  "country",
  "phone",
] as const

export default function UserMenu() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  const displayName = user?.fullName || user?.businessName || user?.email || "Account"
  const profileImageUrl = user?.profileImageUrl?.trim()
  const initials = displayName
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((chunk) => chunk[0]?.toUpperCase())
    .join("")

  const missingCount = requiredProfileFields.filter((field) => {
    const value = user?.[field]
    if (!value) {
      return true
    }
    return value.trim().length === 0
  }).length

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!menuRef.current) {
        return
      }
      if (!menuRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false)
      }
    }

    document.addEventListener("pointerdown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [])

  const handleLogout = () => {
    setIsOpen(false)
    logout()
    navigate("/login")
  }

  return (
    <div className="relative" ref={menuRef}>
      <Button
        variant="ghost"
        size="icon"
        className="size-11 rounded-full border border-border/60 bg-card/40 p-1 hover:bg-card/70"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label="Open account menu"
        onClick={() => setIsOpen((open) => !open)}
      >
        {profileImageUrl ? (
          <img
            src={profileImageUrl}
            alt=""
            className="size-9 rounded-full object-cover"
          />
        ) : (
          <span className="flex size-9 items-center justify-center rounded-full bg-muted/60 text-xs font-semibold text-foreground">
            {initials || "U"}
          </span>
        )}
      </Button>
      {isOpen ? (
        <div
          className="absolute right-0 mt-3 w-72 rounded-2xl border border-border/70 bg-card/80 p-4 shadow-[0_0_0_1px_rgb(var(--primary)/.12),_0_24px_60px_rgb(var(--overlay)/.6)] backdrop-blur"
          role="menu"
        >
          <div className="flex items-center gap-3">
            {profileImageUrl ? (
              <img
                src={profileImageUrl}
                alt=""
                className="size-11 rounded-full object-cover"
              />
            ) : (
              <span className="flex size-11 items-center justify-center rounded-full bg-muted/60 text-sm font-semibold text-foreground">
                {initials || "U"}
              </span>
            )}
            <div className="min-w-0 space-y-1">
              <p className="truncate text-sm font-semibold text-foreground">
                {displayName}
              </p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
              <p className="text-xs text-muted-foreground">
                {missingCount === 0
                  ? "Profile complete"
                  : `Profile missing ${missingCount} fields`}
              </p>
            </div>
          </div>
          <div className="mt-4 space-y-2 border-t pt-3">
            <Button asChild variant="outline" size="sm" className="w-full">
              <Link to="/app/profile" onClick={() => setIsOpen(false)}>
                Complete profile
              </Link>
            </Button>
            <Button variant="ghost" size="sm" className="w-full" onClick={handleLogout}>
              Log out
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
