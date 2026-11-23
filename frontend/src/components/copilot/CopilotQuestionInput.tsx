import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import type { KeyboardEvent } from "react"
import { ArrowUp } from "lucide-react"

import { cn } from "@/lib/utils"

const MAX_QUESTION_LENGTH = 2000
const COUNTER_THRESHOLD = 1600
const MAX_TEXTAREA_HEIGHT_PX = 160

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
      className="bg-card px-3 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <div className="copilot-column">
        <div
          className={cn(
            "flex items-end gap-2 rounded-2xl border border-border/70 bg-background p-1.5 pl-3.5 shadow-sm transition",
            "focus-within:border-primary/50 focus-within:shadow-md focus-within:ring-4 focus-within:ring-primary/10",
            disabled && "opacity-70"
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            rows={1}
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
            className="max-h-40 min-h-9 flex-1 resize-none bg-transparent py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/80 disabled:cursor-not-allowed"
          />
          <button
            type="submit"
            aria-label="Send question"
            disabled={disabled || !value.trim()}
            className={cn(
              "grid size-9 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm transition",
              "hover:bg-primary/90 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              "disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none"
            )}
          >
            <ArrowUp className="size-4" strokeWidth={2.5} aria-hidden="true" />
          </button>
        </div>
        <div className="mt-1.5 flex items-start justify-between gap-2 px-1">
          <p id="copilot-input-hint" className="text-[11px] text-muted-foreground/80">
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
