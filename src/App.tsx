import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { EmptyState } from './components/ui'
import { ThemeProvider } from './context/ThemeContext'

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((page) => ({ default: page.OverviewPage })))
const LiveSimulationPage = lazy(() => import('./pages/LiveSimulationPage').then((page) => ({ default: page.LiveSimulationPage })))
const InvestigationPage = lazy(() => import('./pages/InvestigationPage').then((page) => ({ default: page.InvestigationPage })))
const SustainabilityPage = lazy(() => import('./pages/SustainabilityPage').then((page) => ({ default: page.SustainabilityPage })))
const IncidentHistoryPage = lazy(() => import('./pages/IncidentHistoryPage').then((page) => ({ default: page.IncidentHistoryPage })))
const ModelEvaluationPage = lazy(() => import('./pages/ModelEvaluationPage').then((page) => ({ default: page.ModelEvaluationPage })))
const Homepage = lazy(() => import('./pages/Homepage').then((page) => ({ default: page.Homepage })))

export default function App() {
  return <ThemeProvider><BrowserRouter><Suspense fallback={<div className="page-content"><EmptyState title="Loading view" kind="loading" /></div>}><Routes>
    <Route path="welcome" element={<Homepage />} />
    <Route element={<AppShell />}>
    <Route index element={<OverviewPage />} />
    <Route path="simulation" element={<LiveSimulationPage />} />
    <Route path="investigation" element={<InvestigationPage />} />
    <Route path="sustainability" element={<SustainabilityPage />} />
    <Route path="incidents" element={<IncidentHistoryPage />} />
    <Route path="evaluation" element={<ModelEvaluationPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes></Suspense></BrowserRouter></ThemeProvider>
}
