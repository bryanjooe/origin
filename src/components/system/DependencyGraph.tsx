import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition, EventObject } from 'cytoscape'
import type { TopologyEdge, TopologyNode } from '../../types/domain'

export function DependencyGraph({
  nodes,
  edges = [],
  onNodeSelect,
  height = 330,
  selectedNode,
}: {
  nodes: TopologyNode[]
  edges?: TopologyEdge[]
  onNodeSelect?: (node: TopologyNode) => void
  height?: number
  selectedNode?: string
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Core | null>(null)
  const selectRef = useRef(onNodeSelect)
  const nodesRef = useRef(nodes)
  selectRef.current = onNodeSelect
  nodesRef.current = nodes

  useEffect(() => {
    if (!hostRef.current || !nodes.length) return
    const elements: ElementDefinition[] = [
      ...nodes.map((node) => ({ data: { id: node.id, label: node.label ?? node.id, status: node.status ?? 'unknown' } })),
      ...edges.filter((edge) => nodes.some((node) => node.id === edge.source) && nodes.some((node) => node.id === edge.target)).map((edge, index) => ({
        data: { id: edge.id ?? `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, label: edge.label ?? edge.kind ?? edge.type ?? '' },
        classes: edge.suspected || edge.kind?.toLowerCase() === 'suspected' || edge.type?.toLowerCase() === 'suspected' ? 'suspected' : 'known',
      })),
    ]
    const cy = cytoscape({
      container: hostRef.current,
      elements,
      layout: { name: 'breadthfirst', directed: true, padding: 24, spacingFactor: 1.15, animate: false },
      minZoom: 0.45,
      maxZoom: 2.2,
      style: [
        { selector: 'node', style: { 'background-color': '#e1ebe4', 'border-color': '#719683', 'border-width': 1.25, label: 'data(label)', color: '#1c2924', 'font-family': 'Avenir Next, Segoe UI, sans-serif', 'font-size': '12.5px', 'text-wrap': 'wrap', 'text-max-width': '112.5px', width: 97.5, height: 47.5, shape: 'round-rectangle', 'text-valign': 'center', 'text-halign': 'center' } },
        { selector: 'node[status = "critical"]', style: { 'background-color': '#f3e2df', 'border-color': '#a9433d' } },
        { selector: 'node[status = "warning"]', style: { 'background-color': '#f3eadb', 'border-color': '#a9622f' } },
        { selector: 'node:selected', style: { 'border-width': 2.5, 'border-color': '#168c98', 'background-color': '#d7eaeb' } },
        { selector: 'edge', style: { width: 1.25, 'line-color': '#98a99d', 'target-arrow-color': '#98a99d', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.75 } },
        { selector: 'edge.suspected', style: { 'line-style': 'dashed', width: 2.5, 'line-color': '#a9622f', 'target-arrow-color': '#a9622f' } },
      ],
    })
    cy.on('tap', 'node', (event: EventObject) => {
      const selected = nodesRef.current.find((node) => node.id === event.target.id())
      if (selected) selectRef.current?.(selected)
    })
    cyRef.current = cy
    return () => {
      cyRef.current = null
      cy.destroy()
    }
  }, [nodes, edges])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !selectedNode) return
    cy.nodes().unselect()
    cy.getElementById(selectedNode).select()
  }, [selectedNode])

  return <div className="graph-wrap"><div className="dependency-graph" ref={hostRef} style={{ height }} role="img" aria-label="Microgrid dependency graph. Solid lines are known dependencies; dashed amber lines are suspected propagation paths." />{onNodeSelect && <div className="graph-node-list" aria-label="Select a graph component">{nodes.map((node) => <button key={node.id} type="button" className="graph-node-button" aria-pressed={selectedNode === node.id} onClick={() => onNodeSelect(node)}>{node.label ?? node.id}</button>)}</div>}</div>
}
