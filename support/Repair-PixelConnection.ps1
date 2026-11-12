# Local diagnostic for the existing Digi Pixel emulator. Windows PowerShell 5.1.
# No downloads, data wipes, emulator restart, account access or server-wide ADB reset.
[CmdletBinding()]
param(
    [string]$AdbPath = '',
    [string]$AvdName = 'Digi_Pixel_11_Pro_XL',
    [string]$ReportDirectory = $PSScriptRoot,
    [ValidateRange(0, 180)][int]$TimeoutSeconds = 60,
    [switch]$LibraryOnly
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Write-RepairLine([string]$Message) {
    Write-Host $Message
    if ($script:RepairLog) {
        Add-Content -LiteralPath $script:RepairLog -Value ((Get-Date -Format 'HH:mm:ss') + ' ' + $Message) -Encoding UTF8
    }
}

function Invoke-Adb([string]$Executable, [string[]]$Arguments, [int]$TimeoutMs = 12000) {
    # All arguments are fixed tokens or validated emulator serials. No shell is used.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Arguments -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMs)) {
            $process.Kill()  # This kills only this adb client process, never the emulator.
            [void]$process.WaitForExit(2000)
            return [pscustomobject]@{ Code = 124; Text = 'ADB command timed out' }
        }
        return [pscustomobject]@{ Code = $process.ExitCode; Text = ($stdout.Result + "`n" + $stderr.Result).Trim() }
    } finally { $process.Dispose() }
}

