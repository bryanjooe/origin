import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from 'react'
import { Activity, ArrowDown, ArrowRight, ChartNoAxesCombined, CircleHelp, GitBranch, Menu, ShieldCheck, Waypoints, X } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ThemeToggle } from '../components/ui/ThemeToggle'
import './homepage.css'

const INTRO_SEEN_KEY = 'tracex-greengrid-intro-seen'
const SECTIONS = ['overview', 'capabilities', 'workflow', 'architecture'] as const
const SECTION_LABELS = { overview: 'Overview', capabilities: 'Capabilities', workflow: 'How it works', architecture: 'Architecture' } as const
const capabilities = [
  ['01', 'Simulate and inject', 'Run a software microgrid and introduce a seeded fault with chosen timing and severity.', 'SOLAR · BATTERY · DEMAND · INVERTER', Activity],
  ['02', 'Detect abnormal behavior', 'An Isolation Forest learns normal simulated behavior and flags telemetry that departs from it.', 'ANOMALY DETECTION', ChartNoAxesCombined],
  ['03', 'Rank likely sources', 'A Random Forest ranks candidate sources. If evidence is too weak, the result can be Unknown.', 'SOURCE LOCALIZATION', Waypoints],
  ['04', 'Trace and explain', 'Dependency paths connect a source hypothesis to affected components and the evidence behind it.', 'GRAPH + INVESTIGATION REPORT', GitBranch],
] as const

