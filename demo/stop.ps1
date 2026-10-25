<#
.SYNOPSIS
  Stop the Axolotl demo build's backend and frontend. The local MongoDB is left running
  (docker stop axolotl-atlas-local stops it; its data is kept).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File demo\stop.ps1
#>
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

foreach ($port in $BackendPort, $FrontendPort) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) { Write-Host "port ${port}: nothing running"; continue }
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Write-Host "port ${port}: stopped"
}
