import { useCallback, useState } from "react"
import type { MouseEvent } from "react"

import type { NavItem } from "@/types/navigation"

type ComingSoonState = {
  open: boolean
  onClose: () => void
  onOpen: () => void
  handleNavClick: (event: MouseEvent, item: NavItem) => void
}

export function useComingSoon(): ComingSoonState {
  const [open, setOpen] = useState(false)

  const onOpen = useCallback(() => setOpen(true), [])
  const onClose = useCallback(() => setOpen(false), [])

  const handleNavClick = useCallback(
    (event: MouseEvent, item: NavItem) => {
      if (!item.comingSoon) {
        return
      }
      event.preventDefault()
      event.stopPropagation()
      onOpen()
    },
    [onOpen]
  )

  return { open, onClose, onOpen, handleNavClick }
}
