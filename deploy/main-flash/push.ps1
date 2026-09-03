param(
    [string]$HostName = "main-flash",
    [switch]$BootstrapPilot
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stamp = [DateTime]::UtcNow.ToString("yyyyMMddHHmmss")
$archive = Join-Path ([System.IO.Path]::GetTempPath()) "flashcontrol-$stamp.tar"
$remoteArchive = "/tmp/flashcontrol-$stamp.tar"
$remoteRelease = "/opt/flashcontrol/releases/$stamp"
$temporaryEnvironment = $null
$machineToken = $null
$adminPassword = $null

function New-RandomUrlSafeSecret([int]$Bytes = 32) {
    $buffer = [byte[]]::new($Bytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Send-FileThroughSsh([string]$LocalPath, [string]$RemotePath) {
    $sshExecutable = (Get-Command ssh -ErrorAction Stop).Source
    $upload = Start-Process -FilePath $sshExecutable `
        -ArgumentList @($HostName, "cat > '$RemotePath'") `
        -RedirectStandardInput $LocalPath `
        -NoNewWindow -Wait -PassThru
    if ($upload.ExitCode -ne 0) { throw "SSH upload failed: $LocalPath" }
}

try {
    if ($BootstrapPilot) {
        ssh $HostName "test ! -f /opt/flashcontrol/shared/flashcontrol.env"
        if ($LASTEXITCODE -ne 0) {
            throw "server environment already exists; BootstrapPilot is only for the first deployment"
        }
        $dbPassword = New-RandomUrlSafeSecret
        $machineToken = New-RandomUrlSafeSecret 48
        $adminPassword = New-RandomUrlSafeSecret 24
        $temporaryEnvironment = Join-Path ([System.IO.Path]::GetTempPath()) "flashcontrol-env-$stamp"
        @(
            "POSTGRES_DB=flashcontrol"
            "POSTGRES_USER=flashcontrol"
            "POSTGRES_PASSWORD=$dbPassword"
            "FLASHCONTROL_ENVIRONMENT=development"
            "FLASHCONTROL_AUTH_PROVIDER=local"
            "FLASHCONTROL_MACHINE_AUTH_MODE=token"
            "FLASHCONTROL_DEV_MACHINE_TOKEN=$machineToken"
            "FLASHCONTROL_LOG_LEVEL=INFO"
        ) | Set-Content -LiteralPath $temporaryEnvironment -Encoding utf8NoBOM

        Send-FileThroughSsh $temporaryEnvironment "/tmp/flashcontrol.env"
        ssh $HostName "sudo mkdir -p /opt/flashcontrol/shared/backups && sudo install -m 600 -o user -g user /tmp/flashcontrol.env /opt/flashcontrol/shared/flashcontrol.env && rm -f /tmp/flashcontrol.env"
        if ($LASTEXITCODE -ne 0) { throw "pilot environment installation failed" }
    }

    tar -cf $archive `
        --exclude FlashControlPIBServer/.venv `
        --exclude FlashControlPIBServer/tests `
        --exclude FlashControlPIBServer/__pycache__ `
        --exclude FlashControlPIBServer/flashcontrol-dev.db `
        -C $repoRoot FlashControlPIBServer deploy/main-flash
    if ($LASTEXITCODE -ne 0) { throw "tar failed" }

    Send-FileThroughSsh $archive $remoteArchive

    ssh $HostName "sudo mkdir -p '$remoteRelease' /opt/flashcontrol/shared/backups && sudo tar -xf '$remoteArchive' -C '$remoteRelease' && sudo chown -R user:user /opt/flashcontrol && rm -f '$remoteArchive' && bash '$remoteRelease/deploy/main-flash/deploy.sh' '$remoteRelease' '$stamp'"
    if ($LASTEXITCODE -ne 0) { throw "remote deployment failed" }

    if ($BootstrapPilot) {
        "$adminPassword`n$adminPassword`n" | ssh $HostName "sudo docker exec -i flashcontrol-main python -m app.manage_user create --username admin --role admin"
        if ($LASTEXITCODE -ne 0) { throw "admin account creation failed" }
        Write-Warning "Pilot uses local authentication and plain HTTP."
        Write-Host "Admin username: admin"
        Write-Host "Admin password: $adminPassword"
        Write-Host "Machine token: $machineToken"
    }

    Write-Host "FlashControl $stamp deployed to $HostName"
}
finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    if ($temporaryEnvironment) {
        Remove-Item -LiteralPath $temporaryEnvironment -Force -ErrorAction SilentlyContinue
    }
}
