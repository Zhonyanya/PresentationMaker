import { StrictMode } from 'react'
import { z } from 'zod'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { ErrorBoundary } from './components/app/ErrorBoundary'

// Без проверки new Function: строгая CSP (без unsafe-eval) иначе пишет ошибку в консоль
z.config({ jitless: true })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
