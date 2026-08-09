param(
    [string]$OutputDirectory = "docs/evidence/phase1/windows-current",
    [string]$Vid = "34B7",
    [string]$Pid = "1236"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$output = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Force -Path $output | Out-Null
$log = Join-Path $output "phase1b-windows-collector.txt"

function Record([string]$Title, [scriptblock]$Command) {
    "`n## $Title" | Tee-Object -FilePath $log -Append
    $global:LASTEXITCODE = 0
    & $Command 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "$Title failed with exit code $LASTEXITCODE"
    }
}

Set-Content -Path $log -Value "Phase 1B Windows evidence collector"
Record "Windows" { Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber }
Record "Rust" { rustc +1.97.1 --version --verbose }
Record "Cargo" { cargo +1.97.1 --version --verbose }
Record "Visual Studio" {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio/Installer/vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "vswhere.exe is missing" }
    & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json
}
Record "PnP device" {
    $devices = Get-PnpDevice -PresentOnly |
        Where-Object { $_.InstanceId -match "VID_$Vid&PID_$Pid" }
    if (-not $devices) { throw "VID_$Vid&PID_$Pid is not present" }
    $devices | Format-List Status, Class, FriendlyName, InstanceId
}
Record "Format" { cargo +1.97.1 fmt --manifest-path "$root/host/Cargo.toml" --all --check }
Record "Build" { cargo +1.97.1 build --manifest-path "$root/host/Cargo.toml" --workspace --release --locked }
Record "Test" { cargo +1.97.1 test --manifest-path "$root/host/Cargo.toml" --workspace --release --locked }
Record "Clippy" { cargo +1.97.1 clippy --manifest-path "$root/host/Cargo.toml" --workspace --all-targets --release --locked -- -D warnings }

$exe = Join-Path $root "host/target/release/hpm-usb-smoke.exe"
$lock = Join-Path $root "host/Cargo.lock"
Record "Hashes" { Get-FileHash -Algorithm SHA256 $exe, $lock | Format-Table -AutoSize }
Record "64 MiB HIL" { & $exe --bytes 67108864 }

"PASS collector completed" | Tee-Object -FilePath $log -Append
