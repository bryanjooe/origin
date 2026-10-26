import { useState } from 'react'
import { Play, RefreshCw } from 'lucide-react'
import { useApiResource } from '../hooks/useApiResource'
import { api } from '../services/api'
import { formatNumber, percent } from '../utils/data'
import { Badge, Button, Card, EmptyState, Stat } from '../components/ui'

export function ModelEvaluationPage() {
  const resource = useApiResource('model-metrics', api.getModelMetrics, 2_000)
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
  </>
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
