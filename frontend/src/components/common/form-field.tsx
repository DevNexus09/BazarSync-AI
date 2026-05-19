import type { ChangeEvent } from "react"

import { Input } from "@/components/ui/input"

type FormFieldProps = {
  id: string
  name: string
  label: string
  type?: string
  value: string
  placeholder?: string
  inputMode?: "text" | "email" | "numeric" | "decimal" | "tel"
  min?: number
  step?: number
  error?: string
  helperText?: string
  onChange: (event: ChangeEvent<HTMLInputElement>) => void
}

export function FormField({
  id,
  name,
  label,
  type = "text",
  value,
  placeholder,
  inputMode,
  min,
  step,
  error,
  helperText,
  onChange,
}: FormFieldProps) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-foreground" htmlFor={id}>
        {label}
      </label>
      <Input
        id={id}
        name={name}
        type={type}
        value={value}
        placeholder={placeholder}
        inputMode={inputMode}
        min={min}
        step={step}
        onChange={onChange}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      {helperText ? (
        <p className="text-xs text-muted-foreground">{helperText}</p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
