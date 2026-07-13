import { forwardRef, useState } from "react"
import { Send } from "lucide-react"

import { Button } from "@/components/ui/button"

export const CopilotQuestionInput = forwardRef<
  HTMLTextAreaElement,
  {
    disabled?: boolean
    onSubmit: (question: string) => void
    onEscape: () => void
  }
>(({ disabled, onSubmit, onEscape }, ref) => {
  const [value, setValue] = useState("")
  const [isComposing, setIsComposing] = useState(false)

  const submit = () => {
    const question = value.trim()
    if (!question || disabled) {
      return
    }
    setValue("")
    onSubmit(question)
  }

  return (
    <form
      className="border-t border-border/60 bg-card p-3"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          value={value}
          rows={2}
          maxLength={2000}
          disabled={disabled}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !isComposing) {
              event.preventDefault()
              onEscape()
            }
            if (event.key === "Enter" && !event.shiftKey && !isComposing) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder="Ask about restock, pricing, competitors..."
          aria-label="Ask Copilot a business question"
          className="max-h-28 min-h-11 flex-1 resize-none rounded-xl border border-border/70 bg-background px-3 py-2 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/25 disabled:opacity-60"
        />
        <Button
          type="submit"
          size="icon-lg"
          aria-label="Send question"
          disabled={disabled || !value.trim()}
        >
          <Send className="size-4" />
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Shift+Enter adds a new line. Marketplace changes are not executed
        automatically.
      </p>
    </form>
  )
})

CopilotQuestionInput.displayName = "CopilotQuestionInput"
