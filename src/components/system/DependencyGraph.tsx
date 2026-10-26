import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition, EventObject } from 'cytoscape'
import type { TopologyEdge, TopologyNode } from '../../types/domain'

export function graphElements(nodes: TopologyNode[], edges: TopologyEdge[]): ElementDefinition[] {
  const ids = new Set(nodes.map((node) => node.id))
  return [
    ...nodes.map((node) => ({ data: { id: node.id, label: node.label ?? node.id, status: node.status ?? 'unknown' },
      classes: [node.potentially_affected || node.security_potentially_affected ? 'possible' : '',
        node.observed_symptom || node.security_observed ? 'observed' : '', node.candidate_source ? 'phase1-origin' : '',
        node.security_candidate ? 'security-origin' : ''].filter(Boolean).join(' ') })),
    ...edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)).map((edge) => ({
      data: { id: edge.id ?? `${edge.source}-${edge.target}`, source: edge.source, target: edge.target },
      classes: [edge.suspected || edge.kind?.toLowerCase() === 'suspected' || edge.type?.toLowerCase() === 'suspected' ? 'suspected' : 'known', edge.security_suspected ? 'security-path' : ''].join(' '),
    })),
  ]
}

export function DependencyGraph({
  nodes,
  edges = [],
  onNodeSelect,
  height = 330,
  selectedNode,
  highlightedNodes = [],
}: {
  nodes: TopologyNode[]
  edges?: TopologyEdge[]
  onNodeSelect?: (node: TopologyNode) => void
  height?: number
  selectedNode?: string
  highlightedNodes?: string[]
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Core | null>(null)
  const selectRef = useRef(onNodeSelect)
  const nodesRef = useRef(nodes)
  selectRef.current = onNodeSelect
  nodesRef.current = nodes

  useEffect(() => {
    if (!hostRef.current) return
    const cy = cytoscape({
      container: hostRef.current,
      elements: [],
      minZoom: 0.45,
      maxZoom: 2.2,
      style: [
        { selector: 'node', style: { 'background-color': '#e1ebe4', 'border-color': '#719683', 'border-width': 1.25, label: 'data(label)', color: '#1c2924', 'font-family': 'Avenir Next, Segoe UI, sans-serif', 'font-size': '12.5px', 'text-wrap': 'wrap', 'text-max-width': '112.5px', width: 97.5, height: 47.5, shape: 'round-rectangle', 'text-valign': 'center', 'text-halign': 'center' } },
        { selector: 'node[status = "critical"]', style: { 'background-color': '#f3e2df', 'border-color': '#a9433d' } },
        { selector: 'node[status = "warning"]', style: { 'background-color': '#f3eadb', 'border-color': '#a9622f' } },
        { selector: 'node.possible', style: { 'border-style': 'dotted', 'background-color': '#edf1eb' } },
        { selector: 'node.observed', style: { 'background-color': '#f3eadb', 'border-color': '#a9622f' } },
        { selector: 'node.phase1-origin', style: { 'border-width': 3.5, 'border-color': '#a9622f' } },
        { selector: 'node.security-origin', style: { 'border-width': 4, 'border-color': '#17684f', 'border-style': 'dashed' } },
        { selector: 'node.timeline-focus', style: { 'underlay-color': '#168c98', 'underlay-opacity': 0.2, 'underlay-padding': 7 } },
        { selector: 'node:selected', style: { 'border-width': 2.5, 'border-color': '#168c98', 'background-color': '#d7eaeb' } },
        { selector: 'edge', style: { width: 1.25, 'line-color': '#98a99d', 'target-arrow-color': '#98a99d', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.75 } },
        { selector: 'edge.suspected', style: { 'line-style': 'dashed', width: 2.5, 'line-color': '#a9622f', 'target-arrow-color': '#a9622f' } },
        { selector: 'edge.security-path', style: { 'line-style': 'dashed', width: 2.5, 'line-color': '#17684f', 'target-arrow-color': '#17684f' } },
      ],
    })
    const select = (event: EventObject) => {
      const selected = nodesRef.current.find((node) => node.id === event.target.id())
      if (selected) selectRef.current?.(selected)
    }
    cy.on('tap', 'node', select)
    cyRef.current = cy
    return () => {
      cyRef.current = null
      cy.off('tap', 'node', select)
      cy.destroy()
    }
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const elements = graphElements(nodes, edges)
    const desired = new Set(elements.map((element) => String(element.data.id)))
    const structureChanged = cy.elements().length !== elements.length || elements.some((element) => cy.getElementById(String(element.data.id)).empty())
    cy.batch(() => {
      cy.elements().filter((element) => !desired.has(element.id())).remove()
      for (const element of elements) {
        const existing = cy.getElementById(String(element.data.id))
        if (existing.empty()) cy.add(element)
        else { existing.data(element.data); existing.classes(element.classes ?? '') }
      }
    })
    if (structureChanged) cy.layout({ name: 'breadthfirst', directed: true, padding: 24, spacingFactor: 1.15, animate: false }).run()
  }, [nodes, edges])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().unselect()
    if (selectedNode) cy.getElementById(selectedNode).select()
    cy.nodes().removeClass('timeline-focus')
    for (const id of highlightedNodes) cy.getElementById(id).addClass('timeline-focus')
  }, [selectedNode, highlightedNodes, nodes, edges])

  return <div className="graph-wrap"><div className="dependency-graph" ref={hostRef} style={{ height }} role="img" aria-label="Microgrid dependency graph. Solid lines are known dependencies; dashed amber lines are suspected propagation paths." />{onNodeSelect && <div className="graph-node-list" aria-label="Select a graph component">{nodes.map((node) => <button key={node.id} type="button" className="graph-node-button" aria-pressed={selectedNode === node.id} onClick={() => onNodeSelect(node)}>{node.label ?? node.id}</button>)}</div>}</div>
}
