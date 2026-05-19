type AuthFormAlertProps = {
  message?: string | null
}

export function AuthFormAlert({ message }: AuthFormAlertProps) {
  if (!message) {
    return null
  }

  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {message}
    </div>
  )
}
