import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { simulationClock } from './status'
import { Badge } from '../components/ui'

it.each([[0, '00:00'], [60, '00:01'], [3660, '01:01'], [90000, '25:00']])('formats %s elapsed seconds as hours:minutes', (seconds, clock) => {
  expect(simulationClock(undefined, seconds as number)).toBe(clock)
})

it('does not fabricate a clock for unavailable time', () => {
  expect(simulationClock()).toBe('—')
  expect(simulationClock(undefined, Number.NaN)).toBe('—')
})

it.each([['running', 'play'], ['paused', 'pause'], ['stopped', 'square']])('uses the %s state icon', (status, icon) => {
  render(<Badge severity="unknown" status={status}>{status}</Badge>)
  expect(screen.getByText(status).querySelector(`.lucide-${icon}`)).toBeTruthy()
  expect(screen.getByText(status).querySelector('.lucide-circle-help')).toBeNull()
})
