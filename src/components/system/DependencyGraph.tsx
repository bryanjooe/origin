import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition, EventObject, StylesheetStyle } from 'cytoscape'
import type { TopologyEdge, TopologyNode } from '../../types/domain'
import { useTheme } from '../../context/ThemeContext'

function graphStyles(isDark: boolean): StylesheetStyle[] {
  return [
    { selector: 'node', style: { 'background-color': isDark ? '#203c31' : '#e1ebe4', 'border-color': isDark ? '#72c69b' : '#719683', 'border-width': 1.25, label: 'data(label)', color: isDark ? '#e5eee8' : '#1c2924', 'font-family': 'Avenir Next, Segoe UI, sans-serif', 'font-size': '12.5px', 'text-wrap': 'wrap', 'text-max-width': '112.5px', width: 97.5, height: 47.5, shape: 'round-rectangle', 'text-valign': 'center', 'text-halign': 'center' } },
    { selector: 'node[status = "critical"]', style: { 'background-color': isDark ? '#462c2a' : '#f3e2df', 'border-color': isDark ? '#f09b92' : '#a9433d' } },
    { selector: 'node[status = "warning"]', style: { 'background-color': isDark ? '#453824' : '#f3eadb', 'border-color': isDark ? '#e5ad6f' : '#a9622f' } },
    { selector: 'node.possible', style: { 'border-style': 'dotted', 'background-color': isDark ? '#29382e' : '#edf1eb' } },
    { selector: 'node.observed', style: { 'background-color': isDark ? '#453824' : '#f3eadb', 'border-color': isDark ? '#e5ad6f' : '#a9622f' } },
    { selector: 'node.phase1-origin', style: { 'border-width': 3.5, 'border-color': isDark ? '#e5ad6f' : '#a9622f' } },
    { selector: 'node.security-origin', style: { 'border-width': 4, 'border-color': isDark ? '#72c69b' : '#17684f', 'border-style': 'dashed' } },
    { selector: 'node.timeline-focus', style: { 'underlay-color': isDark ? '#62c3cc' : '#168c98', 'underlay-opacity': 0.2, 'underlay-padding': 7 } },
    { selector: 'node:selected', style: { 'border-width': 2.5, 'border-color': isDark ? '#62c3cc' : '#168c98', 'background-color': isDark ? '#244a4c' : '#d7eaeb' } },
    { selector: 'edge', style: { width: 1.25, 'line-color': isDark ? '#718b7c' : '#98a99d', 'target-arrow-color': isDark ? '#718b7c' : '#98a99d', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.75 } },
    { selector: 'edge.suspected', style: { 'line-style': 'dashed', width: 2.5, 'line-color': isDark ? '#e5ad6f' : '#a9622f', 'target-arrow-color': isDark ? '#e5ad6f' : '#a9622f' } },
    { selector: 'edge.security-path', style: { 'line-style': 'dashed', width: 2.5, 'line-color': isDark ? '#72c69b' : '#17684f', 'target-arrow-color': isDark ? '#72c69b' : '#17684f' } },
  ]
}

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
  const { theme } = useTheme()
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
      style: graphStyles(theme === 'dark'),
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
    cyRef.current?.style().fromJson(graphStyles(theme === 'dark')).update()
  }, [theme])

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
