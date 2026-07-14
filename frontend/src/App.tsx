import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "react-router-dom"

import { AuthProvider } from "@/context/auth-provider"
import { ThemeProvider } from "@/components/theme/theme-provider"
import { queryClient } from "@/lib/query-client"
import router from "@/routes"

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

export default App