function wantsIntro() {
  if (typeof window === 'undefined' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  try { return window.sessionStorage.getItem(INTRO_SEEN_KEY) !== '1' } catch { return false }
}
function rememberIntro() {
  try { window.sessionStorage.setItem(INTRO_SEEN_KEY, '1') } catch { /* Storage is optional. */ }
}

function IntroExperience({ onSkip, transitioning, cardRef }: { onSkip: () => void; transitioning: boolean; cardRef: RefObject<HTMLDivElement | null> }) {
  return <section className={'origin-intro-screen' + (transitioning ? ' is-transitioning' : '')} aria-label="TraceX GreenGrid opening sequence">
    <div className="origin-intro-grain" aria-hidden="true" />
    <div className="origin-intro-header">
      <div className="origin-intro-brand"><span className="origin-brand-mark origin-brand-mark-light" aria-hidden="true"><i /><i /><i /></span><span>TraceX<small>GREEN GRID</small></span></div>
      <button className="origin-intro-skip" onClick={onSkip}>Skip intro <ArrowRight size={14} /></button>
    </div>
    <div className="origin-intro-center">
      <p className="origin-intro-kicker"><i /> SIMULATED MICROGRID / ILLUSTRATIVE TRACE</p>
      <div className="origin-intro-title"><span>TraceX</span><em>GreenGrid</em></div>
      <p className="origin-intro-tagline">Find the fault. Save the energy.</p>
      <div className="origin-intro-card-wrap"><MicrogridDiagram className="origin-intro-card" visualRef={cardRef} /></div>
      <div className="origin-intro-method" aria-label="Detect, localize, trace, explain"><span>DETECT</span><i /><span>LOCALIZE</span><i /><span>TRACE</span><i /><span>EXPLAIN</span></div>
    </div>
    <div className="origin-intro-foot"><span>MODEL OUTPUTS ARE HYPOTHESES</span><span>SIMULATION / 01</span></div>
  </section>
}

function MicrogridDiagram({ className = '', visualRef }: { className?: string; visualRef?: RefObject<HTMLDivElement | null> }) {
  return <div className={'origin-product-visual ' + className} ref={visualRef}>
    <div className="origin-product-visual-head"><span><i /> MICROGRID / DEPENDENCY VIEW</span><span>CONCEPTUAL TRACE</span></div>
    <svg className="origin-product-svg" viewBox="0 0 820 350" fill="none" role="img" aria-labelledby="grid-title grid-desc">
      <title id="grid-title">TraceX GreenGrid component and dependency illustration</title>
      <desc id="grid-desc">Solar and battery sensors connect through communication and firmware dependencies to a controller and inverter. The suspected source and affected path are distinguished.</desc>
      <path className="origin-product-link link-normal" d="M204 82H250" /><path className="origin-product-link link-normal" d="M410 116V136" />
      <path className="origin-product-link link-normal" d="M204 270H250" /><path className="origin-product-link link-normal" d="M410 236V204" /><path className="origin-product-link origin-product-link-affected" d="M563 170H638" />
      <g className="origin-product-node node-solar"><rect x="14" y="48" width="190" height="68" /><circle cx="42" cy="82" r="14" /><path d="M42 72v20m-10-10h20m-17-7 14 14m0-14L35 89" /><text x="68" y="78">Solar + sensor</text><text className="product-sub" x="68" y="97">GENERATION / TELEMETRY</text></g>
      <g className="origin-product-node node-battery"><rect x="14" y="236" width="190" height="68" /><circle cx="42" cy="270" r="14" /><path d="M36 263h10v14H36zM46 267h3v6h-3m-9-2h6" /><text x="68" y="266">Battery + sensor</text><text className="product-sub" x="68" y="285">STORAGE / TELEMETRY</text></g>
      <g className="origin-product-node node-comms"><rect x="250" y="48" width="190" height="68" /><circle cx="278" cy="82" r="14" /><path d="M272 87a9 9 0 0 1 12 0m-9-4a5 5 0 0 1 6 0m-3 6h.01" /><text x="304" y="78">Communication</text><text className="product-sub" x="304" y="97">MESSAGE AGE / LINK</text></g>
      <g className="origin-product-node node-firmware"><rect x="250" y="236" width="190" height="68" /><circle cx="278" cy="270" r="14" /><path d="M272 265h12v10h-12zm3-3v3m6-3v3m-6 10v3m6-3v3" /><text x="304" y="266">Firmware / config</text><text className="product-sub" x="304" y="285">LIMITS / SETTINGS</text></g>
      <g className="origin-product-node node-controller"><rect x="385" y="136" width="178" height="68" /><circle cx="413" cy="170" r="14" /><path d="M407 170h12m-6-6v12" /><text x="439" y="166">Controller</text><text className="product-sub" x="439" y="185">SUSPECTED SOURCE</text></g>
      <g className="origin-product-node node-inverter"><rect x="638" y="136" width="170" height="68" /><circle cx="666" cy="170" r="14" /><path d="m660 175 4-10 4 10 4-10" /><text x="692" y="166">Inverter</text><text className="product-sub" x="692" y="185">AFFECTED PATH</text></g>
      <text className="product-legend" x="15" y="335">KNOWN DEPENDENCY</text><line className="product-legend-line" x1="144" y1="331" x2="179" y2="331" />
      <text className="product-legend" x="195" y="335">EVIDENCE-COMPATIBLE PATH</text><line className="product-legend-line legend-affected" x1="367" y1="331" x2="402" y2="331" />
    </svg>
    <div className="origin-product-visual-note"><CircleHelp size={14} /> Conceptual path; a likely source is not a proven cause.</div>
  </div>
}

export function Homepage() {
  const pageRef = useRef<HTMLDivElement>(null)
  const introCardRef = useRef<HTMLDivElement>(null)
  const heroCardRef = useRef<HTMLDivElement>(null)
  const transitionTimerRef = useRef<number | null>(null)
  const heroTextTimerRef = useRef<number | null>(null)
  const [introActive, setIntroActive] = useState(wantsIntro)
  const [introPhase, setIntroPhase] = useState<'playing' | 'transitioning'>('playing')
  const [heroTextReady, setHeroTextReady] = useState(() => !wantsIntro())
  const [homeReady, setHomeReady] = useState(false)
  const [pageExiting, setPageExiting] = useState(false)
  const [activeSection, setActiveSection] = useState<string>('overview')
  const [menuOpen, setMenuOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const dismissIntro = () => { rememberIntro(); setIntroActive(false); setHeroTextReady(true) }
  const replayIntro = () => {
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setMenuOpen(false)
      setHeroTextReady(false)
      setIntroPhase('playing')
      setIntroActive(true)
    }
  }

  const handleDestinationClick = (event: MouseEvent<HTMLAnchorElement>) => {
    const anchor = event.currentTarget
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || anchor.target === '_blank' || anchor.hasAttribute('download')) return
    const destination = new URL(anchor.href, window.location.href)
    if (destination.origin !== window.location.origin || destination.pathname === location.pathname) return
    const nextLocation = destination.pathname + destination.search + destination.hash
    event.preventDefault()
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { navigate(nextLocation); return }
    if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current)
    setMenuOpen(false)
    setPageExiting(true)
    transitionTimerRef.current = window.setTimeout(() => navigate(nextLocation), 300)
  }

  useEffect(() => {
    const page = pageRef.current
    if (!page) return
    const bodyMinWidth = document.body.style.minWidth
    document.body.style.minWidth = '0'
    const revealTargets = page.querySelectorAll<HTMLElement>('[data-origin-reveal]')
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) {
      revealTargets.forEach((target) => target.classList.add('is-visible'))
      setHomeReady(true)
    } else {
      const revealObserver = new IntersectionObserver((entries) => entries.forEach((entry) => {
        entry.target.classList.toggle('is-visible', entry.isIntersecting)
      }), { threshold: 0, rootMargin: '-10% 0px -14% 0px' })
      revealTargets.forEach((target) => {
        revealObserver.observe(target)
        const rect = target.getBoundingClientRect()
        if (rect.bottom > window.innerHeight * 0.1 && rect.top < window.innerHeight * 0.86) target.classList.add('is-visible')
      })
      setHomeReady(true)
      const activeTargets = SECTIONS.map((id) => page.querySelector<HTMLElement>('#' + id)).filter((section): section is HTMLElement => Boolean(section))
      const activeObserver = new IntersectionObserver((entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.boundingClientRect.top - a.boundingClientRect.top)
        const firstVisible = visible[0]
        if (firstVisible) setActiveSection(firstVisible.target.id)
      }, { threshold: 0, rootMargin: '-102px 0px -58% 0px' })
      activeTargets.forEach((target) => activeObserver.observe(target))
      return () => {
        revealObserver.disconnect()
        activeObserver.disconnect()
        document.body.style.minWidth = bodyMinWidth
      }
    }
    return () => { document.body.style.minWidth = bodyMinWidth }
  }, [])

  useEffect(() => {
    if (!introActive || introPhase !== 'playing') return
    const timer = window.setTimeout(() => setIntroPhase('transitioning'), 2580)
    return () => window.clearTimeout(timer)
  }, [introActive, introPhase])

  useLayoutEffect(() => {
    if (!introActive || introPhase !== 'transitioning') return
    const source = introCardRef.current
    const target = heroCardRef.current
    if (!source || !target) { dismissIntro(); return }
    const from = source.getBoundingClientRect()
    const to = target.getBoundingClientRect()
    const style = source.style
    style.position = 'fixed'
    style.top = `${from.top}px`
    style.left = `${from.left}px`
    style.width = `${from.width}px`
    style.height = `${from.height}px`
    style.maxWidth = 'none'
    style.margin = '0'
    style.zIndex = '1002'
    style.transformOrigin = 'top left'
    style.willChange = 'transform'
    style.transition = 'none'
    style.transform = 'translate3d(0, 0, 0) scale(1, 1)'
    const frame = window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      style.transition = 'transform 880ms cubic-bezier(.22,.74,.18,1)'
      style.transform = `translate3d(${to.left - from.left}px, ${to.top - from.top}px, 0) scale(${to.width / from.width}, ${to.height / from.height})`
    }))
    return () => window.cancelAnimationFrame(frame)
  }, [introActive, introPhase])

  useEffect(() => {
    if (!introActive || introPhase !== 'transitioning') return
    const timer = window.setTimeout(() => {
      rememberIntro()
      setIntroActive(false)
      heroTextTimerRef.current = window.setTimeout(() => setHeroTextReady(true), 160)
    }, 920)
    return () => window.clearTimeout(timer)
  }, [introActive, introPhase])

  useEffect(() => () => {
    if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current)
    if (heroTextTimerRef.current !== null) window.clearTimeout(heroTextTimerRef.current)
  }, [])

  useEffect(() => {
    const previousTitle = document.title
    document.title = 'TraceX GreenGrid · Find the fault. Save the energy.'
    return () => { document.title = previousTitle }
  }, [])

  return <div className={'origin-homepage' + (homeReady ? ' origin-home-ready' : '') + (introActive ? ' origin-intro-playing' : '') + (heroTextReady ? ' origin-hero-text-ready' : '') + (pageExiting ? ' origin-page-exit' : '')} ref={pageRef}>
    <a className="origin-skip-link" href="#origin-main">Skip to content</a>
    {introActive && <IntroExperience onSkip={dismissIntro} transitioning={introPhase === 'transitioning'} cardRef={introCardRef} />}
    <header className="origin-home-header">
      <Link className="origin-home-brand" to="/welcome" onClick={handleDestinationClick} aria-label="TraceX GreenGrid home"><span className="origin-brand-mark" aria-hidden="true"><i /><i /><i /></span><span>TraceX<small>GREEN GRID</small></span></Link>
      <nav id="tracex-home-nav" className={'origin-home-nav' + (menuOpen ? ' is-open' : '')} aria-label="Homepage navigation">
        {SECTIONS.map((section) => {
          const label = SECTION_LABELS[section]
          return <a key={section} href={'#' + section} aria-current={activeSection === section ? 'location' : undefined} onClick={() => setMenuOpen(false)}>{label}</a>
        })}
      </nav>
      <div className="origin-home-tools"><ThemeToggle className="origin-theme-toggle" /><Link className="origin-text-link" to="/register" onClick={handleDestinationClick}>Create account</Link><Link className="origin-header-cta" to="/login" onClick={handleDestinationClick}>Sign in <ArrowRight size={15} /></Link><button className="origin-mobile-menu" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} aria-controls="tracex-home-nav" onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? <X size={18} /> : <Menu size={18} />}</button></div>
    </header>

    <main id="origin-main">
      <section className="origin-hero" id="overview" aria-labelledby="origin-hero-title">
        <div className="origin-hero-copy">
          <p className="origin-kicker origin-hero-kicker"><span className="origin-live-pip" /> AI-POWERED MICROGRID INTELLIGENCE</p>
          <h1 id="origin-hero-title"><span>Find the fault.</span><em>Save the energy.</em></h1>
          <p className="origin-hero-description">TraceX GreenGrid simulates a solar-and-battery microgrid, detects abnormal behavior, ranks likely fault sources, and traces how a fault may spread—with evidence behind each result.</p>
          <div className="origin-hero-actions"><Link className="origin-button origin-button-primary" to="/login" onClick={handleDestinationClick}>Sign in to workspace <ArrowRight size={16} /></Link><a className="origin-text-link" href="#workflow">See how it works <ArrowDown size={15} /></a></div>
          <div className="origin-hero-footnote"><ShieldCheck size={14} /> Simulation-based research system <span /> Likely sources, not proven causes</div>
          <button className="origin-replay-button" onClick={replayIntro}><Activity size={13} /> Replay the system trace</button>
        </div>
        <div className="origin-hero-visual" data-origin-reveal="visual"><div className="origin-visual-index"><span>FIG. 01</span><span>MICROGRID / ILLUSTRATIVE</span></div><MicrogridDiagram visualRef={heroCardRef} /><div className="origin-visual-caption"><span>Abnormal signal</span><i /><span>likely source</span><i /><span>evidence path</span></div></div>
        <div className="origin-hero-bottom"><span>TRACEX GREENGRID / SIMULATION</span><span>DETECT · LOCALIZE · TRACE · EXPLAIN</span><a href="#problem" aria-label="Explore the microgrid fault problem"><ArrowDown size={16} /></a></div>
      </section>

      <section className="origin-problem" id="problem" aria-labelledby="origin-problem-title">
        <div className="origin-section-index" data-origin-reveal="text"><span>01 / WHY IT MATTERS</span><span>FAULTS HIDE IN LAYERS</span></div>
        <div className="origin-problem-grid">
          <div className="origin-problem-lead" data-origin-reveal="text"><p className="origin-kicker">RENEWABLE ENERGY / SYSTEM RELIABILITY</p><h2 id="origin-problem-title">A fault can be<br /><em>quiet—and costly.</em></h2><p>In a connected microgrid, an early symptom rarely tells the whole story.</p></div>
          <div className="origin-problem-points" data-origin-reveal="text">
            <article><span>01</span><div><h3>Clean energy needs reliability.</h3><p>Solar and battery systems depend on sensors, communication, controllers, and inverters working together.</p></div></article>
            <article><span>02</span><div><h3>Faults hide in layers.</h3><p>A sensor, network link, controller, setting, or inverter issue can produce similar symptoms from the outside.</p></div></article>
            <article><span>03</span><div><h3>Energy can be left undelivered.</h3><p>A fault may propagate through dependencies and reduce the energy that reaches demand in the simulation.</p></div></article>
          </div>
        </div>
        <div className="origin-problem-foot" data-origin-reveal="text"><span>THE QUESTION</span><strong>What changed, where might it have started, and what evidence points there?</strong><ArrowRight size={18} /></div>
      </section>

      <section className="origin-workflow-section" id="workflow" aria-labelledby="origin-workflow-title">
        <div className="origin-section-index" data-origin-reveal="text"><span>02 / FROM SIGNAL TO EXPLANATION</span><span>A SIX-STEP SIMULATION WORKFLOW</span></div>
        <div className="origin-workflow-intro" data-origin-reveal="text"><div><p className="origin-kicker">CONTROLLED SCENARIOS / EXPLAINABLE RESULTS</p><h2 id="origin-workflow-title">From a small deviation<br /><em>to a reasoned investigation.</em></h2></div><p>Faults are injected in software. Ground-truth labels stay separate from model input while the system observes telemetry and builds an evidence trail.</p></div>
        <div className="origin-workflow-rail" data-origin-reveal="visual">{[
          ['01', 'Simulate', 'Solar, battery, demand, and inverter evolve tick by tick.'],
          ['02', 'Inject', 'Choose a supported fault, seed, severity, and start time.'],
          ['03', 'Build features', 'Compare telemetry, residuals, message age, and requested output.'],
          ['04', 'Detect', 'Isolation Forest identifies behavior that differs from normal.'],
          ['05', 'Localize', 'Random Forest ranks candidate sources or abstains as Unknown.'],
          ['06', 'Trace + explain', 'Dependency reasoning connects likely source to observed evidence.'],
        ].map(([number, title, description]) => <article className="origin-workflow-item" key={number}><span className="origin-workflow-number">{number}</span><i className="origin-workflow-dot" /><div><h3>{title}</h3><p>{description}</p></div></article>)}</div>
        <div className="origin-workflow-note" data-origin-reveal="text"><CircleHelp size={15} /><p><strong>Detection and localization answer different questions.</strong> An anomaly flag says behavior is unusual. A source hypothesis ranks where it may originate; it does not prove the cause.</p></div>
      </section>

      <section className="origin-intelligence" id="capabilities" aria-labelledby="origin-intelligence-title">
        <div className="origin-section-index" data-origin-reveal="text"><span>03 / THE INTELLIGENCE</span><span>PHYSICS · AI · GRAPH REASONING</span></div>
        <div className="origin-intelligence-head" data-origin-reveal="text"><h2 id="origin-intelligence-title">More than an alert.<br /><em>A path to the evidence.</em></h2><p>Each method contributes a distinct piece. Together they turn a simulated deviation into an investigation a person can inspect.</p></div>
        <div className="origin-capability-list">{capabilities.map(([number, title, copy, detail, Icon]) => <article className="origin-capability" key={number} data-origin-reveal="text"><span className="origin-cap-number">{number}</span><span className="origin-cap-icon"><Icon size={19} strokeWidth={1.65} /></span><div className="origin-cap-copy"><span>{detail}</span><h3>{title}</h3><p>{copy}</p></div><span className="origin-cap-mark" aria-hidden="true"><ArrowRight size={17} /></span></article>)}</div>
        <div className="origin-model-note" data-origin-reveal="text"><span>IMPORTANT DISTINCTION</span><p>Isolation Forest detects abnormal behavior. Random Forest estimates a likely source. Graph paths show documented dependencies and evidence-compatible propagation—not verified causality.</p></div>
      </section>

      <section className="origin-evidence" id="evidence" aria-labelledby="origin-evidence-title">
        <div className="origin-section-index" data-origin-reveal="text"><span>05 / TRUST THE PROCESS</span><span>UNCERTAINTY STAYS VISIBLE</span></div>
        <div className="origin-evidence-grid">
          <article data-origin-reveal="text"><span className="origin-evidence-mark"><ShieldCheck size={19} /></span><p className="origin-kicker">EVIDENCE-BACKED INVESTIGATION</p><h2 id="origin-evidence-title">A useful answer<br /><em>shows its work.</em></h2><p>Incident views connect source candidates with observed residuals, timelines, and dependency paths. A suspected source is a hypothesis, and the system can return <code>Unknown</code> when the evidence is not enough.</p><Link className="origin-inline-link" to="/investigation" onClick={handleDestinationClick}>Explore an investigation <ArrowRight size={15} /></Link></article>
          <article data-origin-reveal="text"><span className="origin-evidence-mark"><ChartNoAxesCombined size={19} /></span><p className="origin-kicker">EVALUATION ON UNSEEN RUNS</p><h3>Test the model beyond its training runs.</h3><p>Evaluation uses complete held-out simulation runs, varied fault scenarios and severities, and normal runs to examine false alarms. No performance figures are shown here.</p><Link className="origin-inline-link" to="/evaluation" onClick={handleDestinationClick}>Explore model evaluation <ArrowRight size={15} /></Link></article>
        </div>
        <div className="origin-boundary-note" data-origin-reveal="text"><span>RESEARCH BOUNDARY</span><p>The current implementation is simulation-based. Predictions are likely sources, not proven causes. Real microgrid data and multi-fault incidents are future work.</p></div>
      </section>

      <section className="origin-architecture" id="architecture" aria-labelledby="origin-architecture-title">
        <div className="origin-section-index" data-origin-reveal="text"><span>06 / SYSTEM ARCHITECTURE</span><span>FROM SIMULATION TO DASHBOARD</span></div>
        <div className="origin-architecture-head" data-origin-reveal="text"><div><p className="origin-kicker">A TRACEABLE PIPELINE</p><h2 id="origin-architecture-title">Every stage leaves<br /><em>something to inspect.</em></h2></div><p>Ground truth remains separate from AI inputs. The local API connects the simulation, analysis, incident records, and dashboard views.</p></div>
        <div className="origin-architecture-flow" data-origin-reveal="visual" aria-label="System architecture stages">{['Microgrid simulator', 'Software fault injection', 'Telemetry + features', 'Anomaly detection', 'Source localization', 'Dependency graph', 'Evidence report', 'Dashboard'].map((stage, index) => <div className="origin-architecture-stage" key={stage}><span>{String(index + 1).padStart(2, '0')}</span><strong>{stage}</strong>{index < 7 && <ArrowRight size={14} aria-hidden="true" />}</div>)}</div>
        <div className="origin-stack" data-origin-reveal="visual" aria-label="Implementation technologies"><div><span>FRONTEND</span><p>React · Vite · TypeScript · Tailwind · Recharts · Cytoscape.js</p></div><div><span>BACKEND + API</span><p>Python · FastAPI · Pydantic · REST polling</p></div><div><span>MODELS + GRAPH</span><p>scikit-learn · NumPy · Pandas · NetworkX</p></div><div><span>RECORDS</span><p>SQLite incidents · CSV datasets</p></div></div>
        <p className="origin-architecture-caption">Corrections modify the software simulation only; no physical equipment is controlled.</p>
      </section>

      <section className="origin-final-cta" aria-labelledby="origin-cta-title">
        <div className="origin-cta-mark" data-origin-reveal="visual" aria-hidden="true"><i /><i /><i /></div>
        <div data-origin-reveal="text"><p className="origin-kicker">TRACEX GREENGRID / LOCAL SIMULATION</p><h2 id="origin-cta-title">Make every fault<br /><em>easier to understand.</em></h2><p>Explore a scenario, inspect a suspected fault, and follow the evidence through the simulated system.</p></div>
        <Link className="origin-button origin-button-light" to="/login" onClick={handleDestinationClick}>Sign in to workspace <ArrowRight size={16} /></Link>
        <span className="origin-cta-foot">FIND THE FAULT · SAVE THE ENERGY</span>
      </section>
    </main>

    <footer className="origin-home-footer">
      <Link className="origin-home-brand" to="/welcome" onClick={handleDestinationClick} aria-label="TraceX GreenGrid home"><span className="origin-brand-mark" aria-hidden="true"><i /><i /><i /></span><span>TraceX<small>GREEN GRID</small></span></Link>
      <p>Simulation-based fault localization.<br />Predictions are likely sources, not proven causes.</p>
      <nav aria-label="Account"><Link to="/login" onClick={handleDestinationClick}>Sign in</Link><Link to="/register" onClick={handleDestinationClick}>Create account</Link></nav>
      <span className="origin-footer-meta">RESEARCH / SIMULATION 01</span>
    </footer>
  </div>
}
