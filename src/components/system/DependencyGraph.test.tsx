import { render } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { Core } from 'cytoscape'
import { DependencyGraph, graphElements } from './DependencyGraph'
import type { TopologyNode } from '../../types/domain'

const state = vi.hoisted(() => ({ cores: [] as Core[] }))
vi.mock('cytoscape', async (original) => {
  const actual = await original<{ default: typeof import('cytoscape') }>()
  return { default: (options: Record<string, unknown>) => {
    const cy = actual.default({ ...options, container: undefined, headless: true, styleEnabled: true })
    state.cores.push(cy)
    return cy
  } }
})
beforeEach(() => { state.cores = [] })
const nodes: TopologyNode[] = [{ id: 'communication', observed_symptom: true, security_candidate: true }, { id: 'controller', potentially_affected: true }]
const edges = [{ source: 'communication', target: 'controller', suspected: true, security_suspected: true }]

it('retains all topology elements and distinct observed/candidate/possible classes', () => {
  const elements = graphElements(nodes, edges)
  expect(elements).toHaveLength(3)
  expect(elements[0]!.classes).toContain('observed')
  expect(elements[0]!.classes).toContain('security-origin')
  expect(elements[1]!.classes).toContain('possible')
  expect(elements[1]!.classes).not.toContain('observed')
  expect(elements[2]!.classes).toContain('security-path')
})
it('keeps unknown nodes and structural edges neutral without invented hypotheses', () => {
  const elements = graphElements([{ id: 'a' }, { id: 'b' }], [{ source: 'a', target: 'b' }])
  expect(elements[0]!.classes).toBe('')
  expect(elements[2]!.classes).toContain('known')
  expect(elements[2]!.classes).not.toContain('suspected')
})
it('uses stable edge IDs when payload ordering changes', () => {
  const a = graphElements(nodes, edges)
  const b = graphElements([...nodes].reverse(), [...edges].reverse())
  expect(a[2]!.data.id).toBe(b[2]!.data.id)
})
it('updates Cytoscape data without recreating the graph or losing node positions/zoom', () => {
  const view = render(<DependencyGraph nodes={nodes} edges={edges} />)
  const cy = state.cores[0]!
  cy.getElementById('controller').position({ x: 123, y: 456 }); cy.zoom(1.2)
  view.rerender(<DependencyGraph nodes={nodes.map((node) => ({ ...node, telemetry: { tick: 9 } }))} edges={[...edges]} />)
  expect(state.cores).toHaveLength(1)
  expect(cy.getElementById('controller').position()).toEqual({ x: 123, y: 456 })
  expect(cy.zoom()).toBe(1.2)
})
it('selects nodes, supports event groups, and clears selections', () => {
  const view = render(<DependencyGraph nodes={nodes} edges={edges} selectedNode="communication" highlightedNodes={['communication', 'controller']} />)
  const cy = state.cores[0]!
  expect(cy.getElementById('communication').selected()).toBe(true)
  expect(cy.nodes('.timeline-focus').length).toBe(2)
  view.rerender(<DependencyGraph nodes={nodes} edges={edges} />)
  expect(cy.nodes(':selected').length).toBe(0)
  expect(cy.nodes('.timeline-focus').length).toBe(0)
})
it('uses current node evidence when a graph tap occurs after data updates', () => {
  const select = vi.fn()
  const view = render(<DependencyGraph nodes={nodes} edges={edges} onNodeSelect={select} />)
  const updated = nodes.map((node) => ({ ...node, telemetry: { tick: 10 } }))
  view.rerender(<DependencyGraph nodes={updated} edges={edges} onNodeSelect={select} />)
  state.cores[0]!.getElementById('controller').emit('tap')
  expect(select).toHaveBeenCalledWith(updated[1])
})
it('cleans up graph listeners and destroys the core on unmount', () => {
  const view = render(<DependencyGraph nodes={nodes} edges={edges} />)
  const cy = state.cores[0]!, off = vi.spyOn(cy, 'off')
  view.unmount()
  expect(off).toHaveBeenCalledWith('tap', 'node', expect.any(Function))
  expect(cy.destroyed()).toBe(true)
})
