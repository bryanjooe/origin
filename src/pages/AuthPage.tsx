import { useState, type FormEvent } from 'react'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './auth.css'

export function AuthPage({ create = false }: { create?: boolean }) {
  const { user, login, createAccount } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (create) await createAccount(name, email, password)
      else await login(email, password)
      navigate('/', { replace: true })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not complete this request.')
    } finally { setBusy(false) }
  }

  return <main className="auth-page">
    <section className="auth-panel" aria-labelledby="auth-title">
      <Link className="auth-brand" to="/welcome" aria-label="TraceX GreenGrid homepage"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><span>Origin<small>GREEN GRID</small></span></Link>
      <p className="eyebrow">SIMULATION WORKSPACE</p>
      <h1 id="auth-title">{create ? 'Create your account' : 'Welcome back'}</h1>
      <p className="auth-intro">{create ? 'Set up a local demo account to enter the Origin workspace.' : 'Sign in to continue to the Origin microgrid workspace.'}</p>
      <form onSubmit={(event) => void submit(event)}>
        {create && <label className="field-label">NAME<input autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} required /></label>}
        <label className="field-label">EMAIL<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label className="field-label">PASSWORD<input type="password" autoComplete={create ? 'new-password' : 'current-password'} minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="button button-primary auth-submit" type="submit" disabled={busy}>{busy ? 'Please wait…' : create ? 'Create account' : 'Sign in'} <ArrowRight size={15} aria-hidden="true" /></button>
      </form>
      <p className="auth-switch">{create ? 'Already have a local account?' : 'New to this browser?'} <Link to={create ? '/login' : '/register'}>{create ? 'Sign in' : 'Create account'}</Link></p>
      <p className="auth-note"><ShieldCheck size={14} aria-hidden="true" /> Accounts are saved by the Origin backend. You can sign in from any browser connected to this server.</p>
      <Link className="auth-home-link" to="/welcome">Back to project homepage</Link>
    </section>
  </main>
}
