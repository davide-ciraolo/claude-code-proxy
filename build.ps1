# Build script for Claude Code Proxy
# Requires: Python 3.11+, PyInstaller (pip install pyinstaller)

$ErrorActionPreference = "Stop"

Write-Host "Building claude-proxy.exe..." -ForegroundColor Cyan

# Check PyInstaller is available
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Clean previous build artifacts
if (Test-Path "dist\claude-proxy.exe") { Remove-Item "dist\claude-proxy.exe" -Force }
if (Test-Path "build")                  { Remove-Item "build" -Recurse -Force }
if (Test-Path "claude-proxy.spec")      { Remove-Item "claude-proxy.spec" -Force }

# Build
pyinstaller --onefile --windowed --name "claude-proxy" proxy.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Build complete: dist\claude-proxy.exe" -ForegroundColor Green
