import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from '../context/AuthContext'
import { SessionRoute } from '../App'
import { api } from '../services/api'
import { AuthPage } from './AuthPage'
import { Homepage } from './Homepage'

const user = { id: 'test-user', name: 'Demo User', email: 'demo@example.test' }

beforeEach(() => {
  vi.spyOn(api, 'getCurrentUser').mockResolvedValue(null)
  vi.spyOn(api, 'login').mockResolvedValue(user)
  vi.spyOn(api, 'createAccount').mockResolvedValue(user)
  vi.spyOn(api, 'logout').mockResolvedValue(undefined)
})

function mount(create = false) {
  return render(<AuthProvider><MemoryRouter initialEntries={[create ? '/register' : '/login']}><Routes>
    <Route path="/login" element={<SessionRoute publicOnly><AuthPage /></SessionRoute>} />
    <Route path="/register" element={<SessionRoute publicOnly><AuthPage create /></SessionRoute>} />
    <Route path="/" element={<SessionRoute><div>Existing workspace</div></SessionRoute>} />
    <Route path="/welcome" element={<div>Welcome page</div>} />
  </Routes></MemoryRouter></AuthProvider>)
}

async function fill(create = false) {
  await screen.findByLabelText('EMAIL')
  if (create) fireEvent.change(screen.getByLabelText('NAME'), { target: { value: user.name } })
  fireEvent.change(screen.getByLabelText('EMAIL'), { target: { value: user.email } })
  fireEvent.change(screen.getByLabelText('PASSWORD'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByRole('button', { name: create ? 'Create account' : 'Sign in' }))
}

it('registers with the backend and enters the existing workspace', async () => {
  mount(true); await fill(true)
  expect(await screen.findByText('Existing workspace')).toBeTruthy()
  expect(api.createAccount).toHaveBeenCalledWith(user.name, user.email, 'password123')
})

it('signs in with the backend and enters the existing workspace', async () => {
  mount(); await fill()
  expect(await screen.findByText('Existing workspace')).toBeTruthy()
  expect(api.login).toHaveBeenCalledWith(user.email, 'password123')
})

it('keeps server errors visible without entering the workspace', async () => {
  vi.mocked(api.login).mockRejectedValue(new Error('Email or password is incorrect'))
  mount(); await fill()
  expect((await screen.findByRole('alert')).textContent).toBe('Email or password is incorrect')
  expect(screen.queryByText('Existing workspace')).toBeNull()
  expect((screen.getByRole('button', { name: 'Sign in' }) as HTMLButtonElement).disabled).toBe(false)
})

it('restores the server session before showing account forms', async () => {
  vi.mocked(api.getCurrentUser).mockResolvedValue(user)
  mount()
  expect(await screen.findByText('Existing workspace')).toBeTruthy()
  expect(screen.queryByLabelText('PASSWORD')).toBeNull()
})

it('routes anonymous workspace visits to the welcome page', async () => {
  render(<AuthProvider><MemoryRouter><Routes>
    <Route path="/" element={<SessionRoute><div>Existing workspace</div></SessionRoute>} />
    <Route path="/welcome" element={<div>Welcome page</div>} />
  </Routes></MemoryRouter></AuthProvider>)
  expect(await screen.findByText('Welcome page')).toBeTruthy()
})

it('does not clear the session when server sign-out fails', async () => {
  vi.mocked(api.getCurrentUser).mockResolvedValue(user)
  vi.mocked(api.logout).mockRejectedValue(new Error('Offline'))
  function Account() {
    const auth = useAuth()
    return <><span>{auth.user?.name}</span><button onClick={() => void auth.logout().catch(() => undefined)}>Sign out</button></>
  }
  render(<AuthProvider><Account /></AuthProvider>)
  await screen.findByText(user.name)
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(api.logout).toHaveBeenCalled())
  expect(screen.getByText(user.name)).toBeTruthy()
})

it('preserves the welcome screen account links and restores body styles on exit', () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
  const oldWidth = document.body.style.minWidth
  const view = render(<MemoryRouter><Homepage /></MemoryRouter>)
  expect(screen.getAllByRole('link', { name: /^Sign in$/ }).every((link) => link.getAttribute('href') === '/login')).toBe(true)
  expect(screen.getAllByRole('link', { name: /Create account/ }).every((link) => link.getAttribute('href') === '/register')).toBe(true)
  expect(screen.getByRole('img', { name: /component and dependency illustration/ })).toBeTruthy()
  view.unmount()
  expect(document.body.style.minWidth).toBe(oldWidth)
})
