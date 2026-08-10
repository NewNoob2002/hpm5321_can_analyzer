param(
    [string]$OutputDirectory = "docs/evidence/phase1/windows-current",
    [string]$FirmwareManifest = "build/hpm5321-flash-release/build-manifest.json",
    [string]$Vid = "34B7",
    [string]$Pid = "1236",
    [switch]$ExerciseDisconnectRecovery,
    [int]$DisconnectBytes = 1073741824,
    [int]$RecoveryBytes = 1048576,
    [int]$ReenumerationTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$output = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Force -Path $output | Out-Null
$log = Join-Path $output "phase1b-windows-collector.txt"

function Resolve-RepoFile([string]$Path, [string]$Description) {
    $candidate = if ([IO.Path]::IsPathRooted($Path)) {
        $Path
    } else {
        Join-Path $root $Path
    }
    if (-not (Test-Path -PathType Leaf $candidate)) {
        throw "$Description is missing: $candidate"
    }
    return (Resolve-Path $candidate).Path
}

function Assert-HexDigest([string]$Value, [int]$Digits, [string]$Description) {
    if ($Value -notmatch "^[0-9a-fA-F]{$Digits}$") {
        throw "$Description is not a $Digits-digit hexadecimal digest"
    }
}

function Read-FirmwareProvenance([string]$ManifestArgument) {
    $manifestPath = Resolve-RepoFile $ManifestArgument "Firmware manifest"
    $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
    if ($manifest.schema -ne 1) { throw "Firmware manifest schema must be 1" }
    Assert-HexDigest $manifest.source_revision 40 "Firmware source revision"
    Assert-HexDigest $manifest.sdk_commit 40 "Firmware SDK commit"
    if ($manifest.source_dirty -isnot [bool] -or $manifest.source_dirty) {
        throw "Firmware manifest must record source_dirty=false"
    }
    $artifactDirectory = Join-Path (Split-Path $manifestPath) "output"
    $artifacts = @()
    foreach ($name in @("demo.elf", "demo.bin")) {
        $entry = $manifest.artifacts.$name
        if ($null -eq $entry) { throw "Firmware manifest artifact is missing: $name" }
        Assert-HexDigest $entry.sha256 64 "Firmware artifact $name SHA-256"
        $artifactPath = Resolve-RepoFile (Join-Path $artifactDirectory $name) "Firmware artifact $name"
        $measuredHash = (Get-FileHash -Algorithm SHA256 $artifactPath).Hash.ToLowerInvariant()
        $measuredSize = (Get-Item $artifactPath).Length
        if ($measuredHash -ne $entry.sha256.ToLowerInvariant() -or
            $measuredSize -ne [long]$entry.size) {
            throw "Firmware artifact does not match manifest: $name"
        }
        $artifacts += [PSCustomObject]@{
            Name = $name
            Path = $artifactPath
            Size = $measuredSize
            Sha256 = $measuredHash
            Verified = $true
        }
    }
    return [PSCustomObject]@{
        Path = $manifestPath
        Sha256 = (Get-FileHash -Algorithm SHA256 $manifestPath).Hash.ToLowerInvariant()
        Preset = $manifest.preset
        SourceRevision = $manifest.source_revision.ToLowerInvariant()
        SourceDirty = [bool]$manifest.source_dirty
        SdkCommit = $manifest.sdk_commit.ToLowerInvariant()
        Compiler = $manifest.compiler
        BuildOptions = $manifest.build_options
        Artifacts = $artifacts
        AssociationMethod = "operator-selected manifest with verified host build artifacts"
        DeviceAttested = $false
        Boundary = "the device does not expose an on-device build identifier"
    }
}

function Record([string]$Title, [scriptblock]$Command) {
    "`n## $Title" | Tee-Object -FilePath $log -Append
    $global:LASTEXITCODE = 0
    & $Command 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "$Title failed with exit code $LASTEXITCODE"
    }
}

