# 本机启用 GitHub 加速器时,让容器也能走通 GitHub。
#
# 用法:  pwsh -File scripts/enable-github-accelerator.ps1
#
# 做两件事:
#   1. 从 Windows 证书库导出加速器根证书到 backend/certs/extra-ca/
#   2. 用叠加 compose 文件重建并启动 backend
#
# ⚠️ 第 1 步等于让容器信任一个本地中间人根证书。只有在直连 GitHub 不通时才用。
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$certDir = 'backend\certs\extra-ca'
New-Item -ItemType Directory -Path $certDir -Force | Out-Null

$certs = Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
         Where-Object { $_.Subject -match 'SteamTools|Watt|Accelerator' } |
         Sort-Object Subject -Unique

if (-not $certs) {
  Write-Host "未在证书库找到加速器根证书。" -ForegroundColor Yellow
  Write-Host "如果你没在用 GitHub 加速器,直接 docker compose up -d 即可(直连 GitHub)。"
  exit 1
}

foreach ($cert in $certs) {
  $b64 = [Convert]::ToBase64String($cert.RawData)
  $chunks = for ($i = 0; $i -lt $b64.Length; $i += 64) { $b64.Substring($i, [Math]::Min(64, $b64.Length - $i)) }
  $pem = "-----BEGIN CERTIFICATE-----`n" + ($chunks -join "`n") + "`n-----END CERTIFICATE-----`n"
  $name = ($cert.Subject -replace '[^A-Za-z0-9]+', '-').Trim('-') + '.pem'
  [System.IO.File]::WriteAllText((Join-Path $certDir $name), $pem, (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "已导出: $name  ($($cert.Subject))" -ForegroundColor Green
}

Write-Host "`n重建并启动 backend(叠加加速器配置)..." -ForegroundColor Cyan
docker compose -f docker-compose.yml -f docker-compose.accelerator.yml up -d --build backend

Write-Host "`n完成。验证:" -ForegroundColor Green
Write-Host "  docker compose logs -f backend"
Write-Host "  curl http://localhost:8000/api/repos"