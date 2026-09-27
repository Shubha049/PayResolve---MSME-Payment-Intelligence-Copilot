# PayResolve AI — Phase 4 Risk Model Setup Script
# Generates synthetic training data and trains the initial ML model

Write-Host "================================" -ForegroundColor Cyan
Write-Host "PayResolve Risk Model Setup" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Stop"

# Check if we're in the backend directory
if (-not (Test-Path "scripts/generate_synthetic_data.py")) {
    Write-Host "Error: Must run from backend/ directory" -ForegroundColor Red
    exit 1
}

# Step 1: Generate synthetic training data
Write-Host "[1/3] Generating synthetic training data..." -ForegroundColor Yellow
python scripts/generate_synthetic_data.py --rows 500 --seed 42

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to generate training data" -ForegroundColor Red
    exit 1
}

# Step 2: Train the model
Write-Host ""
Write-Host "[2/3] Training risk model (this may take a minute)..." -ForegroundColor Yellow
python scripts/train_risk_model.py --version synthetic_v1 --test-size 0.2

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to train model" -ForegroundColor Red
    exit 1
}

# Step 3: Verify artifacts
Write-Host ""
Write-Host "[3/3] Verifying model artifacts..." -ForegroundColor Yellow

$artifacts = @(
    "models/artifacts/risk_model.pkl",
    "models/artifacts/risk_scaler.pkl",
    "models/artifacts/risk_model_meta.json"
)

$allPresent = $true
foreach ($artifact in $artifacts) {
    if (Test-Path $artifact) {
        Write-Host "  ✓ $artifact" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $artifact (missing)" -ForegroundColor Red
        $allPresent = $false
    }
}

Write-Host ""
if ($allPresent) {
    Write-Host "================================" -ForegroundColor Green
    Write-Host "✅ Setup complete!" -ForegroundColor Green
    Write-Host "================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Risk scoring is ready. The ML model will be used automatically" -ForegroundColor White
    Write-Host "for invoices with sufficient payment history (≥5 prior invoices)." -ForegroundColor White
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Start the backend: uvicorn app.main:app --reload" -ForegroundColor White
    Write-Host "  2. Run tests: pytest tests/test_risk.py -v" -ForegroundColor White
    Write-Host "  3. Check model metrics: cat models/artifacts/risk_model_meta.json" -ForegroundColor White
} else {
    Write-Host "Setup incomplete - some artifacts missing" -ForegroundColor Red
    exit 1
}
