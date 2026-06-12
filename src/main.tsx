import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { resolveAdapter } from './data'
import { App } from './ui/App'
import './styles.css'

const root = createRoot(document.getElementById('root')!)
root.render(<div className="boot">Connecting to market data…</div>)

resolveAdapter().then((adapter) => {
  root.render(
    <StrictMode>
      <App adapter={adapter} />
    </StrictMode>,
  )
})
