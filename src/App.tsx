import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { EmptyState } from './components/ui'
import { AuthProvider, useAuth } from './context/AuthContext'

const Homepage = lazy(() => import('./pages/Homepage').then((page) => ({ default: page.Homepage })))
const AuthPage = lazy(() => import('./pages/AuthPage').then((page) => ({ default: page.AuthPage })))

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((page) => ({ default: page.OverviewPage })))
const LiveSimulationPage = lazy(() => import('./pages/LiveSimulationPage').then((page) => ({ default: page.LiveSimulationPage })))
const InvestigationPage = lazy(() => import('./pages/InvestigationPage').then((page) => ({ default: page.InvestigationPage })))
const SustainabilityPage = lazy(() => import('./pages/SustainabilityPage').then((page) => ({ default: page.SustainabilityPage })))
const IncidentHistoryPage = lazy(() => import('./pages/IncidentHistoryPage').then((page) => ({ default: page.IncidentHistoryPage })))
const ModelEvaluationPage = lazy(() => import('./pages/ModelEvaluationPage').then((page) => ({ default: page.ModelEvaluationPage })))

export function SessionRoute({ children, publicOnly = false }: { children: ReactNode; publicOnly?: boolean }) {
  const { user, loading } = useAuth()
  if (loading) return <EmptyState title="Checking your sign-in" kind="loading" />
  if (publicOnly) return user ? <Navigate to="/" replace /> : children
  return user ? children : <Navigate to="/welcome" replace />
}

export default function App() {
  return <AuthProvider><BrowserRouter><Suspense fallback={<div className="page-content"><EmptyState title="Loading view" kind="loading" /></div>}><Routes>
    <Route path="welcome" element={<SessionRoute publicOnly><Homepage /></SessionRoute>} />
    <Route path="login" element={<SessionRoute publicOnly><AuthPage key="login" /></SessionRoute>} />
    <Route path="register" element={<SessionRoute publicOnly><AuthPage key="register" create /></SessionRoute>} />
    <Route element={<SessionRoute><AppShell /></SessionRoute>}>
    <Route index element={<OverviewPage />} />
    <Route path="simulation" element={<LiveSimulationPage />} />
    <Route path="investigation" element={<InvestigationPage />} />
    <Route path="sustainability" element={<SustainabilityPage />} />
    <Route path="incidents" element={<IncidentHistoryPage />} />
    <Route path="evaluation" element={<ModelEvaluationPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes></Suspense></BrowserRouter></AuthProvider>
}
