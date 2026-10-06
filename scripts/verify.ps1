# DevFlow AI Demo 端到端验收(Windows 原生入口)。
#
# 用法:  pwsh -File scripts/verify.ps1
# 这是交付的唯一权威验收入口:容器健康 + 后端单测 + 前端单测 + 全链路 HTTP 验收。
$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')

$script:pass = 0
$script:fail = 0

function Mark([int]$code, [string]$name) {
  if ($code -eq 0) { Write-Host "  [PASS] $name"; $script:pass++ }
  else { Write-Host "  [FAIL] $name" -ForegroundColor Red; $script:fail++ }
}

Write-Host "`n==== 1. 容器健康 ===="
$ps = docker compose ps --format '{{.Service}}|{{.State}}'
foreach ($svc in 'postgres','etcd','minio','milvus','backend','frontend') {
  $line = $ps | Select-String "^$svc\|" | Select-Object -First 1
  if ($line -and ($line.ToString().Split('|')[1] -eq 'running')) { Mark 0 "$svc running" } else { Mark 1 "$svc 未运行" }
}

Write-Host "`n==== 2. 后端单测(全 Mock,不联网) ===="
docker compose exec -T backend pytest -q
Mark $LASTEXITCODE "pytest"

Write-Host "`n==== 3. 前端单测 ===="
docker compose exec -T frontend npm test --silent
Mark $LASTEXITCODE "vitest"

Write-Host "`n==== 4. 全链路 HTTP 验收 ===="
docker compose cp scripts/verify_api.py backend:/app/_verify_api.py | Out-Null
docker compose exec -T backend python /app/_verify_api.py
Mark $LASTEXITCODE "verify_api"

Write-Host "`n==== 验收汇总: PASS=$script:pass FAIL=$script:fail ===="
if ($script:fail -ne 0) { exit 1 }