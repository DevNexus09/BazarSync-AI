import { useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import type { User } from "@/types/auth"

const requiredProfileFields: Array<keyof User> = [
  "fullName",
  "businessName",
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
        size="sm"
        className="gap-2"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
      >
        <span className="flex size-8 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground">
          {initials || "U"}
        </span>
        <span className="hidden text-sm font-medium text-foreground sm:inline">
          {displayName}
        </span>
      </Button>
      {isOpen ? (
        <div
          className="absolute right-0 mt-2 w-72 rounded-lg border bg-background p-4 shadow-lg"
          role="menu"
        >
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">{displayName}</p>
            <p className="text-xs text-muted-foreground">{user?.email}</p>
            <p className="text-xs text-muted-foreground">
              {missingCount === 0
                ? "Profile complete"
                : `Profile missing ${missingCount} fields`}
            </p>
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
