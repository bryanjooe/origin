import { useEffect, useRef, useState } from 'react'
import cytoscape, { type Core } from 'cytoscape'
import { Expand, Network, X } from 'lucide-react'
import type { Evidence, GraphData, GraphEdge, GraphNode } from '../types'
import { human, number } from '../utils/format'

const positions: Record<string, { x: number; y: number }> = {
  irradiance: { x: 70, y: 50 }, solar: { x: 70, y: 150 }, solar_sensor: { x: 235, y: 70 },
  battery: { x: 70, y: 330 }, battery_sensor: { x: 235, y: 330 }, demand: { x: 70, y: 240 },
  demand_sensor: { x: 235, y: 200 }, communication: { x: 405, y: 100 }, firmware: { x: 405, y: 330 },
  controller: { x: 560, y: 200 }, inverter: { x: 730, y: 200 }, delivered: { x: 895, y: 200 },
}
export default function GridGraph({ graph, evidence = [], compact = false }: { graph: GraphData; evidence?: Evidence[]; compact?: boolean }) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<Core | null>(null)
  const viewport = useRef<{ zoom: number; pan: { x: number; y: number } } | null>(null)
  const [selected, setSelected] = useState<{ kind: 'node'; value: GraphNode } | { kind: 'edge'; value: GraphEdge } | null>(null)
  useEffect(() => {
    let dispose = () => {}
    // Strict Mode may immediately unmount an effect; start the canvas only once
    // its container survives a frame, then destroy after Cytoscape is ready.
    const frame = requestAnimationFrame(() => {
    if (!container.current?.isConnected) return
    const cy = cytoscape({ container: container.current, layout: { name: 'preset', fit: !viewport.current, padding: compact ? 12 : 32 },
      minZoom: 0.25, maxZoom: 2.5, wheelSensitivity: 0.2,
      elements: [
        ...graph.nodes.map(node => ({ data: { id: node.id, label: node.label.replace(' ', '\n') }, position: positions[node.id], classes: `${node.candidate_source ? 'source' : ''} ${node.observed_symptom ? 'symptom' : ''} ${node.potentially_affected ? 'affected' : ''}` })),
        ...graph.edges.map((edge, i) => ({ data: { id: `edge-${i}`, source: edge.source, target: edge.target }, classes: edge.suspected ? 'suspected' : '' })),
      ],
      style: [
        { selector: 'node', style: { 'background-color': '#122234', 'border-color': '#35516a', 'border-width': 1, 'width': 75, 'height': 48, 'shape': 'round-rectangle', 'label': 'data(label)', 'color': '#c5d4e5', 'font-size': 10, 'text-valign': 'center', 'text-halign': 'center', 'text-wrap': 'wrap', 'text-max-width': '72px', 'font-family': 'Segoe UI, sans-serif' } },
        { selector: 'node.affected', style: { 'border-color': '#54c9e8', 'background-color': '#102b3a' } },
        { selector: 'node.symptom', style: { 'border-color': '#d6a359', 'border-width': 2 } },
        { selector: 'node.source', style: { 'border-color': '#f3b76a', 'background-color': '#3a2c1d', 'border-width': 3, 'color': '#ffe2b8' } },
        { selector: 'edge', style: { 'width': 1, 'line-color': '#2c4158', 'target-arrow-color': '#2c4158', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.7, 'opacity': 0.8 } },
        { selector: 'edge.suspected', style: { 'width': 2.5, 'line-color': '#f3b76a', 'target-arrow-color': '#f3b76a', 'line-style': 'dashed', 'opacity': 1 } },
        { selector: ':selected', style: { 'overlay-color': '#65cfea', 'overlay-opacity': 0.1, 'overlay-padding': 7 } },
      ],
    })
    instance.current = cy
    if (viewport.current) cy.viewport(viewport.current)
    setSelected(current => {
      if (!current) return null
      if (current.kind === 'node') { const node = graph.nodes.find(item => item.id === current.value.id); return node ? { kind: 'node', value: node } : null }
      const edge = graph.edges.find(item => item.source === current.value.source && item.target === current.value.target)
      return edge ? { kind: 'edge', value: edge } : null
    })
    cy.on('tap', 'node', event => { const node = graph.nodes.find(n => n.id === event.target.id()); if (node) setSelected({ kind: 'node', value: node }) })
    cy.on('tap', 'edge', event => { const edge = graph.edges[Number(event.target.id().split('-')[1])]; if (edge) setSelected({ kind: 'edge', value: edge }) })
    const observer = new ResizeObserver(() => { cy.resize(); if (!viewport.current) cy.fit(undefined, compact ? 12 : 32) })
    observer.observe(container.current)
    dispose = () => { viewport.current = { zoom: cy.zoom(), pan: cy.pan() }; observer.disconnect(); cy.ready(() => { if (!cy.destroyed()) cy.destroy() }); if (instance.current === cy) instance.current = null }
    })
    return () => { cancelAnimationFrame(frame); dispose() }
  }, [graph, compact])
  const related = selected ? evidence.filter(item => selected.value.evidence_ids?.includes(item.id)) : []
  return <div className={`grid-graph ${compact ? 'compact' : ''}`}>
    <div className="graph-toolbar"><span><Network size={14} />Directed dependencies</span><button className="icon-button" aria-label="Fit dependency graph" onClick={() => instance.current?.fit(undefined, 24)}><Expand size={15} /></button></div>
    <div ref={container} className="graph-canvas" role="img" aria-label="Interactive microgrid dependency graph. Use the component selector below to inspect nodes." />
    {!compact && <div className="graph-legend"><span><i className="line-key" />Known dependency</span><span><i className="line-key suspected" />Suspected path</span><span><i className="node-key" />Candidate source</span></div>}
    {!compact && <label className="graph-select">Inspect component<select aria-label="Inspect component" value={selected?.kind === 'node' ? selected.value.id : ''} onChange={event => { const value = graph.nodes.find(node => node.id === event.target.value); setSelected(value ? { kind: 'node', value } : null) }}><option value="">Select a node…</option>{graph.nodes.map(node => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>}
    {selected && !compact && <div className="node-inspector"><div className="flex items-center justify-between"><h3>{selected.kind === 'node' ? selected.value.label : `${human(selected.value.source)} → ${human(selected.value.target)}`}</h3><button aria-label="Close component inspection" className="icon-button" onClick={() => setSelected(null)}><X size={16} /></button></div>
      {selected.kind === 'edge' ? <><p>{selected.value.dependency}</p><p className="muted">{selected.value.evidence_scope ?? 'Known dependency only'}. {selected.value.uncertainty}</p></> : <>
        <p className="muted">{selected.value.candidate_source ? 'Candidate source hypothesis. ' : ''}{selected.value.observed_symptom ? 'A symptom was observed during this incident. ' : ''}{selected.value.potentially_affected ? 'Potentially involved downstream. ' : ''}</p>
        {selected.value.telemetry?.length ? <div className="table-scroll"><table><thead><tr><th>Latest observation</th><th>Value</th></tr></thead><tbody>{Object.entries(selected.value.telemetry.at(-1)!).map(([key, value]) => <tr key={key}><td>{human(key)}</td><td>{typeof value === 'number' ? number(value, 3) : JSON.stringify(value)}</td></tr>)}</tbody></table></div> : <p className="muted">No incident-specific telemetry attached to this topology.</p>}
        {!!selected.value.events?.length && <><p className="muted">{selected.value.events.length} observed event(s) attached to this node:</p>{selected.value.events.slice(-10).map((event, index) => <div className="evidence-mini" key={`${event.tick}-${index}`}>Tick {event.tick} · {human(event.event)}{event.signal ? ` · ${human(event.signal)}` : ''}</div>)}</>}
      </>}
      {related.map(item => <div className="evidence-mini" key={item.id}>Tick {item.tick} · {human(item.signal)}: {number(item.value, 3)} {item.unit}; limit {number(item.threshold, 3)}</div>)}
      {!related.length && <p className="muted">No direct symptom evidence attached. A structural connection alone does not establish causation.</p>}
    </div>}
  </div>
}
