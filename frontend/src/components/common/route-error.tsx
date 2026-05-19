import { useNavigate, useRouteError, isRouteErrorResponse } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"

export default function RouteError() {
  const error = useRouteError()
  const navigate = useNavigate()

  let title = "Unexpected error"
  let message = "Something went wrong while loading this page."

  if (isRouteErrorResponse(error)) {
    title = `${error.status} ${error.statusText}`
    const payload =
      typeof error.data === "string"
        ? { message: error.data }
        : (error.data as { message?: string } | undefined)
    message = payload?.message ?? message
  } else if (error instanceof Error) {
    message = error.message
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <ErrorState
        title={title}
        message={message}
        action={
          <Button variant="outline" onClick={() => navigate(-1)}>
            Go back
          </Button>
        }
      />
    </div>
  )
}