function Get-PnpPropertyValue([string]$InstanceId, [string]$KeyName) {
    $property = Get-PnpDeviceProperty `
        -InstanceId $InstanceId `
        -KeyName $KeyName `
        -ErrorAction SilentlyContinue
    if ($null -eq $property) { return $null }
    return $property.Data
}

function Get-MatchingPnpDevices {
    return @(
        Get-PnpDevice -PresentOnly |
            Where-Object { $_.InstanceId -match "VID_$Vid&PID_$Pid" }
    )
}

function Wait-ForDevicePresence([bool]$Present, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $isPresent = (Get-MatchingPnpDevices).Count -gt 0
        if ($isPresent -eq $Present) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    $state = if ($Present) { "re-enumeration" } else { "disconnect" }
    throw "Timed out waiting for device $state"
}

Set-Content -Path $log -Value "Phase 1B Windows evidence collector"
$firmware = Read-FirmwareProvenance $FirmwareManifest
$computer = Get-ComputerInfo |
    Select-Object WindowsProductName, WindowsVersion, OsBuildNumber
Record "Windows" { $computer | Format-List }
Record "Firmware provenance" { $firmware | ConvertTo-Json -Depth 8 }
Record "Rust" { rustc +1.97.1 --version --verbose }
Record "Cargo" { cargo +1.97.1 --version --verbose }
Record "Visual Studio" {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio/Installer/vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "vswhere.exe is missing" }
    & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json
}
$devices = Get-MatchingPnpDevices
if (-not $devices) { throw "VID_$Vid&PID_$Pid is not present" }
$interfaceZero = @($devices | Where-Object { $_.InstanceId -match "&MI_00" })
$bindingCandidates = if ($interfaceZero.Count -gt 0) { $interfaceZero } else { $devices }
$bindings = @(
    foreach ($device in $bindingCandidates) {
        [PSCustomObject]@{
            Status = $device.Status
            Class = $device.Class
            FriendlyName = $device.FriendlyName
            InstanceId = $device.InstanceId
            Service = Get-PnpPropertyValue $device.InstanceId "DEVPKEY_Device_Service"
            DriverProvider = Get-PnpPropertyValue $device.InstanceId "DEVPKEY_Device_DriverProvider"
            DriverVersion = Get-PnpPropertyValue $device.InstanceId "DEVPKEY_Device_DriverVersion"
            DriverInfPath = Get-PnpPropertyValue $device.InstanceId "DEVPKEY_Device_DriverInfPath"
        }
    }
)
Record "PnP WinUSB binding" { $bindings | ConvertTo-Json -Depth 4 }
$winUsbBindings = @($bindings | Where-Object { $_.Service -ieq "WinUSB" })
if ($winUsbBindings.Count -eq 0) {
    throw "Vendor interface 0 is not bound to the WinUSB service"
}
Record "Format" { cargo +1.97.1 fmt --manifest-path "$root/host/Cargo.toml" --all --check }
Record "Build" { cargo +1.97.1 build --manifest-path "$root/host/Cargo.toml" --workspace --release --locked }
Record "Test" { cargo +1.97.1 test --manifest-path "$root/host/Cargo.toml" --workspace --release --locked }
Record "Clippy" { cargo +1.97.1 clippy --manifest-path "$root/host/Cargo.toml" --workspace --all-targets --release --locked -- -D warnings }

$exe = Join-Path $root "host/target/release/hpm-usb-smoke.exe"
$lock = Join-Path $root "host/Cargo.lock"
if (-not (Test-Path $exe)) { throw "Expected executable is missing: $exe" }
$hashes = Get-FileHash -Algorithm SHA256 $exe, $lock
Record "Hashes" { $hashes | Format-Table -AutoSize }
Record "64 MiB HIL" { & $exe --bytes 67108864 }

if ($ExerciseDisconnectRecovery) {
    $disconnectOut = Join-Path $output "disconnect-stdout.txt"
    $disconnectErr = Join-Path $output "disconnect-stderr.txt"
    Record "Physical disconnect failure" {
        "Unplug the device cable now; reconnect it after the failure is reported."
        $process = Start-Process `
            -FilePath $exe `
            -ArgumentList "--bytes", "$DisconnectBytes" `
            -RedirectStandardOutput $disconnectOut `
            -RedirectStandardError $disconnectErr `
            -PassThru
        Wait-ForDevicePresence $false $ReenumerationTimeoutSeconds
        if (-not $process.WaitForExit(10000)) {
            $process.Kill()
            throw "USB transfer did not fail within 10 seconds of disconnect"
        }
        Get-Content $disconnectOut, $disconnectErr -ErrorAction SilentlyContinue
        "exit=$($process.ExitCode)"
        if ($process.ExitCode -eq 0) {
            throw "Disconnect transfer unexpectedly returned success"
        }
    }
    Record "Re-enumeration and recovery" {
        "Reconnect the physical device cable now."
        Wait-ForDevicePresence $true $ReenumerationTimeoutSeconds
        & $exe --bytes $RecoveryBytes
    }
}

$manifest = [PSCustomObject]@{
    SchemaVersion = 1
    Status = "PASS"
    CollectedAtUtc = [DateTime]::UtcNow.ToString("o")
    Computer = $computer
    Vid = $Vid
    Pid = $Pid
    WinUsbBindings = $winUsbBindings
    Firmware = $firmware
    Hashes = @(
        foreach ($hash in $hashes) {
            [PSCustomObject]@{
                Path = $hash.Path
                Algorithm = $hash.Algorithm
                Hash = $hash.Hash
            }
        }
    )
    ExactEchoBytes = 67108864
    DisconnectRecoveryExercised = [bool]$ExerciseDisconnectRecovery
    EvidenceBoundary = [PSCustomObject]@{
        Covered = "native Windows interface-0 WinUSB binding, exact echo, host executable provenance, and associated firmware artifacts"
        NotCovered = "on-device firmware attestation, FS behavior, CAN data plane, installer, or signing"
    }
}
$manifestPath = Join-Path $output "manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $manifestPath

"PASS collector completed" | Tee-Object -FilePath $log -Append

$archive = "$output.zip"
if (Test-Path $archive) { Remove-Item -Force $archive }
Compress-Archive -Path (Join-Path $output "*") -DestinationPath $archive
$archiveHash = Get-FileHash -Algorithm SHA256 $archive
"$($archiveHash.Hash)  $([IO.Path]::GetFileName($archive))" |
    Set-Content -Encoding ASCII "$archive.sha256"
"Evidence archive: $archive"
"Evidence SHA-256: $($archiveHash.Hash)"
