param(
    [string]$AvdName = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Probe = Join-Path $ScriptDir "native_google_one_probe.py"

function Stop-Test([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $Probe)) {
    Stop-Test "native_google_one_probe.py is missing. Keep both files in the same project directory."
}

$PossibleSdks = @(
    $env:ANDROID_HOME,
    $env:ANDROID_SDK_ROOT,
    (Join-Path $env:LOCALAPPDATA "Android\Sdk")
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

$Sdk = $null
foreach ($Path in $PossibleSdks) {
    if (Test-Path (Join-Path $Path "platform-tools\adb.exe")) {
        $Sdk = $Path
        break
    }
}
if (-not $Sdk) {
    Stop-Test "Android SDK not found. Install Android Studio and Android SDK Platform-Tools first."
}

$Adb = Join-Path $Sdk "platform-tools\adb.exe"
$Emulator = Join-Path $Sdk "emulator\emulator.exe"
$env:PATH = "$(Join-Path $Sdk 'platform-tools');$(Join-Path $Sdk 'emulator');$env:PATH"
Write-Host "Android SDK: $Sdk"

function Online-Emulators {
    $Lines = @(& $Adb devices 2>$null)
    $Result = @()
    foreach ($Line in $Lines) {
        if ($Line -match '^(emulator-\d+)\s+device\s*$') {
            $Result += $Matches[1]
        }
    }
    return @($Result)
}

$Running = @(Online-Emulators)
if ($Running.Count -eq 0) {
    if (-not (Test-Path $Emulator)) {
        Stop-Test "Android Emulator is missing. Install it from Android Studio > SDK Manager > SDK Tools."
    }
    $Avds = @(& $Emulator -list-avds 2>$null | Where-Object { $_ -and $_.Trim() })
    if ($Avds.Count -eq 0) {
        Stop-Test "No virtual device found. In Android Studio > Device Manager create a Pixel phone using a Google Play system image."
    }
    if (-not $AvdName) {
        if ($Avds.Count -eq 1) {
            $AvdName = $Avds[0].Trim()
        } else {
            Write-Host "Virtual devices:"
            for ($i = 0; $i -lt $Avds.Count; $i++) {
                Write-Host ("  {0}. {1}" -f ($i + 1), $Avds[$i])
            }
            $Selected = Read-Host "Enter device number"
            $Index = 0
            if (-not [int]::TryParse($Selected, [ref]$Index) -or $Index -lt 1 -or $Index -gt $Avds.Count) {
                Stop-Test "Invalid device number."
            }
            $AvdName = $Avds[$Index - 1].Trim()
        }
    }
    if ($AvdName -notin $Avds) {
        Stop-Test "AVD '$AvdName' not found. Available: $($Avds -join ', ')"
    }
    Write-Host "Starting Android Emulator: $AvdName" -ForegroundColor Cyan
    Start-Process -FilePath $Emulator -ArgumentList @("-avd", $AvdName)
    Write-Host "Waiting for Android to boot..."
} else {
    Write-Host "Using an already running Android Emulator."
}

$Serial = $null
$Deadline = (Get-Date).AddMinutes(5)
while ((Get-Date) -lt $Deadline) {
    $Running = @(Online-Emulators)
    if ($Running.Count -gt 0) {
        $Serial = $Running[0]
        $Booted = (& $Adb -s $Serial shell getprop sys.boot_completed 2>$null | Out-String).Trim()
        if ($Booted -eq "1") { break }
    }
    Start-Sleep -Seconds 4
}
if (-not $Serial -or $Booted -ne "1") {
    Stop-Test "Emulator did not finish booting. Check BIOS virtualization and Windows Hypervisor Platform."
}

$env:ANDROID_SERIAL = $Serial
Write-Host "Android ready: $Serial" -ForegroundColor Green
$Play = (& $Adb -s $Serial shell pm path com.android.vending 2>$null | Out-String)
if ($Play -notmatch 'package:') {
    Stop-Test "This AVD does not have Google Play. Create a new AVD with a system image marked 'Google Play'."
}

Write-Host ""
Write-Host "Follow the sign-in and app-install screens INSIDE the Android emulator." -ForegroundColor Yellow
Write-Host "Never type your Google password into this script or Telegram."
Write-Host ""

Push-Location $ScriptDir
try {
    $Launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($Launcher) {
        & py -3 $Probe --interactive --wait-seconds 900 --screenshots
    } else {
        $Python = Get-Command "python" -ErrorAction SilentlyContinue
        if (-not $Python) {
            Stop-Test "Python 3 not found. Install Python 3 from python.org and retry."
        }
        & python $Probe --interactive --wait-seconds 900 --screenshots
    }
    Write-Host ""
    Write-Host "Result: $(Join-Path $ScriptDir 'native_test_results\report.json')" -ForegroundColor Green
} finally {
    Pop-Location
}
