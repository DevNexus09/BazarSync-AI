import { useEffect } from "react"
import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  TelegramInstructions,
  type TelegramInstructionsProps,
} from "@/components/telegram/telegram-instructions"

type TelegramInstructionsModalProps = TelegramInstructionsProps & {
  open: boolean
  onClose: () => void
}

export function TelegramInstructionsModal({
  open,
  onClose,
  ...instructionsProps
}: TelegramInstructionsModalProps) {
  useEffect(() => {
    if (!open) {
      return
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [onClose, open])

  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Bot connection instructions"
        className="relative w-full max-w-xl"
      >
        <Button
          variant="ghost"
          size="icon-sm"
          className="absolute right-3 top-3 z-10"
          onClick={onClose}
          aria-label="Close instructions"
        >
          <X className="size-4" />
        </Button>
        <TelegramInstructions {...instructionsProps} />
      </div>
    </div>
  )
}
