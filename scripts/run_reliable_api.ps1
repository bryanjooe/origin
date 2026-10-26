# Opt-in activation of the evaluated Stage B revision. Original artifacts remain intact.
$projectRoot = Split-Path -Parent $PSScriptRoot
$decision = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'outputs/step5/candidates/promotion_decision.json') | ConvertFrom-Json
if (-not $decision.promotable) { throw 'The candidate did not pass the predeclared evaluation guards.' }
$manifest = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'outputs/step5/promoted.json') | ConvertFrom-Json
$artifactPath = Join-Path $projectRoot 'outputs/step5/candidates/regular/selected.joblib'
if (-not $manifest.promotable -or (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash -ne $manifest.sha256) { throw 'Candidate artifact does not match the validated promotion manifest.' }
$previousModel = $env:ORIGIN_SECURITY_MODEL
$previousResults = $env:ORIGIN_SECURITY_RESULTS
Push-Location $projectRoot
try {
    $env:ORIGIN_SECURITY_MODEL = Join-Path $projectRoot 'outputs/step5/candidates/regular/selected.joblib'
    $env:ORIGIN_SECURITY_RESULTS = Join-Path $projectRoot 'outputs/step5/candidates/regular'
    & (Join-Path $projectRoot '.venv/Scripts/python.exe') -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
} finally {
    $env:ORIGIN_SECURITY_MODEL = $previousModel
    $env:ORIGIN_SECURITY_RESULTS = $previousResults
    Pop-Location
}
