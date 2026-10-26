import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { EmptyState } from './components/ui'
import { ThemeProvider } from './context/ThemeContext'
import { AuthProvider, useAuth } from './context/AuthContext'
import { AuthPage } from './pages/AuthPage'

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((page) => ({ default: page.OverviewPage })))
const LiveSimulationPage = lazy(() => import('./pages/LiveSimulationPage').then((page) => ({ default: page.LiveSimulationPage })))
const InvestigationPage = lazy(() => import('./pages/InvestigationPage').then((page) => ({ default: page.InvestigationPage })))
const IncidentHistoryPage = lazy(() => import('./pages/IncidentHistoryPage').then((page) => ({ default: page.IncidentHistoryPage })))
const ModelEvaluationPage = lazy(() => import('./pages/ModelEvaluationPage').then((page) => ({ default: page.ModelEvaluationPage })))
const Homepage = lazy(() => import('./pages/Homepage').then((page) => ({ default: page.Homepage })))

export default function App() {
  return <ThemeProvider><AuthProvider><BrowserRouter><Suspense fallback={<div className="page-content"><EmptyState title="Loading view" kind="loading" /></div>}><Routes>
    <Route path="welcome" element={<PublicOnly><Homepage /></PublicOnly>} />
    <Route path="login" element={<AuthPage />} />
    <Route path="register" element={<AuthPage create />} />
    <Route element={<RequireAuth><AppShell /></RequireAuth>}>
    <Route index element={<OverviewPage />} />
    <Route path="simulation" element={<LiveSimulationPage />} />
    <Route path="investigation" element={<InvestigationPage />} />
    <Route path="incidents" element={<IncidentHistoryPage />} />
    <Route path="evaluation" element={<ModelEvaluationPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes></Suspense></BrowserRouter></AuthProvider></ThemeProvider>
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="page-content"><EmptyState title="Checking your sign-in" kind="loading" /></div>
  return user ? children : <Navigate to="/login" replace />
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="page-content"><EmptyState title="Checking your sign-in" kind="loading" /></div>
  return user ? <Navigate to="/" replace /> : children
}
