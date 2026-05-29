import { Loader2, Send } from "lucide-react"

import { Button } from "@/components/ui/button"

type SendSnapshotButtonProps = {
  onClick: () => void
  disabled?: boolean
  isLoading?: boolean
}

export function SendSnapshotButton({
  onClick,
  disabled = false,
  isLoading = false,
}: SendSnapshotButtonProps) {
  return (
    <Button
      type="button"
      className="w-full"
      onClick={onClick}
      disabled={disabled || isLoading}
    >
      {isLoading ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
<<<<<<< HEAD
      {isLoading ? "Sending..." : "Send Telegram Alert"}
=======
      {isLoading ? "Sending..." : "Send Snapshot"}
>>>>>>> develop
    </Button>
  )
}
