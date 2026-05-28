import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
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