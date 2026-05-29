import type { ChangeEvent } from "react"

import { Input } from "@/components/ui/input"

type AuthFieldProps = {
  id: string
  label: string
  type?: string
  name: string
  value: string
  placeholder?: string
  autoComplete?: string
  inputMode?: "text" | "email" | "numeric" | "tel"
  error?: string
  onChange: (event: ChangeEvent<HTMLInputElement>) => void
}

export function AuthField({
  id,
  label,
  type = "text",
  name,
  value,
  placeholder,
  autoComplete,
  inputMode,
  error,
  onChange,
}: AuthFieldProps) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground" htmlFor={id}>
        {label}
      </label>
      <Input
        id={id}
        name={name}
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        autoComplete={autoComplete}
        inputMode={inputMode}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
