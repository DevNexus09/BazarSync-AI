import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import type { KeyboardEvent } from "react"
import { Send } from "lucide-react"

import { Button } from "@/components/ui/button"

const MAX_QUESTION_LENGTH = 2000
const COUNTER_THRESHOLD = 1600
const MAX_TEXTAREA_HEIGHT_PX = 112

export const CopilotQuestionInput = forwardRef<
  HTMLTextAreaElement,
  {
    disabled?: boolean
    onSubmit: (question: string) => void
    onEscape: () => void
    placeholder?: string
    hint?: string
    /** Puts text back in the box (for example a question that failed to send). */
    restore?: { text: string; nonce: number } | null
  }
>(({ disabled, onSubmit, onEscape, placeholder, hint, restore }, ref) => {
  const [value, setValue] = useState("")
  const [isComposing, setIsComposing] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(ref, () => textareaRef.current as HTMLTextAreaElement)

  useEffect(() => {
    if (!restore) {
      return
    }
    setValue(restore.text)
    if (restore.text) {
      textareaRef.current?.focus()
    }
  }, [restore])

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) {
      return
    }
    textarea.style.height = "auto"
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`
  }, [value])

  const submit = () => {
    const question = value.trim()
    if (!question || disabled) {
      return
    }
    setValue("")
    onSubmit(question)
  }

  // Safari can fire compositionend before the Enter keydown that commits a Bangla
  // (or any IME) word, so React state alone is not enough to tell them apart.
  const composing = (event: KeyboardEvent<HTMLTextAreaElement>) =>
    isComposing || event.nativeEvent.isComposing || event.keyCode === 229

  return (
    <form
      className="border-t border-border/60 bg-card p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <div className="copilot-column">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={value}
          rows={2}
          maxLength={MAX_QUESTION_LENGTH}
          disabled={disabled}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (composing(event)) {
              return
            }
            if (event.key === "Escape") {
              event.preventDefault()
              event.stopPropagation()
              onEscape()
            }
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={placeholder ?? "Ask about restock, pricing, competitors..."}
          aria-label="Ask Copilot a business question"
          aria-describedby="copilot-input-hint"
          className="max-h-28 min-h-11 flex-1 resize-none rounded-xl border border-border/70 bg-background px-3 py-2 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/25 disabled:opacity-60"
        />
        <Button type="submit" size="icon-lg" aria-label="Send question" disabled={disabled || !value.trim()}>
          <Send className="size-4" />
        </Button>
      </div>
      <div className="mt-2 flex items-start justify-between gap-2">
        <p id="copilot-input-hint" className="text-[11px] text-muted-foreground">
          {hint ?? "Shift+Enter adds a new line. Marketplace changes are not executed automatically."}
        </p>
        {value.length >= COUNTER_THRESHOLD ? (
          <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground" aria-live="polite">
            {value.length}/{MAX_QUESTION_LENGTH}
          </span>
        ) : null}
      </div>
      </div>
    </form>
  )
})

CopilotQuestionInput.displayName = "CopilotQuestionInput"
