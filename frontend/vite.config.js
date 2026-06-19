import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite' // <--- DODANY IMPORT

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(), // <--- DODANA WTYCZKA
  ],
})
