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
# Smoke-only settings layered over docker-compose.yml.
@"
services:
  backend:
    environment:
      METRICS_TOKEN: smoke-metrics-token
"@ | Set-Content -Encoding ascii docker-compose.smoke.yml
$compose = @("compose", "--env-file", ".env.smoke", "-f", "docker-compose.yml", "-f", "docker-compose.smoke.yml", "-p", "traytrack-smoke")

function Check($name, [scriptblock]$test) {
  try { if (& $test) { Write-Host "PASS $name" -ForegroundColor Green; return } } catch { Write-Host "     $_" }
  Write-Host "FAIL $name" -ForegroundColor Red; $script:failed++
}
$failed = 0

try {
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
# Strict styles: nginx stamps a fresh nonce into the page and the header.
$nonce = ([regex]'name="csp-nonce" content="([0-9a-f]{32})"').Match($page.Content).Groups[1].Value
Check "CSP nonce in page matches header" { $nonce -and $page.Headers["Content-Security-Policy"] -match "'nonce-$nonce'" -and $page.Headers["Content-Security-Policy"] -notmatch "style-src-elem[^;]*unsafe-inline" }
$again = Invoke-WebRequest http://localhost:8080/ -UseBasicParsing
Check "CSP nonce changes per request" { $again.Content -notmatch $nonce }
Check "security headers on the app" { $page.Headers["X-Frame-Options"] -eq "DENY" -and $page.Headers["X-Content-Type-Options"] -eq "nosniff" }
$deep = Invoke-WebRequest http://localhost:8080/admin/alerts -UseBasicParsing
Check "client-side routes fall back to the app" { $deep.StatusCode -eq 200 -and $deep.Content -match 'id="root"' }
$asset = ([regex]'/assets/[^"]+\.js').Match($page.Content).Value
$js = Invoke-WebRequest "http://localhost:8080$asset" -UseBasicParsing
Check "assets cached and still carry security headers" { $js.Headers["Cache-Control"] -match "immutable" -and $js.Headers["X-Content-Type-Options"] -eq "nosniff" }
Check "public API via same origin" { (Invoke-RestMethod http://localhost:8080/api/colleges).Count -ge 1 }
try {
  Invoke-WebRequest http://localhost:8080/api/staff/me -UseBasicParsing | Out-Null
  $staffStatus = 200
} catch { $staffStatus = [int]$_.Exception.Response.StatusCode }
Check "staff API needs sign-in" { $staffStatus -eq 401 }
$login = $null
try {
  $login = Invoke-WebRequest http://localhost:8080/api/staff/login -Method Post -ContentType "application/json" `
    -Body '{"email":"admin@traytrack.local","password":"changeme123"}' -UseBasicParsing -SessionVariable s
} catch { Write-Host "     login: $_" }
Check "staff sign-in sets an HttpOnly session cookie" { $login.Headers["Set-Cookie"] -match "tt_staff=.*HttpOnly" }
Check "cookie session works through nginx" { (Invoke-RestMethod http://localhost:8080/api/staff/me -WebSession $s).role -eq "admin" }
# The slim image has no `ps`; count python processes via /proc (master +
# 2 workers + this checker = 4).
$countPy = "import os; print(sum(1 for p in os.listdir('/proc') if p.isdigit() and b'python' in open('/proc/'+p+'/cmdline','rb').read()))"
Check "two backend workers running" { [int](docker @compose exec -T backend python -c $countPy) -ge 4 }
try { Invoke-WebRequest http://localhost:8080/api/metrics -UseBasicParsing | Out-Null; $metricsAnon = 200 }
catch { $metricsAnon = [int]$_.Exception.Response.StatusCode }
$m = Invoke-WebRequest http://localhost:8080/api/metrics -Headers @{ Authorization = "Bearer smoke-metrics-token" } -UseBasicParsing
Check "metrics need the token, then report" { $metricsAnon -eq 401 -and $m.Content -match "traytrack_database_up 1" -and $m.Content -match "traytrack_http_requests_total" }

# Restore drill: back up, lose a table, restore, and check nothing is missing.
$count = "import db; print(db.fetch_one('SELECT (SELECT COUNT(*) FROM staff_users) + (SELECT COUNT(*) FROM activity_log) AS n')['n'])"
$before = [int](docker @compose exec -T backend python -c $count)
Check "backup script works in the container" { (docker @compose exec -T backend python scripts/backup.py --keep 2) -match "Database:.*verified" }
docker @compose exec -T backend python -c "import db; db.execute('DROP TABLE activity_log')"
$ErrorActionPreference = "Continue"   # the refusal goes to stderr, as it should
$refusal = docker @compose exec -T backend python scripts/restore.py 2>&1 | Out-String
$refusedCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
Check "restore refuses a database that has data" { $refusedCode -ne 0 -and $refusal -match "use --force" }
$restored = docker @compose exec -T backend python scripts/restore.py --force
Check "restore drill brings the data back" { $restored -match "Restored" -and [int](docker @compose exec -T backend python -c $count) -eq $before }
Check "app healthy after restore" { (Invoke-RestMethod http://localhost:8080/api/health).status -eq "ok" }

} catch {
  Write-Host "ERROR $_" -ForegroundColor Red; $failed++
  docker @compose logs --tail 30 backend
} finally {
  # docker writes normal progress to stderr; don't let that count as an error.
  $ErrorActionPreference = "Continue"
  if ($Keep) { Write-Host "Left running on http://localhost:8080 (docker compose -p traytrack-smoke down -v to remove)" }
  else { docker @compose down -v 2>&1 | Out-Null; Remove-Item .env.smoke, docker-compose.smoke.yml -ErrorAction SilentlyContinue }
}
if ($failed) { Write-Host "$failed check(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "All Docker checks passed" -ForegroundColor Green
