import { useAuth } from './auth'
import { Layout } from './components/Layout'
import { Empty } from './components/ui'
import { match, useLocation } from './lib/router'
import { AccountPage } from './pages/AccountPage'
import { ChartPage } from './pages/ChartPage'
import { InstrumentPage, InstrumentsPage } from './pages/InstrumentsPage'
import { Login } from './pages/Login'
import { Overview } from './pages/Overview'
import { RunPage, SystemPage } from './pages/SystemPage'
import { SignalsPage, TradesPage } from './pages/TradesPage'

function Routes() {
  const { path } = useLocation()
  let params: Record<string, string> | null
  if (path === '/' || path === '') return <Overview />
  if ((params = match('/accounts/:id', path))) return <AccountPage key={params.id} id={params.id} />
  if (path === '/instruments') return <InstrumentsPage />
  if ((params = match('/instruments/:symbol', path))) return <InstrumentPage key={params.symbol} symbol={params.symbol} />
  if (path === '/chart') return <ChartPage />
  if (path === '/trades') return <TradesPage />
  if (path === '/signals') return <SignalsPage />
  if (path === '/system') return <SystemPage />
  if ((params = match('/runs/:id', path))) return <RunPage key={params.id} id={params.id} />
  return (
    <div className="page">
      <Empty title="Page not found" />
    </div>
  )
}

export function App() {
  const { session, checking } = useAuth()
  if (checking) return <div className="boot">K·Terminal</div>
  if (!session) return <Login />
  return (
    <Layout>
      <Routes />
    </Layout>
  )
}
