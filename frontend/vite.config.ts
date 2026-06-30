import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
  resolve: {
    alias: [
      {
        find: /^es-toolkit\/compat\/(.+)$/,
        replacement: path.resolve(
          __dirname,
          "./src/vendor/es-toolkit-compat/$1"
        ),
      },
      { find: "@", replacement: path.resolve(__dirname, "./src") },
    ],
  },
})
