import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { FeedApp } from './FeedApp'
import './feed.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <FeedApp />
  </StrictMode>,
)
