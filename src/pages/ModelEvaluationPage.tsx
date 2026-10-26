import { useState } from 'react'
import { Play, RefreshCw } from 'lucide-react'
import { useApiResource } from '../hooks/useApiResource'
import { api } from '../services/api'
import { formatNumber, percent } from '../utils/data'
import { Badge, Button, Card, EmptyState, Stat } from '../components/ui'
import type { SecurityMetrics, SecurityProtocolReport, SecurityTaskReport } from '../types/domain'

export function ModelEvaluationPage() {
  const resource = useApiResource('model-metrics', api.getModelMetrics, 2_000)
  const securityResource = useApiResource('security-metrics', api.getSecurityMetrics)
  const [evaluating, setEvaluating] = useState(false)
  const [evaluationError, setEvaluationError] = useState<string | null>(null)
  const metrics = resource.data

  async function runEvaluation() {
    if (evaluating) return
    setEvaluating(true)
    setEvaluationError(null)
    try {
      await api.evaluateModel()
      resource.reload()
    } catch (error) {
      setEvaluationError(error instanceof Error ? error.message : 'Evaluation could not be run.')
    } finally {
      setEvaluating(false)
    }
  }

  const detector = metrics?.anomaly_detector
  const unavailable = metrics && metrics.trained === false

  return <>
    <div className="page-intro"><div><p className="eyebrow">MODEL / HELD-OUT VALIDATION</p><h1>Model evaluation</h1><p className="intro-copy">Performance is computed on held-out simulation scenarios; this view reports API results only.</p></div><Button variant="primary" icon={<Play size={14} />} loading={evaluating} disabled={evaluating} onClick={() => void runEvaluation()}>Run evaluation</Button></div>
    {resource.loading && !metrics && <EmptyState title="Loading evaluation metrics" kind="loading" />}
    {resource.error && !metrics && <EmptyState title="Evaluation metrics unavailable" detail={resource.error} kind="error" action={<Button onClick={resource.reload} icon={<RefreshCw size={14} />}>Retry</Button>} />}
    {evaluationError && <div className="inline-error" role="alert">Evaluation failed: {evaluationError}</div>}
    {(evaluating || metrics?.evaluation_status === 'running') && <p className="muted-small" role="status">The API is computing a real held-out evaluation. Results will appear when the job finishes.</p>}
    {metrics?.evaluation_status === 'complete' && <Badge severity="normal">LATEST EVALUATION COMPLETE</Badge>}
    {!resource.loading && !resource.error && !metrics && <EmptyState title="No evaluation results" detail="The model metrics endpoint returned no results. Run evaluation when the model is trained." kind="unknown" />}
    {metrics && unavailable && <EmptyState title="Model not trained" detail="Evaluation metrics are not available until the backend reports a trained model." kind="unknown" />}
    {metrics && !unavailable && <>
      <div className="stat-grid evaluation-stats">
        <Stat label="Dataset size" value={metrics.dataset_size} note="Samples reported by API" />
        <Stat label="Train scenarios" value={metrics.train_scenario_count} />
        <Stat label="Test scenarios" value={metrics.test_scenario_count} note="Held-out scenarios" />
        <Stat label="Classification accuracy" value={asPercent(metrics.accuracy)} unit={metrics.accuracy == null ? undefined : '%'} severity={metrics.accuracy == null ? 'unknown' : 'normal'} />
        <Stat label="False-positive rate" value={asPercent(detector?.false_positive_rate)} unit={detector?.false_positive_rate == null ? undefined : '%'} />
        <Stat label="Detection delay" value={detector?.detection_delay_seconds} unit={detector?.detection_delay_seconds == null ? undefined : 's'} />
      </div>
      <div className="two-column-grid evaluation-main">
        <Card title="Per-class performance" eyebrow="PRECISION / RECALL / F1">
          {metrics.per_class?.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Class</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr></thead><tbody>{metrics.per_class.map((item) => <tr key={item.label}><th>{item.label}</th><td>{displayRate(item.precision)}</td><td>{displayRate(item.recall)}</td><td>{displayRate(item.f1)}</td><td>{item.support ?? '—'}</td></tr>)}</tbody></table></div> : <EmptyState title="Class metrics unavailable" detail="The API did not return per-class scores." kind="unknown" />}
        </Card>
        <Card title="Anomaly detector" eyebrow="RESIDUAL / DETECTION METRICS">
          {detector ? <div className="metric-list"><MetricLine label="Precision" value={displayRate(detector.precision)} /><MetricLine label="Recall" value={displayRate(detector.recall)} /><MetricLine label="F1 score" value={displayRate(detector.f1)} /><MetricLine label="False-positive rate" value={displayRate(detector.false_positive_rate)} /><MetricLine label="Detection delay" value={detector.detection_delay_seconds == null ? '—' : `${formatNumber(detector.detection_delay_seconds, 2)} s`} /></div> : <EmptyState title="Anomaly metrics unavailable" detail="No detector metrics were returned." kind="unknown" />}
          <p className="data-footnote">These metrics describe the anomaly detector and are separate from ML fault-source predictions.</p>
        </Card>
      </div>
      <div className="two-column-grid evaluation-lower">
        <Card title="Confusion matrix" eyebrow="HELD-OUT SCENARIOS">
          {metrics.confusion_matrix?.labels.length ? <div className="table-scroll"><table className="data-table confusion-table"><thead><tr><th>Actual \ Predicted</th>{metrics.confusion_matrix.labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{metrics.confusion_matrix.labels.map((label, row) => <tr key={label}><th>{label}</th>{metrics.confusion_matrix?.labels.map((_, column) => <td className={row === column ? 'matrix-diagonal' : ''} key={column}>{metrics.confusion_matrix?.values[row]?.[column] ?? '—'}</td>)}</tr>)}</tbody></table></div> : <EmptyState title="Confusion matrix unavailable" detail="The API did not return class labels and counts." kind="unknown" />}
        </Card>
        <Card title="Performance by severity" eyebrow="HELD-OUT DETECTION RECALL">
          {metrics.by_severity?.length ? <div className="severity-performance">{metrics.by_severity.map((row) => <div className="severity-row" key={row.severity}><Badge severity="unknown">{row.severity}</Badge>{row.recall !== undefined ? <span>Detection recall <strong>{displayRate(row.recall)}</strong></span> : <span>Accuracy <strong>{displayRate(row.accuracy)}</strong></span>}</div>)}</div> : <EmptyState title="Severity breakdown unavailable" detail="No severity-specific evaluation scores were returned." kind="unknown" />}
        </Card>
      </div>
    </>}
    <SecurityEvaluation resource={securityResource.data} loading={securityResource.loading} error={securityResource.error} onRetry={securityResource.reload} />
  </>
}

function SecurityEvaluation({ resource, loading, error, onRetry }: { resource: SecurityMetrics | null; loading: boolean; error: string | null; onRetry: () => void }) {
  if (loading && !resource) return <section className="stage-b-evaluation"><EmptyState title="Loading fault-vs-attack evaluation" kind="loading" /></section>
  if (error && !resource) return <section className="stage-b-evaluation"><EmptyState title="Security evaluation unavailable" detail={error} kind="error" action={<Button onClick={onRetry} icon={<RefreshCw size={14} />}>Retry</Button>} /></section>
  if (!resource?.held_out) return <section className="stage-b-evaluation"><Card title="Fault vs attack classification" eyebrow="STAGE B / SYNTHETIC STUDY"><EmptyState title="Stage B evaluation results unavailable" detail={resource?.results_error ?? 'The backend has not supplied held-out security classification reports.'} kind="unknown" /></Card></section>

  const held = resource.held_out
  const stealth = resource.stealth_generalization
  const nature = held.nature
  const binary = held.fault_vs_attack
  const origin = held.origin
  return <section className="stage-b-evaluation">
    <div className="page-intro stage-b-heading"><div><p className="eyebrow">STAGE B / FAULT VS ATTACK</p><h2>Security classification</h2><p className="intro-copy">Seeded synthetic-simulation results. This independent classifier complements the existing source classifier.</p></div><Badge severity={resource.available ? 'normal' : 'unknown'}>{resource.available ? 'LIVE MODEL AVAILABLE' : 'LIVE MODEL UNAVAILABLE'}</Badge></div>
    {!resource.available && <div className="inline-error" role="status">Held-out study results are shown, but incident predictions are unavailable: {resource.model_error ?? 'security model not loaded'}.</div>}
    <div className="stat-grid evaluation-stats">
      <Stat label="Generated runs" value={resource.run_count} note="Whole-run split" />
      <Stat label="Nature macro F1" value={rate(nature?.macro_f1)} unit="%" />
      <Stat label="Fault / attack F1" value={rate(binary?.macro_f1)} unit="%" />
      <Stat label="Origin-layer macro F1" value={rate(origin?.macro_f1)} unit="%" />
      <Stat label="Detector coverage" value={rate(held.detector_coverage)} unit="%" />
      <Stat label="Normal false-alert rate" value={rate(held.normal_run_false_positive_rate?.detector_fire)} unit="%" />
    </div>
    <Card title="Dataset and protocol" eyebrow="SYNTHETIC / RUN-LEVEL SPLIT">
      <div className="stage-b-run-counts">{Object.entries(resource.class_run_counts ?? {}).map(([label, count]) => <div key={label}><span>{label.replaceAll('_', ' ')}</span><strong>{formatNumber(count, 0)}</strong></div>)}</div>
      <p className="data-footnote">{resource.provenance ?? 'Synthetic simulations only.'} Training and test partitions are split by complete run. Confidence kind: {resource.confidence_kind ?? 'not reported'}.</p>
      {resource.calibration_note && <p className="data-footnote">{resource.calibration_note}</p>}
    </Card>
    <div className="two-column-grid evaluation-main">
      <Card title="Nature classifier" eyebrow="HELD-OUT / PRECISION · RECALL · F1"><TaskMetrics report={nature} /></Card>
      <Card title="Fault vs attack" eyebrow="HELD-OUT / BINARY ATTRIBUTION"><TaskMetrics report={binary} /><CompactMatrix report={binary} /></Card>
    </div>
    <div className="two-column-grid evaluation-main">
      <Card title="Origin-layer classifier" eyebrow="FAULTS AND ATTACKS / HELD-OUT"><TaskMetrics report={origin} /><CompactMatrix report={origin} /></Card>
      <Card title="Stealthy-held-out generalization" eyebrow="STEALTHY ATTACKS EXCLUDED FROM TRAINING">
        {stealth ? <><div className="metric-list"><MetricLine label="Nature macro F1" value={displayRate(stealth.nature?.macro_f1)} /><MetricLine label="Fault / attack macro F1" value={displayRate(stealth.fault_vs_attack?.macro_f1)} /><MetricLine label="Origin-layer macro F1" value={displayRate(stealth.origin?.macro_f1)} /><MetricLine label="Detector coverage" value={displayRate(stealth.detector_coverage)} /><MetricLine label="Attack detection delay" value={stealth.attack_detection_delay_ticks?.mean == null ? '—' : `${formatNumber(stealth.attack_detection_delay_ticks.mean, 2)} ticks`} /><MetricLine label="Nature abstention" value={displayRate(stealth.abstention_rate?.nature)} /></div><FeatureImportance report={stealth} /></> : <EmptyState title="Generalization report unavailable" detail="The backend did not return a stealth-held-out report." kind="unknown" />}
      </Card>
    </div>
    <div className="two-column-grid evaluation-main">
      <Card title="Attack performance by scenario" eyebrow="ATTACK LABEL RATE / HELD-OUT RUNS">
        <AttackBreakdown title="By stealth level" rows={held.nature_recall_by_stealth} />
        <AttackBreakdown title="By attack type" rows={held.nature_recall_by_attack_type} />
      </Card>
      <Card title="Origin-layer comparison" eyebrow="SAME HELD-OUT FAULT RUNS / EXISTING CLASSIFIER PRESERVED">
        {held.fault_only_origin_comparison ? <div className="metric-list"><MetricLine label="Existing source classifier · macro F1" value={displayRate(held.fault_only_origin_comparison.existing_source_classifier?.macro_f1_including_unknown)} /><MetricLine label="New origin layer model · macro F1" value={displayRate(held.fault_only_origin_comparison.new_origin_layer_classifier?.macro_f1_including_unknown)} /><MetricLine label="Existing classifier coverage" value={displayRate(held.fault_only_origin_comparison.existing_source_classifier?.coverage)} /><MetricLine label="New model coverage" value={displayRate(held.fault_only_origin_comparison.new_origin_layer_classifier?.coverage)} /></div> : <EmptyState title="Comparison unavailable" detail="The backend did not return the same-run classifier comparison." kind="unknown" />}
        <p className="data-footnote">Origin-layer classification is a separate task from fault-vs-attack nature classification.</p>
      </Card>
    </div>
    <p className="data-footnote">Predictions and evidence are indicators, not proof of intent. The synthetic telemetry does not include attacker identity or independently verifiable authorization provenance.</p>
  </section>
}

function TaskMetrics({ report }: { report?: SecurityTaskReport }) {
  const entries = Object.entries(report?.per_class ?? {})
  return entries.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Class</th><th>Precision</th><th>Recall</th><th>F1</th><th>Runs</th></tr></thead><tbody>{entries.map(([label, item]) => <tr key={label}><th>{label}</th><td>{displayRate(item.precision)}</td><td>{displayRate(item.recall)}</td><td>{displayRate(item['f1-score'])}</td><td>{item.support == null ? '—' : formatNumber(item.support, 0)}</td></tr>)}</tbody></table></div> : <EmptyState title="Class metrics unavailable" detail="No class-level scores were reported." kind="unknown" />
}

function CompactMatrix({ report }: { report?: SecurityTaskReport }) {
  const matrix = report?.confusion_matrix
  if (!matrix?.labels.length) return null
  return <div className="table-scroll security-matrix"><table className="data-table confusion-table"><thead><tr><th>Actual \ Predicted</th>{matrix.labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{matrix.labels.map((label, row) => <tr key={label}><th>{label}</th>{matrix.labels.map((_, column) => <td className={row === column ? 'matrix-diagonal' : ''} key={column}>{matrix.counts[row]?.[column] ?? '—'}</td>)}</tr>)}</tbody></table></div>
}

function FeatureImportance({ report }: { report: SecurityProtocolReport }) {
  const entries = report.nature_feature_importance_by_stealth?.stealthy ?? []
  return <div className="security-feature-list"><h3>Signals used for stealthy cases</h3>{entries.length ? entries.slice(0, 6).map((item) => <div key={item.feature}><span>{item.feature.replaceAll('_', ' ')}</span><strong>{formatNumber(item.importance, 3)}</strong></div>) : <p className="muted-small">Feature-importance results were not reported.</p>}</div>
}

function AttackBreakdown({ title, rows }: { title: string; rows?: Record<string, { attack_label_rate?: number; detector_fire_rate?: number; run_count?: number }> }) {
  const entries = Object.entries(rows ?? {})
  return <div className="security-breakdown"><h3>{title}</h3>{entries.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Group</th><th>Runs</th><th>Attack label</th><th>Detector fire</th></tr></thead><tbody>{entries.map(([name, values]) => <tr key={name}><th>{name.replaceAll('_', ' ')}</th><td>{values.run_count ?? '—'}</td><td>{displayRate(values.attack_label_rate)}</td><td>{displayRate(values.detector_fire_rate)}</td></tr>)}</tbody></table></div> : <EmptyState title="Breakdown unavailable" detail="No results were reported for this group." kind="unknown" />}</div>
}

function rate(value: number | null | undefined) {
  const formatted = displayRate(value)
  return formatted === '—' ? undefined : formatted.slice(0, -1)
}

function asPercent(value: number | null | undefined) {
  const normalized = percent(value)
  return normalized === undefined ? undefined : formatNumber(normalized, 1)
}

function displayRate(value: number | null | undefined) {
  const normalized = asPercent(value)
  return normalized === undefined ? '—' : `${normalized}%`
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return <div className="metric-line"><span>{label}</span><strong>{value}</strong></div>
}
