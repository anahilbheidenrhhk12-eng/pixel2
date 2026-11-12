$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot 'Repair-PixelConnection.ps1'
$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
. $path -LibraryOnly
$passed = New-Object 'System.Collections.Generic.List[string]'
$passed.Add('PowerShell syntax')
function Assert-True($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
$echo = Invoke-Adb $env:ComSpec @('/c', 'echo', 'device') 8000
Assert-True ($echo.Code -eq 0 -and $echo.Text.Trim() -eq 'device') 'Actual Windows process wrapper did not capture output'
$passed.Add('Windows process stdout')
$delayed = Invoke-Adb (Join-Path $PSHOME 'powershell.exe') @('-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep', '5') 250
Assert-True ($delayed.Code -eq 124) 'Actual Windows process timeout was not bounded'
$passed.Add('Windows process timeout')

function Reply([string]$Text, [int]$Code = 0) { return [pscustomobject]@{ Code = $Code; Text = $Text } }
function Invoke-Adb([string]$Executable, [string[]]$Arguments, [int]$TimeoutMs = 12000) {
    $key = $Arguments -join ' '
    $script:calls.Add($key)
    if ($key -eq 'start-server') { return Reply 'server running' }
    if ($key -eq 'devices') {
        if ($script:scenario -eq 'usb_only') { return Reply "List of devices attached`nusb-123 device" }
        if ($script:scenario -eq 'duplicate' -or $script:scenario -eq 'mixed') {
            return Reply "List of devices attached`nemulator-5554 offline`nemulator-5556 offline"
        }
        return Reply "List of devices attached`nemulator-5554 device"
    }
    if ($key -match '^-s (emulator-\d+) emu avd name$') {
        if ($script:scenario -eq 'wrong_avd' -or ($script:scenario -eq 'mixed' -and $Matches[1] -eq 'emulator-5554')) { return Reply "Other_AVD`nOK" }
        return Reply "Digi_Pixel_11_Pro_XL`nOK"
    }
    if ($key -match '^-s emulator-\d+ get-state$') {
        if ($script:scenario -eq 'unauthorized') { return Reply 'error: device unauthorized' 1 }
        if ($script:scenario -eq 'always_offline' -or (($script:scenario -eq 'offline' -or $script:scenario -eq 'mixed') -and -not $script:reconnected)) { return Reply 'error: device offline' 1 }
        return Reply 'device'
    }
    if ($key -match '^-s emulator-\d+ reconnect$') {
        $script:reconnected = $true
        return Reply 'reconnecting emulator transport'
    }
    if ($key -match ' shell getprop sys.boot_completed$') {
        if ($script:scenario -eq 'boot_pending') { return Reply '' }
        return Reply '1'
    }
    if ($key -match ' shell pm path android$') {
        $script:pmCount++
        if ($script:scenario -eq 'pm_failure' -or ($script:scenario -eq 'transient_pm' -and $script:pmCount -eq 1)) { return Reply "cmd: Can't find service: package" 1 }
        return Reply 'package:/system/framework/framework-res.apk'
    }
    if ($key -match ' shell service check activity$') { return Reply 'Service activity: found' }
    if ($key -match ' shell pm list packages com.google.android.apps.subscriptions.red$') {
        if ($script:scenario -eq 'missing_app') { return Reply '' }
        return Reply 'package:com.google.android.apps.subscriptions.red'
    }
    throw ('Unexpected ADB command in fixture: ' + $key)
}
function Case([string]$Name, [string]$Status, [bool]$Ready, [int]$Seconds = 3) {
    $script:scenario = $Name
    $script:reconnected = $false
    $script:pmCount = 0
    $script:calls = New-Object 'System.Collections.Generic.List[string]'
    $out = Join-Path $env:TEMP ('pixel-check-' + [Guid]::NewGuid().ToString('N'))
    try {
        $result = Invoke-PixelRepair 'fixture-adb.exe' 'Digi_Pixel_11_Pro_XL' $out $Seconds 0
        Assert-True ($result.status -eq $Status) ($Name + ': expected ' + $Status + ', got ' + ($result | ConvertTo-Json -Depth 5 -Compress))
        Assert-True ($result.android_ready -eq $Ready) ($Name + ': wrong readiness')
        $saved = Get-Content -LiteralPath (Join-Path $out 'pixel-connection-result.json') -Raw | ConvertFrom-Json
        Assert-True ($saved.status -eq $Status) ($Name + ': report missing or wrong')
        Assert-True (@($script:calls | Where-Object { $_ -match '\b(kill-server|reboot|tcpip|install|uninstall|wipe-data)\b' }).Count -eq 0) 'Unexpected destructive/global command'
        return $result
    } finally {
        Remove-Item -LiteralPath $out -Recurse -Force -ErrorAction SilentlyContinue
    }
}
$r = Case 'healthy' 'already_ready' $true
Assert-True (-not $r.reconnect_attempted -and $r.google_one_installed) 'Healthy device should not be reset'
$passed.Add('Already-ready target left intact')
$r = Case 'offline' 'reconnected_ready' $true
Assert-True ($r.reconnect_attempted -and @($script:calls | Where-Object { $_ -eq '-s emulator-5554 reconnect' }).Count -eq 1) 'Reconnect must be targeted and single'
$passed.Add('Offline target reconnect')
$r = Case 'always_offline' 'still_offline' $false 0
Assert-True (@($script:calls | Where-Object { $_ -match ' shell ' }).Count -eq 0) 'Offline device must not receive shell commands'
$passed.Add('Persistent offline is not reported as ready')
$r = Case 'unauthorized' 'authorization_required' $false 0
Assert-True (-not $r.reconnect_attempted) 'Unauthorized target should be left to the user'
$passed.Add('Unauthorized target unchanged')
$r = Case 'pm_failure' 'android_not_ready' $false 0
$passed.Add('Boot property alone is not readiness')
$r = Case 'boot_pending' 'android_not_ready' $false 0
$passed.Add('Pending Android boot')
$r = Case 'wrong_avd' 'target_not_found' $false 0
$passed.Add('Wrong AVD never targeted')
$r = Case 'usb_only' 'target_not_found' $false 0
$passed.Add('USB device never targeted')
$r = Case 'duplicate' 'check_failed' $false 0
Assert-True (-not $r.reconnect_attempted) 'Duplicate targets require disambiguation'
$passed.Add('Duplicate AVD refused')
$r = Case 'missing_app' 'already_ready' $true
Assert-True ($r.google_one_installed -eq $false) 'Missing Google One should be reported separately'
$passed.Add('Missing app reported separately')
$r = Case 'transient_pm' 'already_ready' $true
Assert-True ($script:pmCount -ge 3) 'Need two stable checks after a failed service check'
$passed.Add('Transient services need two stable checks')
$r = Case 'mixed' 'reconnected_ready' $true
Assert-True ($r.serial -eq 'emulator-5556') 'Wrong target selected'
Assert-True (-not $script:calls.Contains('-s emulator-5554 reconnect')) 'Other emulator was reset'
$passed.Add('Multiple emulators scoped to matching AVD')
Write-Host ('PASSED ' + $passed.Count + ' Windows checks (ADB states use fixtures; no real emulator or account).')
$passed | ForEach-Object { Write-Host ('PASS: ' + $_) }
