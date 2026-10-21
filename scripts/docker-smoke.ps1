# Builds and starts the Docker stack, then checks it end to end.
#   powershell -ExecutionPolicy Bypass -File scripts\docker-smoke.ps1
# Uses throwaway passwords in .env.smoke; tears everything down at the end
# (pass -Keep to leave it running on http://localhost:8080).
param([switch]$Keep)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

@"
DB_NAME=traytrack_smoke
DB_USER=traytrack
DB_PASSWORD=smoke-db-pass
DB_ROOT_PASSWORD=smoke-root-pass
GOOGLE_CLIENT_ID=smoke-test.apps.googleusercontent.com
PUBLIC_URL=http://localhost:8080
"@ | Set-Content -Encoding ascii .env.smoke

if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
$compose = @("compose", "--env-file", ".env.smoke", "-p", "traytrack-smoke")

function Check($name, [scriptblock]$test) {
  try { if (& $test) { Write-Host "PASS $name" -ForegroundColor Green; return } } catch { Write-Host "     $_" }
  Write-Host "FAIL $name" -ForegroundColor Red; $script:failed++
}
$failed = 0

docker @compose up -d --build
if ($LASTEXITCODE) { throw "docker compose up failed" }

# Wait for the API (migrations run on first start).
$deadline = (Get-Date).AddMinutes(3)
do {
  Start-Sleep 3
  try { $health = Invoke-RestMethod http://localhost:8080/api/health -TimeoutSec 5 } catch { $health = $null }
} until ($health.database -or (Get-Date) -gt $deadline)

Check "API healthy through nginx (/api/health)" { $health.status -eq "ok" -and $health.schema_version -ge 5 }
$page = Invoke-WebRequest http://localhost:8080/ -UseBasicParsing
Check "app served" { $page.StatusCode -eq 200 -and $page.Content -match "TrayTrack" }
Check "CSP on the app" { $page.Headers["Content-Security-Policy"] -match "script-src 'self'" }
Check "security headers on the app" { $page.Headers["X-Frame-Options"] -eq "DENY" -and $page.Headers["X-Content-Type-Options"] -eq "nosniff" }
$deep = Invoke-WebRequest http://localhost:8080/admin/alerts -UseBasicParsing
Check "client-side routes fall back to the app" { $deep.StatusCode -eq 200 -and $deep.Content -match 'id="root"' }
$asset = ([regex]'/assets/[^"]+\.js').Match($page.Content).Value
$js = Invoke-WebRequest "http://localhost:8080$asset" -UseBasicParsing
Check "assets cached and still carry security headers" { $js.Headers["Cache-Control"] -match "immutable" -and $js.Headers["X-Content-Type-Options"] -eq "nosniff" }
$colleges = Invoke-RestMethod http://localhost:8080/api/colleges
Check "public API via same origin" { $colleges.Count -ge 1 }
try {
  Invoke-WebRequest http://localhost:8080/api/staff/me -UseBasicParsing | Out-Null
  $staffStatus = 200
} catch { $staffStatus = [int]$_.Exception.Response.StatusCode }
Check "staff API needs sign-in" { $staffStatus -eq 401 }
$login = Invoke-WebRequest http://localhost:8080/api/staff/login -Method Post -ContentType "application/json" `
  -Body '{"email":"admin@traytrack.local","password":"changeme123"}' -UseBasicParsing -SessionVariable s
Check "staff sign-in sets an HttpOnly session cookie" { $login.Headers["Set-Cookie"] -match "tt_staff=.*HttpOnly" }
$me = Invoke-RestMethod http://localhost:8080/api/staff/me -WebSession $s
Check "cookie session works through nginx" { $me.role -eq "admin" }
Check "two backend workers running" { (docker @compose exec -T backend sh -c "ps aux | grep -c '[u]vicorn'") -ge 2 }
Check "backup script works in the container" { (docker @compose exec -T backend python scripts/backup.py --keep 2) -match "Database:" }

if ($Keep) { Write-Host "Left running on http://localhost:8080 (docker compose -p traytrack-smoke down -v to remove)" }
else { docker @compose down -v | Out-Null; Remove-Item .env.smoke }
if ($failed) { Write-Host "$failed check(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "All Docker checks passed" -ForegroundColor Green
