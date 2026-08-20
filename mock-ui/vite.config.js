import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-only test bed for leap-input's grab mode. React Grab needs the source
// locations the React plugin emits, so keep the default dev sourcemaps.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, open: false },
})
