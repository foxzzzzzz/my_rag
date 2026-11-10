param([string]$Config = 'config/web.json', [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$configPath = (Resolve-Path -LiteralPath $Config).Path
$c = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($c.host -notin @('127.0.0.1','localhost')) { throw 'Only loopback hosts are allowed.' }
$launcher = Get-Content -LiteralPath (Join-Path $root 'config/web-launcher.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$startupTimeout = [int]$launcher.startup_timeout_ms
$interval = [int]$launcher.health_interval_ms
$probeTimeout = [int]$launcher.health_probe_timeout_seconds
$cleanupTimeout = [int]$launcher.cleanup_timeout_ms
if ($startupTimeout -lt 1 -or $interval -lt 1 -or $probeTimeout -lt 1 -or $cleanupTimeout -lt 1) { throw 'Invalid launcher health settings.' }
$port = [int]$c.port
if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid port.' }
$uriHost = $c.host
$uri = "http://${uriHost}:${port}/healthz"
$logDir = Join-Path $root 'tmp/web-server'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    try { $response = Invoke-WebRequest -Uri $uri -TimeoutSec 2 -UseBasicParsing; $body = $response.Content | ConvertFrom-Json } catch { throw "Port $port is occupied by PID $($listener.OwningProcess); unable to verify application." }
    if ($proc.CommandLine -notmatch '(?i)(^|\s)tools\.web_server(\s|$)' -or !($body.ok -is [bool]) -or $body.ok -ne $true -or $response.StatusCode -ne 200) { throw "Port $port is occupied by another service (PID $($listener.OwningProcess))." }
    $configMatch = [regex]::Match($proc.CommandLine, '(?i)(?:^|\s)--config\s+(?:"([^"]+)"|(\S+))(?=\s|$)')
    $existingConfig = if ($configMatch.Groups[1].Success) { $configMatch.Groups[1].Value } else { $configMatch.Groups[2].Value }
    if (!$configMatch.Success -or ![IO.Path]::IsPathRooted($existingConfig) -or ![string]::Equals([IO.Path]::GetFullPath($existingConfig), $configPath, [StringComparison]::OrdinalIgnoreCase) -or !$existingConfig.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Port $port has a PersonalKB process with a different or unverifiable project/configuration (PID $($listener.OwningProcess))."
    }
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($owner.OwningProcess -ne $listener.OwningProcess) { throw "Port $port changed listener during verification. Retry startup." }
    Write-Output "Existing PersonalKB service: PID $($listener.OwningProcess), $uri"
    exit 0
}
$useCache = $false
if (!$PythonPath) {
    $venv = Join-Path $root '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $venv) { $PythonPath = $venv } else { $PythonPath = (Get-Command python -ErrorAction Stop).Source; $useCache = $true }
}
$deps = Join-Path $root 'tmp/web-deps'
$oldPath = $env:PYTHONPATH
$p = $null
$started = $false
try {
    if ($useCache -and (Test-Path (Join-Path $deps 'fastapi')) -and (Test-Path (Join-Path $deps 'uvicorn'))) { $env:PYTHONPATH = if ($oldPath) { "$deps;$oldPath" } else { $deps } }
    & $PythonPath -c 'import fastapi, uvicorn' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Python cannot import FastAPI and Uvicorn; use an existing compatible environment.' }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $out = Join-Path $logDir "stdout-$stamp.log"
    $err = Join-Path $logDir "stderr-$stamp.log"
    $quotedConfig = '"' + $configPath.Replace('"','\"') + '"'
    $p = Start-Process -FilePath $PythonPath -ArgumentList @('-m','tools.web_server','--config',$quotedConfig) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (!$p.HasExited) {
        $remaining = $startupTimeout - $clock.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        Start-Sleep -Milliseconds ([Math]::Min($interval, $remaining))
        $remaining = $startupTimeout - $clock.ElapsedMilliseconds
        if ($remaining -le 0 -or $p.HasExited) { break }
        try {
            $timeout = [Math]::Min($probeTimeout, [Math]::Ceiling($remaining / 1000))
            $r = Invoke-WebRequest -Uri $uri -TimeoutSec $timeout -UseBasicParsing
            $b = $r.Content | ConvertFrom-Json
            $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($r.StatusCode -eq 200 -and ($b.ok -is [bool]) -and $b.ok -eq $true -and $owner.OwningProcess -eq $p.Id -and !$p.HasExited) {
                Set-Content -LiteralPath (Join-Path $logDir 'server.pid') -Value $p.Id
                $started = $true
                Write-Output "Started PersonalKB: PID $($p.Id), $uri"
                exit 0
            }
        } catch { }
    }
    throw "Server did not become healthy. Logs: $out ; $err"
} finally {
    if ($p -and !$started) {
        try {
            if (!$p.HasExited) {
                $p.Kill()
                if (!$p.WaitForExit($cleanupTimeout)) { Write-Warning "Could not stop started PID $($p.Id); logs: $out ; $err" }
            }
        } catch {
            Write-Warning "Could not clean up started PID $($p.Id): $_; logs: $out ; $err"
        }
    }
    $env:PYTHONPATH = $oldPath
}


