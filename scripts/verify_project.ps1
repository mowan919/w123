# VCTN verification helper
# Run from project root.

$ErrorActionPreference = "Stop"

Write-Host "=== VCTN Verification ==="

if (Test-Path "pyproject.toml") {
    Write-Host "[OK] pyproject.toml"
} else {
    Write-Host "[WARN] pyproject.toml not found"
}

if (Test-Path "alembic.ini") {
    Write-Host "[OK] alembic.ini"
} else {
    Write-Host "[WARN] alembic.ini not found"
}

if (Test-Path "tests") {
    Write-Host "[OK] tests/"
} else {
    Write-Host "[WARN] tests/ not found"
}

Write-Host ""
Write-Host "Run your project's configured test/lint/type-check commands."
Write-Host "Do not treat this script alone as acceptance."
