# Lets the Jarvis website start Jarvis: registers jarvis:// links for this Windows user.
# Opening jarvis://start runs run_jarvis.bat (minimized). Anything after "jarvis://" is ignored,
# so a link can only start Jarvis, nothing else. Chrome asks before the first launch.
#
# Run once:   powershell -ExecutionPolicy Bypass -File setup_website_launch.ps1
# Undo:       powershell -ExecutionPolicy Bypass -File setup_website_launch.ps1 -Remove

param([switch]$Remove)

$key = "HKCU:\Software\Classes\jarvis"
if ($Remove) {
    Remove-Item $key -Recurse -ErrorAction SilentlyContinue
    "jarvis:// links removed."
    return
}

$bat = Join-Path $PSScriptRoot "run_jarvis.bat"
New-Item "$key\shell\open\command" -Force | Out-Null
Set-ItemProperty $key -Name "(default)" -Value "URL:Jarvis"
Set-ItemProperty $key -Name "URL Protocol" -Value ""
# No %1 on purpose: the link's contents are never passed to Jarvis.
Set-ItemProperty "$key\shell\open\command" -Name "(default)" -Value "`"$env:SystemRoot\System32\cmd.exe`" /c start `"Jarvis`" /min `"$bat`""
"jarvis:// links now start: $bat"