function Resolve-PixelAdb([string]$Supplied) {
    if ($Supplied) {
        if (-not (Test-Path -LiteralPath $Supplied -PathType Leaf)) { throw 'The specified adb.exe was not found.' }
        return (Resolve-Path -LiteralPath $Supplied).Path
    }
    $roots = @()
    if ($env:LOCALAPPDATA) {
        $roots += Join-Path $env:LOCALAPPDATA 'DigiPixelServer\android-sdk'
    }
    if ($env:ANDROID_HOME) { $roots += $env:ANDROID_HOME }
    if ($env:ANDROID_SDK_ROOT) { $roots += $env:ANDROID_SDK_ROOT }
    if ($env:LOCALAPPDATA) { $roots += Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    foreach ($root in ($roots | Select-Object -Unique)) {
        $candidate = Join-Path $root 'platform-tools\adb.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Installed ADB was not found. This helper does not install or download Android.'
}

function Find-PixelTarget([string]$Executable, [string]$ExpectedName) {
    $listing = Invoke-Adb $Executable @('devices')
    if ($listing.Code -ne 0) { throw ('Cannot read the ADB device list: ' + $listing.Text) }
    $found = @()
    foreach ($line in ($listing.Text -split '\r?\n')) {
        if ($line -match '^(emulator-\d+)\s+(device|offline|unauthorized)\b') {
            $serial = $Matches[1]
            # Emulator console lookup works independently of Android shell readiness.
            $name = Invoke-Adb $Executable @('-s', $serial, 'emu', 'avd', 'name') 6000
            if (($name.Code -eq 0) -and (($name.Text -split '\r?\n') -contains $ExpectedName)) {
                $found += $serial
            }
        }
    }
    if ($found.Count -gt 1) { throw 'More than one matching Pixel emulator is running. Close duplicates manually and retry.' }
    if ($found.Count -eq 1) { return $found[0] }
    return $null
}

function Read-PixelState([string]$Executable, [string]$Serial) {
    $reply = Invoke-Adb $Executable @('-s', $Serial, 'get-state') 6000
    if (($reply.Code -eq 0) -and $reply.Text.Trim() -eq 'device') { return 'device' }
    if ($reply.Text -match '\boffline\b') { return 'offline' }
    if ($reply.Text -match '\bunauthorized\b') { return 'unauthorized' }
    return 'unavailable'
}

function Wait-PixelReady([string]$Executable, [string]$Serial, [int]$Seconds, [int]$PollMs = 2000) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $stable = 0
    $lastText = ''
    $last = [ordered]@{ state = 'unavailable'; booted = $false; package_manager = $false; activity_manager = $false }
    do {
        $last.state = Read-PixelState $Executable $Serial
        $last.booted = $false
        $last.package_manager = $false
        $last.activity_manager = $false
        if ($last.state -eq 'device') {
            $boot = Invoke-Adb $Executable @('-s', $Serial, 'shell', 'getprop', 'sys.boot_completed') 8000
            $last.booted = $boot.Code -eq 0 -and $boot.Text.Trim() -eq '1'
            if ($last.booted) {
                $pm = Invoke-Adb $Executable @('-s', $Serial, 'shell', 'pm', 'path', 'android') 10000
                $activity = Invoke-Adb $Executable @('-s', $Serial, 'shell', 'service', 'check', 'activity') 8000
                $last.package_manager = $pm.Code -eq 0 -and $pm.Text -match '(?m)^package:.+\.apk\s*$'
                $last.activity_manager = $activity.Code -eq 0 -and $activity.Text -match '(?i)Service activity:\s*found\b'
            }
        }
        if ($last.state -eq 'device' -and $last.booted -and $last.package_manager -and $last.activity_manager) {
            $stable++
        } else { $stable = 0 }
        $text = 'ADB: {0} | Android boot: {1} | Package Manager: {2} | Activity Manager: {3}' -f $last.state, $last.booted, $last.package_manager, $last.activity_manager
        if ($text -ne $lastText) { Write-RepairLine $text; $lastText = $text }
        if ($stable -ge 2) {
            return [pscustomobject]@{ Ready = $true; Snapshot = $last }
        }
        if ($clock.Elapsed.TotalSeconds -ge $Seconds) { break }
        if ($PollMs -gt 0) { Start-Sleep -Milliseconds $PollMs }
    } while ($true)
    return [pscustomobject]@{ Ready = $false; Snapshot = $last }
}

function Invoke-PixelRepair([string]$Executable, [string]$ExpectedName, [string]$OutputFolder, [int]$Seconds = 60, [int]$PollMs = 2000) {
    [void](New-Item -ItemType Directory -Path $OutputFolder -Force)
    $script:RepairLog = Join-Path $OutputFolder 'pixel-connection-result.txt'
    Set-Content -LiteralPath $script:RepairLog -Value 'Digi Pixel connection check - no data changes' -Encoding UTF8
    $report = [ordered]@{ checked_at = (Get-Date).ToString('o'); status = 'checking'; serial = $null; avd = $ExpectedName; reconnect_attempted = $false; android_ready = $false; google_one_installed = $null }
    try {
        Write-RepairLine 'Checking the existing Pixel emulator. No reinstall or data reset.'
        $start = Invoke-Adb $Executable @('start-server') 15000
        if ($start.Code -ne 0) { throw ('ADB service could not start: ' + $start.Text) }
        $serial = Find-PixelTarget $Executable $ExpectedName
        if (-not $serial) {
            $report.status = 'target_not_found'
            Write-RepairLine 'The named Pixel emulator was not found. Keep its Android window open, then retry.'
            return [pscustomobject]$report
        }
        $report.serial = $serial
        $initial = Read-PixelState $Executable $serial
        Write-RepairLine ('Target verified: ' + $ExpectedName + ' / ' + $serial + ' / ' + $initial)
        if ($initial -eq 'offline') {
            $report.reconnect_attempted = $true
            Write-RepairLine 'Reconnecting ONLY this emulator transport once...'
            $reconnect = Invoke-Adb $Executable @('-s', $serial, 'reconnect') 10000
            Write-RepairLine ('Reconnect response: ' + $reconnect.Text)
        } elseif ($initial -eq 'unauthorized') {
            $report.status = 'authorization_required'
            Write-RepairLine 'ADB authorization is required on the Android screen. No keys or settings were changed.'
            return [pscustomobject]$report
        }
        $result = Wait-PixelReady $Executable $serial $Seconds $PollMs
        $report.android_ready = $result.Ready
        $report['checks'] = $result.Snapshot
        if (-not $result.Ready) {
            $report.status = if ($result.Snapshot.state -eq 'offline') { 'still_offline' } else { 'android_not_ready' }
            Write-RepairLine 'NOT READY. The current connection or Android services have not passed the checks.'
            return [pscustomobject]$report
        }
        $app = Invoke-Adb $Executable @('-s', $serial, 'shell', 'pm', 'list', 'packages', 'com.google.android.apps.subscriptions.red') 10000
        if ($app.Code -eq 0 -and $app.Text -notmatch '(?i)error|exception|can.t find service') {
            $report.google_one_installed = ($app.Text -split '\r?\n') -contains 'package:com.google.android.apps.subscriptions.red'
        }
        $report.status = if ($report.reconnect_attempted) { 'reconnected_ready' } else { 'already_ready' }
        Write-RepairLine 'READY. ADB and Android system services passed two consecutive checks.'
        if ($report.google_one_installed -eq $true) {
            Write-RepairLine 'Google One is installed. Return to Digi Pixel Server and press OPEN GOOGLE ONE APP.'
        } elseif ($report.google_one_installed -eq $false) {
            Write-RepairLine 'Google One is not installed. Use OPEN GOOGLE ONE APP to open its Play Store page.'
        } else { Write-RepairLine 'Google One installation status could not be confirmed.' }
        return [pscustomobject]$report
    } catch {
        $report.status = 'check_failed'
        $report['error'] = $_.Exception.Message
        Write-RepairLine ('CHECK FAILED: ' + $_.Exception.Message)
        return [pscustomobject]$report
    } finally {
        $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputFolder 'pixel-connection-result.json') -Encoding UTF8
        Write-RepairLine ('Report saved: ' + $script:RepairLog)
    }
}

if (-not $LibraryOnly) {
    try {
        $chosen = Resolve-PixelAdb $AdbPath
        $result = Invoke-PixelRepair $chosen $AvdName $ReportDirectory $TimeoutSeconds
        if (-not $result.android_ready) { exit 2 }
        exit 0
    } catch {
        Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
        exit 1
    }
}
