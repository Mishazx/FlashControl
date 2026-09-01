#requires -Version 5.1
<#
.SYNOPSIS
  Запуск FlashControl probe для synthetic USB профилей в Windows 11 VM.

.EXAMPLE
  .\run_probe_tests.ps1 -Profile baseline_mbr_fat32

.EXAMPLE
  .\run_probe_tests.ps1 -Watch -ShareDir Z:\flashcontrol

  Совместно с Proxmox:
    sudo ./run_vm_suite.sh suite
#>
[CmdletBinding()]
param(
    [string]$Profile,
    [string]$ResultsDir = (Join-Path $PSScriptRoot "results"),
    [string]$ProbePath = (Join-Path (Split-Path $PSScriptRoot -Parent) "FlashControlAgent\main.py"),
    [string]$ShareDir,
    [int]$PollSeconds = 2,
    [switch]$Watch,
    [switch]$RepeatTwice
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
    Write-Host "[flashgen] $Message"
}

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-PythonCommand {
    foreach ($candidate in @("python", "py")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            if ($candidate -eq "py") {
                return @("py", "-3")
            }
            return @($candidate)
        }
    }
    throw "Python not found in PATH"
}

function Invoke-Probe {
    if (-not (Test-Path -LiteralPath $ProbePath)) {
        throw "Probe not found: $ProbePath"
    }

    $python = Get-PythonCommand
    $output = & $python[0] @($python[1..($python.Length - 1)]) $ProbePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Probe failed: $output"
    }
    return ($output -join [Environment]::NewLine)
}

function Get-ScanDocument([string]$JsonText) {
    return $JsonText | ConvertFrom-Json
}

function Get-UsbObservationCount($Document) {
    $count = 0
    foreach ($observation in $Document.observations) {
        $busType = $observation.device.storage.bus_type
        $hasUsb = $null -ne $observation.device.pnp.usb
        if ($busType -eq 7 -or $hasUsb) {
            $count++
        }
    }
    if ($count -eq 0) {
        return @($Document.observations).Count
    }
    return $count
}

function Get-DeviceSignature($Document) {
    if (-not $Document.observations -or $Document.observations.Count -eq 0) {
        return $null
    }
    $device = $Document.observations[0].device
    return [string]::Join("|", @(
        $device.hardware_stable_sha256,
        $device.media_identity_sha256,
        $device.media_state_sha256,
        $device.observation_sha256
    ))
}

function Save-Result([string]$Name, [string]$JsonText) {
    Ensure-Directory $ResultsDir
    $path = Join-Path $ResultsDir ($Name + ".json")
    [System.IO.File]::WriteAllText($path, $JsonText, [System.Text.UTF8Encoding]::new($false))
    Write-Info "saved $path"
    return $path
}

function Read-CurrentProfile {
    param([string]$BaseDir)
    if (-not $BaseDir) { return $null }
    $marker = Join-Path $BaseDir "current_profile.txt"
    if (-not (Test-Path -LiteralPath $marker)) { return $null }
    return (Get-Content -LiteralPath $marker -Raw).Trim()
}

function Run-SingleProfile {
    param(
        [string]$Name,
        [switch]$DoRepeat
    )

    Write-Info "scan profile=$Name"
    if ($DoRepeat) {
        $first = Invoke-Probe
        Start-Sleep -Seconds 2
        $second = Invoke-Probe
        $docFirst = Get-ScanDocument $first
        $docSecond = Get-ScanDocument $second
        $merged = [ordered]@{
            schema_version = $docFirst.schema_version
            probe_version = $docFirst.probe_version
            scan_id = [guid]::NewGuid().ToString()
            generated_at_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
            repeatability = $true
            observations = @($docFirst.observations + $docSecond.observations)
            scan_capabilities = $docFirst.scan_capabilities
            scan_errors = @($docFirst.scan_errors + $docSecond.scan_errors)
        }
        $json = $merged | ConvertTo-Json -Depth 100
        Save-Result $Name $json | Out-Null
        return
    }

    $json = Invoke-Probe
    Save-Result $Name $json | Out-Null
}

Ensure-Directory $ResultsDir

if ($Watch) {
    Write-Info "watch mode; results -> $ResultsDir"
    if ($ShareDir) {
        Write-Info "profile marker dir: $ShareDir"
    }
    $seen = @{}
    while ($true) {
        $activeProfile = if ($Profile) { $Profile } else { Read-CurrentProfile $ShareDir }
        try {
            $json = Invoke-Probe
            $document = Get-ScanDocument $json
            $signature = Get-DeviceSignature $document
            $usbCount = Get-UsbObservationCount $document
            if ($usbCount -eq 0) {
                Start-Sleep -Seconds $PollSeconds
                continue
            }
            if (-not $activeProfile) {
                $activeProfile = "auto_" + (Get-Date -Format "yyyyMMdd_HHmmss")
            }
            $key = "$activeProfile::$signature"
            if ($seen.ContainsKey($key)) {
                Start-Sleep -Seconds $PollSeconds
                continue
            }
            $seen[$key] = $true
            Save-Result $activeProfile $json | Out-Null
        }
        catch {
            Write-Info "probe error: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

if (-not $Profile) {
    throw "Specify -Profile name or use -Watch"
}

Run-SingleProfile -Name $Profile -DoRepeat:$RepeatTwice
Write-Info "done"
